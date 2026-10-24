"""Selected G2B tender: ten-year ACTUAL opening and final-award result history.

Reference is the selected original notice's ten-digit detailed product code
8111159901; eight-digit 81111599 notices are only DISCOVERY CANDIDATES, never
historical opening/award statistics. Each candidate is checked against an actual
original G2B attachment before its outcome may enter the case. No title/LLM.
"""
from __future__ import annotations
from datetime import date,datetime,timedelta,timezone
from hashlib import sha256
from html.parser import HTMLParser
from urllib.parse import urljoin,urlparse,parse_qs
from urllib.request import Request,urlopen
import json,re,logging
from playwright.sync_api import sync_playwright
from db import session
from g2b_case_10y import CASE_BID,BEGIN,END
from g2b_categories import upsert_verified_codes
from g2b_documents import extract_file

DETAIL="8111159901"
PARENT="81111599"
ID=re.compile(r"^(R\d{2}BK\d{8}|\d{11})$")
ATC_PATH="/pn/pnp/pnpe/UntyAtchFile/downloadFile.do"
SPEC_MARKER=re.compile(r"(?:세\s*부\s*품\s*명\s*번\s*호|세\s*부\s*품\s*명|직접생산확인증명서)")
SPEC_CODE=re.compile(r"(?<!\d)8111159901(?!\d)")
OTHER_CODE=re.compile(r"(?<!\d)81111599\d{2}(?!\d)")

class OriginalLinks(HTMLParser):
    def __init__(self):
        super().__init__();self.links=[];self.active=None
    def handle_starttag(self,tag,attrs):
        if tag=="a":
            a=dict(attrs);self.active={"href":a.get("href",""),"name":""}
    def handle_data(self,data):
        if self.active:self.active["name"]+=data
    def handle_endtag(self,tag):
        if tag=="a" and self.active:
            self.links.append(self.active);self.active=None

def ensure_schema():
    with session() as db:
        db.execute("""CREATE TABLE IF NOT EXISTS procureflow.g2b_case_outcome_verification(
            case_bid_no text NOT NULL, bid_no text NOT NULL,bid_ord text NOT NULL,
            expected_detail10 text NOT NULL,
            status text NOT NULL DEFAULT 'pending',
            source_uri text NOT NULL DEFAULT '',
            original_sha256 text NOT NULL DEFAULT '',
            matched_code text NOT NULL DEFAULT '',
            reason text NOT NULL DEFAULT '',
            attempts int NOT NULL DEFAULT 0,
            checked_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY(case_bid_no,bid_no,bid_ord))""")
        db.execute("""CREATE INDEX IF NOT EXISTS ix_g2b_case_outcome_verification_status
                     ON procureflow.g2b_case_outcome_verification(case_bid_no,status,checked_at)""")
        db.execute("""CREATE TABLE IF NOT EXISTS procureflow.g2b_case_outcome_attempts(
            id bigserial PRIMARY KEY,case_bid_no text NOT NULL,
            bid_no text NOT NULL,bid_ord text NOT NULL,
            stage text NOT NULL, status text NOT NULL,
            detail jsonb NOT NULL DEFAULT '{}'::jsonb,
            created_at timestamptz NOT NULL DEFAULT now())""")

def candidates_to_verify(limit=5):
    """CANDIDATES ONLY. These are not a result, nor proven ten-digit category."""
    ensure_schema()
    with session() as db:
        rows=db.execute("""SELECT h.hist_notice_no AS bid_no,
              h.hist_notice_ord AS bid_ord,h.published_on,h.source_url,
              h.title,
              EXISTS(SELECT 1 FROM procureflow.bid_results r
                     WHERE r.source='g2b'
                     AND r.bid_ntce_no=h.hist_notice_no
                     AND r.bid_ntce_ord=h.hist_notice_ord
                     AND r.result_kind IN('opening','award')) AS has_existing_result
             FROM procureflow.g2b_case_10yr_history h
             LEFT JOIN procureflow.g2b_case_outcome_verification v
              ON v.case_bid_no=h.case_bid_no AND v.bid_no=h.hist_notice_no
             AND v.bid_ord=h.hist_notice_ord
             WHERE h.case_bid_no=%s AND h.classification8=%s
               AND h.published_on BETWEEN %s AND %s
               AND h.hist_notice_no<>%s
               AND (v.status IS NULL OR
                   (v.status IN ('error','original_unavailable')
                    AND v.checked_at<now()-interval '24 hours'))
             ORDER BY has_existing_result DESC,h.published_on DESC,h.hist_notice_no DESC
             LIMIT %s""",(CASE_BID,PARENT,BEGIN,END,CASE_BID,
                           max(1,min(10,int(limit))))).fetchall()
    return [dict(x) for x in rows]

def _save_verification(bid_no,bid_ord,status,source_uri="",digest="",reason="",code=""):
    with session() as db:
        db.execute("""INSERT INTO procureflow.g2b_case_outcome_verification(
           case_bid_no,bid_no,bid_ord,expected_detail10,status,
           source_uri,original_sha256,reason,matched_code,attempts)
           VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,1)
           ON CONFLICT(case_bid_no,bid_no,bid_ord) DO UPDATE SET
             status=excluded.status,source_uri=excluded.source_uri,
             original_sha256=excluded.original_sha256,
             reason=excluded.reason,matched_code=excluded.matched_code,
             attempts=procureflow.g2b_case_outcome_verification.attempts+1,
             checked_at=now()
         """,(CASE_BID,bid_no,bid_ord,DETAIL,status,source_uri,digest,
              reason[:320],code))
        db.execute("""INSERT INTO procureflow.g2b_case_outcome_attempts(
              case_bid_no,bid_no,bid_ord,stage,status,detail)
             VALUES(%s,%s,%s,'ten_digit_verify',%s,%s::jsonb)""",
             (CASE_BID,bid_no,bid_ord,status,
              json.dumps({"source":source_uri,"reason":reason[:250],
                          "original_sha256":digest,"code":code})))

def _urls_from_mirror(html,bid_no,bid_ord,base):
    p=OriginalLinks();p.feed(html or "")
    links=[]
    for a in p.links:
        url=urljoin(base,a["href"])
        u=urlparse(url)
        if u.scheme!="https" or u.hostname!="www.g2b.go.kr" or u.path!=ATC_PATH:
            continue
        q=parse_qs(u.query)
        if q.get("bidPbancNo")!=[bid_no] or q.get("bidPbancOrd")!=[bid_ord]:
            continue
        label=a["name"].strip()
        suffix=label.lower().rsplit(".",1)[-1]
        if suffix not in ("hwp","hwpx","pdf","docx"):continue
        links.append((url,label))
    return links

def original_has_exact_code(text):
    """Must occur in an explicit sub-product / direct production context."""
    source=" ".join((text or "").split())
    matches=list(SPEC_CODE.finditer(source))
    for m in matches:
        before=source[max(0,m.start()-140):m.start()]
        if SPEC_MARKER.search(before):
            return True
    return False

def verify_candidate(row,ctx):
    no=str(row["bid_no"]);ord_=str(row["bid_ord"])
    if not ID.fullmatch(no) or not re.fullmatch(r"\d{3}",ord_):
        return {"status":"invalid_candidate","bid_no":no}
    if no==CASE_BID:return {"status":"excluded_target","bid_no":no}
    url=row.get("source_url") or ""
    # An existing official direct classification field is already sufficient.
    with session() as db:
        official=db.execute("""SELECT code,source_uri FROM
              procureflow.g2b_notice_categories
              WHERE bid_no=%s AND bid_ord=%s
                AND code_type='detail10' AND code=%s
                AND evidence_level='official_direct' LIMIT 1""",
                (no,ord_,DETAIL)).fetchone()
    if official:
        _save_verification(no,ord_,"verified_exact_10",official["source_uri"],
                           reason="already verified original detail10",code=DETAIL)
        return {"status":"verified_exact_10","bid_no":no,"source":official["source_uri"]}
    if not url.startswith("https://bid24.kr/b/"):
        _save_verification(no,ord_,"original_unavailable",url,reason="no supported original-file index")
        return {"status":"original_unavailable","bid_no":no}
    try:
        resp=ctx.get(url,timeout=16000)
        if resp.status!=200:raise RuntimeError("mirror_http_"+str(resp.status))
        urls=_urls_from_mirror(resp.text(),no,ord_,url)
        if not urls:
            _save_verification(no,ord_,"original_unavailable",url,
                               reason="mirror has no original government document URLs")
            return {"status":"original_unavailable","bid_no":no}
        tested=0
        for original_url,label in urls[:4]:
            try:
                res=ctx.get(original_url,timeout=16000)
                if res.status!=200:continue
                raw=res.body()
                if len(raw)>12*1024*1024:continue
                state,text=extract_file(label,raw)
                if state!="parsed":continue
                tested+=1
                digest=sha256(raw).hexdigest()
                if original_has_exact_code(text):
                    # Evidence is the original file itself, not a mirror headline.
                    upsert_verified_codes(no,ord_,"service",
                         {"dtilPrdctClsfcNo":DETAIL,"prdctClsfcNo":PARENT},
                         original_url,evidence_level="official_direct")
                    _save_verification(no,ord_,"verified_exact_10",original_url,
                                       digest,"explicit ten-digit code in original government file",
                                       DETAIL)
                    return {"status":"verified_exact_10","bid_no":no,
                            "evidence_sha256":digest,
                            "source":original_url}
                # A document may list a different item or omit code; do not reject
                # candidate until checked all accessible original files.
            except Exception as exc:
                logging.warning("G2B_DETAIL10_DOC_CHECK notice=%s reason=%s",no,
                                type(exc).__name__+":"+str(exc)[:80])
        status="original_no_exact_code" if tested else "original_unavailable"
        _save_verification(no,ord_,status,url,reason="original_files_parsed_"+str(tested))
        return {"status":status,"bid_no":no,"tested_originals":tested}
    except Exception as exc:
        msg=type(exc).__name__+":"+str(exc)[:140]
        _save_verification(no,ord_,"error",url,reason=msg)
        return {"status":"error","bid_no":no,"reason":msg}

def exact_result_query(db,limit=200,offset=0):
    # Join by BOTH notice and notice round. Do not count bid status-only as bid.
    # Date sourced from observed historical notice; no invented dates.
    return db.execute("""SELECT r.bid_ntce_no,r.bid_ntce_ord,
           r.bid_clsfc_no,r.rbid_no,r.result_kind,
           r.company,r.amount,r.rate,r.rank,r.result_status,
           r.raw,r.agency,r.title,r.record_key,
           h.published_on AS historical_notice_date,
           c.source_uri AS detail_code_original_url,
           v.original_sha256 AS detail_code_original_sha256
         FROM procureflow.g2b_case_outcome_verification v
         JOIN procureflow.g2b_notice_categories c
           ON c.bid_no=v.bid_no AND c.bid_ord=v.bid_ord
            AND c.code_type='detail10' AND c.code=%s
            AND c.evidence_level='official_direct'
         JOIN procureflow.g2b_case_10yr_history h
           ON h.case_bid_no=v.case_bid_no
          AND h.hist_notice_no=v.bid_no AND h.hist_notice_ord=v.bid_ord
         JOIN procureflow.bid_results r ON r.source='g2b'
           AND r.bid_ntce_no=v.bid_no AND r.bid_ntce_ord=v.bid_ord
         WHERE v.case_bid_no=%s AND v.expected_detail10=%s
           AND v.status='verified_exact_10'
           AND h.published_on BETWEEN %s AND %s
           AND v.bid_no<>%s
           AND r.result_kind IN('opening','award')
         ORDER BY h.published_on DESC,r.bid_ntce_no,
                  r.bid_clsfc_no,r.rbid_no,r.result_kind,r.rank,r.record_key
         LIMIT %s OFFSET %s""",(DETAIL,CASE_BID,DETAIL,BEGIN,END,
                                CASE_BID,max(1,min(1000,int(limit))),
                                max(0,int(offset)))).fetchall()

def actual_result_status(limit=200):
    ensure_schema()
    with session() as db:
        candidates=db.execute("""SELECT count(*) AS n
             FROM procureflow.g2b_case_10yr_history h
             WHERE h.case_bid_no=%s AND h.classification8=%s
                 AND h.published_on BETWEEN %s AND %s
                 AND h.hist_notice_no<>%s
         """,(CASE_BID,PARENT,BEGIN,END,CASE_BID)).fetchone()["n"]
        by_state=db.execute("""SELECT status,count(*) AS n
             FROM procureflow.g2b_case_outcome_verification
             WHERE case_bid_no=%s GROUP BY status ORDER BY status
         """,(CASE_BID,)).fetchall()
        totals=db.execute("""SELECT count(DISTINCT(v.bid_no,v.bid_ord)) AS n,
             count(*) FILTER(WHERE r.result_kind='opening') AS openings,
             count(*) FILTER(WHERE r.result_kind='opening' AND
                r.amount <> '') AS opening_amount_rows,
             count(*) FILTER(WHERE r.result_kind='award') AS awards
           FROM procureflow.g2b_case_outcome_verification v
           JOIN procureflow.g2b_notice_categories c
            ON c.bid_no=v.bid_no AND c.bid_ord=v.bid_ord
             AND c.code_type='detail10' AND c.code=%s
             AND c.evidence_level='official_direct'
           JOIN procureflow.g2b_case_10yr_history h
            ON h.hist_notice_no=v.bid_no AND h.hist_notice_ord=v.bid_ord
             AND h.case_bid_no=v.case_bid_no
           LEFT JOIN procureflow.bid_results r
            ON r.source='g2b' AND r.bid_ntce_no=v.bid_no
              AND r.bid_ntce_ord=v.bid_ord
              AND r.result_kind IN('opening','award')
           WHERE v.case_bid_no=%s AND v.status='verified_exact_10'
             AND h.published_on BETWEEN %s AND %s
             AND v.bid_no<>%s
         """,(DETAIL,CASE_BID,BEGIN,END,CASE_BID)).fetchone()
        rows=exact_result_query(db,limit)
        last=db.execute("""SELECT bid_no,stage,status,detail,created_at
                  FROM procureflow.g2b_case_outcome_attempts
                  WHERE case_bid_no=%s ORDER BY id DESC LIMIT 12""",
                  (CASE_BID,)).fetchall()
    return {"target_bid_no":CASE_BID,"exact_detail_product_code":DETAIL,
            "period_start":BEGIN,"period_end":END,
            "candidate_notice_count_not_results":candidates,
            "verified_exact_code_history_and_result_counts":{
                "verified_notice_rounds":totals["n"],
                "opening_bidder_rows":totals["openings"],
                "opening_amount_rows":totals["opening_amount_rows"],
                "confirmed_award_rows":totals["awards"]},
            "verification_states":by_state,
            "scope_is_exact_product_8111159901":True,
            "ten_year_coverage_completed":False,
            "actual_opening_and_award_rows":rows,
            "recent_collection_attempts":last,
            "ten_year_all_bids_verified":False,
            "eight_digit_notice_count_not_used_as_result":True,
            "bid_submitted":False}

def _record_attempt(bid_no,bid_ord,stage,status,detail):
    with session() as db:
        db.execute("""INSERT INTO procureflow.g2b_case_outcome_attempts(
               case_bid_no,bid_no,bid_ord,stage,status,detail)
               VALUES(%s,%s,%s,%s,%s,%s::jsonb)""",
               (CASE_BID,bid_no,bid_ord,stage,status,
                json.dumps(detail,ensure_ascii=False,default=str)[:18000]))

def _award_from_official_opening(bid_no,bid_ord,entry):
    """Only an EXPLICIT final winner in actual G2B opening payload is an award.

    Rank 1, a provisional preferred bidder, and mere opening-complete status
    do not qualify. Never declare 'not found' to mean 'no award exists'.
    """
    from g2b_bid_collector import _final_award,normalize_item,save_batch
    from hashlib import sha256
    if entry.get("bid_no")!=bid_no or entry.get("bid_ord")!=bid_ord:
        raise ValueError("official_opening_notice_identity_mismatch")
    info=entry.get("bid_info") or {}
    etc=entry.get("etc_data") or {}
    winner_name=_final_award(info,etc)
    if not winner_name:
        return {"status":"winner_not_confirmed_in_available_official_opening",
                "winner_confirmed":False,"saved":0,
                "evidence":"no_explicit_final_winner_and_completion_status"}
    eligible=[(i,x) for i,x in enumerate(entry.get("bidders") or [])
              if str(x.get("grpNm") or "").strip()==winner_name]
    if len(eligible)!=1:
        return {"status":"winner_name_not_unique_in_bidder_rows",
                "winner_confirmed":False,"saved":0,
                "candidate_name_redacted":True}
    i,x=eligible[0]
    row=normalize_item({**x,"bid_no":bid_no,"bid_ord":bid_ord,
                         "bidClsfNo":str(info.get("bidClsfNo") or "0"),
                         "bidPrgrsOrd":str(info.get("bidPrgrsOrd") or "000"),
                         "result_status":"최종낙찰확정"},
                       "service","award","g2b_web_confirmed_award",i)
    if not row:return {"status":"invalid_official_winner_data",
                       "winner_confirmed":False,"saved":0}
    if not row["amount"]:
        return {"status":"final_winner_exists_but_amount_not_released",
                "winner_confirmed":False,"saved":0}
    row["record_key"]=sha256(
        ("g2b|official-verified-final|"+bid_no+"|"+bid_ord+"|"+
         row["bid_clsfc_no"]+"|"+row["rbid_no"]).encode()).hexdigest()[:40]
    row["raw"]={**row["raw"],
                "evidence":"official_opening_explicit_final_winner",
                "winner_company":row["company"],
                "official_final_winner_name_present":True,
                "completion_signal_present":True}
    saved,new=save_batch([row])
    return {"status":"official_explicit_final_winner_confirmed",
            "winner_confirmed":True,"company":row["company"],
            "amount":row["amount"],"saved":saved,"new":new}


def fetch_one_final_award(bid_no,bid_ord,published_on):
    """Use working G2B official opening endpoint, NOT broken Nuri HTTP 422.

    All inputs must already pass the 10-digit original-product gate.
    The same official response can confirm the final winner only when it
    independently carries an explicit completion signal and matching bidder.
    """
    from g2b_bid_collector import BASE,fetch_opening
    from playwright.sync_api import sync_playwright
    if not ID.fullmatch(bid_no) or not re.fullmatch(r"\d{3}",bid_ord):
        raise ValueError("invalid_official_bid_number")
    out={"bid_no":bid_no,"bid_ord":bid_ord,
         "status":"winner_not_confirmed_in_available_official_opening",
         "winner_confirmed":False,"saved":0,
         "source":"g2b_official_public_websquare"}
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True,args=[
            "--no-sandbox","--disable-dev-shm-usage"])
        ctx=browser.new_context(locale="ko-KR",timezone_id="Asia/Seoul")
        try:
            resp=ctx.request.get(BASE,timeout=20000)
            if resp.status>=400:raise RuntimeError("g2b_homepage_http_"+str(resp.status))
            entry=fetch_opening(ctx,bid_no,bid_ord,max_pages=2)
            out.update(_award_from_official_opening(bid_no,bid_ord,entry))
        except LookupError:
            out["status"]="official_opening_not_published"
        finally:
            ctx.close();browser.close()
    return out


def run_batch(limit=3,opening_limit=3):
    """Verify exact-code original docs first; then request actual openings.

    Candidates are a bounded workload only. Never expose them as matches.
    """
    ensure_schema()
    cand=candidates_to_verify(limit)
    output={"case":CASE_BID,"exact_detail_product_code":DETAIL,
            "candidate_checked":0,"verified_exact_code":0,
            "opening_queried":0,"opening_bidder_rows_saved":0,
            "final_awards_verified":0,"errors":[],"evidence":[]}
    with sync_playwright() as pw:
        ctx=pw.request.new_context(timeout=16000,user_agent="ProcureFlow-G2B-ActualBidResult/1.0")
        try:
            for row in cand:
                outcome=verify_candidate(row,ctx)
                output["candidate_checked"]+=1
                output["evidence"].append(outcome)
                if outcome["status"]=="verified_exact_10":
                    output["verified_exact_code"]+=1
        finally:ctx.dispose()
    # First verify exact official product code; only those may be opened.
    with session() as db:
        eligible=db.execute("""SELECT v.bid_no,v.bid_ord,h.published_on
          FROM procureflow.g2b_case_outcome_verification v
          JOIN procureflow.g2b_case_10yr_history h
            ON h.case_bid_no=v.case_bid_no
           AND h.hist_notice_no=v.bid_no AND h.hist_notice_ord=v.bid_ord
          WHERE v.case_bid_no=%s AND v.status='verified_exact_10'
            AND NOT EXISTS (
               SELECT 1 FROM procureflow.g2b_case_outcome_attempts x
               WHERE x.case_bid_no=v.case_bid_no AND x.bid_no=v.bid_no
                 AND x.bid_ord=v.bid_ord AND x.stage='opening_collection'
                 AND x.created_at>now()-interval '12 hours')
          ORDER BY v.checked_at DESC LIMIT %s""",
           (CASE_BID,max(1,min(8,int(opening_limit))))).fetchall()
    if eligible:
        # Direct public opening endpoint has already been exercised by the
        # general g2b bidder collector; it stores real bidder rows and never
        # converts rank 1 to a final award without official winner evidence.
        from g2b_bid_collector import collect
        for item in eligible:
            bid_no=item["bid_no"];bid_ord=item["bid_ord"]
            try:
                r=collect(days=7,pages=1,
                          bid_numbers=[bid_no+"-"+bid_ord])
                output["opening_queried"]+=1
                output["opening_bidder_rows_saved"]+=int(r.get("new",0))
                stat="attempted"
                if r.get("errors"):stat="partial"
                with session() as db:
                    db.execute("""INSERT INTO procureflow.g2b_case_outcome_attempts(
                      case_bid_no,bid_no,bid_ord,stage,status,detail)
                      VALUES(%s,%s,%s,'opening_collection',%s,%s::jsonb)""",
                       (CASE_BID,bid_no,bid_ord,stat,json.dumps(r,ensure_ascii=False,default=str)[:15000]))
                if r.get("errors"):output["errors"].append({"bid_no":bid_no,"reason":r["errors"][:3]})
                # Final confirmed award is fetched separately, never inferred
                # from rank one, and every official unsuccessful lookup audited.
                try:
                    award=fetch_one_final_award(bid_no,bid_ord,item["published_on"])
                    output["final_awards_verified"]+=int(award.get("winner_confirmed",False))
                    _record_attempt(bid_no,bid_ord,"final_award_collection",
                                    award["status"],award)
                except Exception as exc:
                    msg=type(exc).__name__+":"+str(exc)[:145]
                    output["errors"].append({"bid_no":bid_no,"award":msg})
                    _record_attempt(bid_no,bid_ord,"final_award_collection","error",
                                    {"reason":msg})
            except Exception as exc:
                output["errors"].append({"bid_no":bid_no,
                                         "reason":type(exc).__name__+":"+str(exc)[:120]})
    return output
