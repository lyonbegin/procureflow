"""Evidence-gated, one-tender ProcureFlow workflow for the 104-function catalog.

The engine coordinates official notice evidence, category-exact 10-year search,
opening/award associations, eligibility, documented quotes and bid package
generation. A function is 'verified' only when actual source evidence exists.
It will NEVER click the bid participation / submission button.
"""
from __future__ import annotations
from datetime import date,datetime,timezone
from hashlib import sha256
from decimal import Decimal,InvalidOperation
import json,re
from db import session
from g2b_feature_registry import FEATURES,REQUIREMENTS,GROUPS,FEATURE_GATES
from g2b_case_10y import CASE_BID,CAT8,BEGIN,END,status as history_status

SOURCE_RE=re.compile(r"^(?:R\d{2}BK\d{8}|\d{11})$")
STATES=("missing","queued","running","partial","blocked","verified","error")
SINGLE_CASE=CASE_BID

def ensure_engine():
    with session() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS procureflow.g2b_case_control(
             bid_no text PRIMARY KEY,bid_ord text NOT NULL DEFAULT '000',
             category8 text NOT NULL DEFAULT '',
             title text NOT NULL DEFAULT '',state text NOT NULL DEFAULT 'selected',
             selected_at timestamptz NOT NULL DEFAULT now(),
             updated_at timestamptz NOT NULL DEFAULT now(),
             context jsonb NOT NULL DEFAULT '{}'::jsonb,
             CHECK(state IN ('selected','collecting','paused','blocked',
                               'review','ready_for_manual_participation')))""")
        c.execute("""CREATE TABLE IF NOT EXISTS procureflow.g2b_case_features(
             bid_no text NOT NULL,feature_no int NOT NULL,
             state text NOT NULL DEFAULT 'missing',note text NOT NULL DEFAULT '',
             evidence_ids jsonb NOT NULL DEFAULT '[]'::jsonb,
             attempt int NOT NULL DEFAULT 0,updated_at timestamptz NOT NULL DEFAULT now(),
             PRIMARY KEY(bid_no,feature_no),CHECK(feature_no BETWEEN 1 AND 104))""")
        c.execute("""CREATE TABLE IF NOT EXISTS procureflow.g2b_case_evidence(
             bid_no text NOT NULL,evidence_type text NOT NULL,
             reference text NOT NULL,
             state text NOT NULL DEFAULT 'observed',
             source_url text NOT NULL DEFAULT '',content_sha text NOT NULL DEFAULT '',
             summary text NOT NULL DEFAULT '',
             structured jsonb NOT NULL DEFAULT '{}'::jsonb,
             verified_source boolean NOT NULL DEFAULT false,
             recorded_at timestamptz NOT NULL DEFAULT now(),
             PRIMARY KEY(bid_no,evidence_type,reference))""")
        c.execute("""CREATE TABLE IF NOT EXISTS procureflow.g2b_case_decisions(
             bid_no text NOT NULL,kind text NOT NULL,key text NOT NULL,
             value jsonb NOT NULL DEFAULT '{}'::jsonb,
             state text NOT NULL DEFAULT 'draft',
             origin text NOT NULL DEFAULT 'local',
             updated_at timestamptz NOT NULL DEFAULT now(),
             PRIMARY KEY(bid_no,kind,key))""")
        c.execute("""CREATE TABLE IF NOT EXISTS procureflow.g2b_case_runs(
             id bigserial PRIMARY KEY,bid_no text NOT NULL,
             phase text NOT NULL,state text NOT NULL DEFAULT 'queued',
             result jsonb NOT NULL DEFAULT '{}'::jsonb,
             error text NOT NULL DEFAULT '',
             started_at timestamptz,finished_at timestamptz,
             created_at timestamptz NOT NULL DEFAULT now())""")
        c.execute("""CREATE TABLE IF NOT EXISTS procureflow.g2b_case_events(
             id bigserial PRIMARY KEY,bid_no text NOT NULL,
             action text NOT NULL,details jsonb NOT NULL DEFAULT '{}'::jsonb,
             created_at timestamptz NOT NULL DEFAULT now())""")
        c.execute("""CREATE INDEX IF NOT EXISTS ix_pf_case_run_recent
                     ON procureflow.g2b_case_runs(bid_no,id DESC)""")
        c.execute("""INSERT INTO procureflow.g2b_case_control
              (bid_no,bid_ord,category8,title,context)
              VALUES (%s,'000','81111599',%s,%s::jsonb)
              ON CONFLICT(bid_no) DO NOTHING""",
            (SINGLE_CASE,"철강·금속 AX실증센터 스마트 실증장비 모니터링 시스템용 소프트웨어 개발 용역",
             json.dumps({"provenance":"user_selected_case_and_secondary_public_category",
                         "official_notice_verified":False,"submission_permitted":False})))
        for x in FEATURES:
            c.execute("""INSERT INTO procureflow.g2b_case_features
                (bid_no,feature_no) VALUES (%s,%s) ON CONFLICT DO NOTHING""",
                      (SINGLE_CASE,x["number"]))

def _ev(c,bid_no,kind,ref,verified,summary="",source_uri="",details=None):
    raw=json.dumps(details or {},sort_keys=True,ensure_ascii=False,default=str)
    digest=sha256(raw.encode()).hexdigest()
    c.execute("""INSERT INTO procureflow.g2b_case_evidence(
           bid_no,evidence_type,reference,state,source_url,content_sha,summary,
           structured,verified_source)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s)
           ON CONFLICT(bid_no,evidence_type,reference) DO UPDATE SET
              state=excluded.state,source_url=excluded.source_url,
              content_sha=excluded.content_sha,summary=excluded.summary,
              structured=excluded.structured,
              verified_source=excluded.verified_source,recorded_at=now()
        """,(bid_no,kind,ref,"verified" if verified else "observed",
              source_uri,digest,summary,raw,verified))

def refresh_existing_evidence(bid_no=SINGLE_CASE):
    """Import real existing DB records; never count unsearched months as zero bids."""
    ensure_engine()
    if bid_no!=SINGLE_CASE:raise ValueError("one selected tender only")
    h=history_status(1000)
    with session() as c:
        exists=c.execute("""SELECT source,external_id,title,raw,deadline,agency,category
             FROM procureflow.tenders WHERE source='g2b' AND external_id=%s""",
             (bid_no,)).fetchone()
        if exists and isinstance(exists["raw"],dict):
            official=exists["raw"].get("bidNtceNo")==bid_no
            _ev(c,bid_no,"notice_official","official_bid_notice",official,
                "공식 G2B 입찰공고 원본" if official else "비검증 발주요청",
                "https://www.g2b.go.kr/",dict(exists))
        if exists and isinstance(exists["raw"],dict) and exists["raw"].get("bidNtceNo")==bid_no:
            if exists.get("agency"):
                _ev(c,bid_no,"agency","official_agency",True,
                    exists["agency"],"https://apis.data.go.kr/",
                    {"agency":exists["agency"],
                     "agency_code":exists["raw"].get("ntceInsttCd")})
            if exists.get("deadline"):
                _ev(c,bid_no,"deadline","official_deadline",True,
                    exists["deadline"],"https://apis.data.go.kr/",
                    {"deadline":exists["deadline"]})
            budget=next((exists["raw"].get(k) for k in (
                "asignBdgtAmt","bdgtAmt","presmptPrce")
                if exists["raw"].get(k)),None)
            if budget is not None:
                _ev(c,bid_no,"budget_observed","official_budget",True,
                    "공식 공고 금액", "https://apis.data.go.kr/",
                    {"field":"first_available_original_budget_field","amount":budget})
            if exists["raw"].get("scsbidLwltRate"):
                _ev(c,bid_no,"price_rules_observed","original_bid_rate",True,
                    "낙찰하한율 원본", "https://apis.data.go.kr/",
                    {"raw_rate":exists["raw"]["scsbidLwltRate"]})
            for field,ev_kind in (("ntceInsttCd","agency_code"),
                                  ("bidQlfctRgstDt","qualification_deadline"),
                                  ("cntrctCnclsMthdNm","contract_terms"),
                                  ("bidMethdNm","bid_method")):
                if exists["raw"].get(field):
                    _ev(c,bid_no,ev_kind,field,True,
                        str(exists["raw"][field]),"https://apis.data.go.kr/",
                        {"field":field,"value":exists["raw"][field]})
        cats=c.execute("""SELECT code_type,code,evidence_level,source_uri
                    FROM procureflow.g2b_notice_categories
                    WHERE bid_no=%s AND bid_ord='000'""",(bid_no,)).fetchall()
        official_cats=[x for x in cats if x["evidence_level"]=="official_direct"]
        if official_cats:
            _ev(c,bid_no,"classification_verified","official_codes",True,
                "공식 세부 분류코드","https://apis.data.go.kr/",
                {"codes":[dict(x) for x in official_cats]})
        index=c.execute("""SELECT count(*) n FROM
               procureflow.g2b_notice_source_files
               WHERE bid_no=%s AND bid_ord='000'""",(bid_no,)).fetchone()["n"]
        files=c.execute("""SELECT extraction_state,url,sha256,filename,
                       file_id,size_bytes,source_verified,
                       octet_length(data) AS stored_bytes,
                       length(extracted_text) AS text_chars
               FROM procureflow.g2b_case_documents
               WHERE bid_no=%s AND bid_ord='000'""",
               (bid_no,)).fetchall()
        if index>0:
            _ev(c,bid_no,"attachment_index","official_links",True,
                str(index)+"개 첨부 후보 목록","https://apis.data.go.kr/",
                {"listed":index})
        c.execute("""DELETE FROM procureflow.g2b_case_evidence
               WHERE bid_no=%s AND
               ((evidence_type='attachments_complete' AND reference='all_original_files')
               OR (evidence_type='attachment_text' AND reference='all_docs_parsed'))""",
                  (bid_no,))
        index_rows=c.execute("""SELECT file_id FROM procureflow.g2b_notice_source_files
               WHERE bid_no=%s AND bid_ord='000'""",(bid_no,)).fetchall()
        listed_ids={x["file_id"] for x in index_rows}
        complete=(index>0 and len(files)==index
             and {x["file_id"] for x in files}==listed_ids
             and all(x["source_verified"] and x["sha256"]
                 and len(x["sha256"])==64 and (x["size_bytes"] or 0)>0
                 and x["stored_bytes"]==x["size_bytes"] for x in files))
        if complete:
            _ev(c,bid_no,"attachments_complete","all_original_files",True,
                str(index)+"개 공식 파일 원본 해시·바이트 확인",
                "https://www.g2b.go.kr/",
                {"files":[{"id":x["file_id"],"sha256":x["sha256"],
                           "bytes":x["stored_bytes"]} for x in files]})
            if all(x["extraction_state"]=="parsed" and (x["text_chars"] or 0)>0
                   for x in files):
                _ev(c,bid_no,"attachment_text","all_docs_parsed",True,
                    "첨부 문서 내용 추출 완료","https://www.g2b.go.kr/",
                    {"files":[x["filename"] for x in files]})
        for row in h["history"]:
            _ev(c,bid_no,"historical_notice",row["hist_notice_no"],
                row["evidence"]=="official_openapi_explicit_code",
                row["title"],row["source_url"],dict(row))
        windows=c.execute("""SELECT status,count(*) n
              FROM procureflow.g2b_case_10yr_windows
              WHERE case_bid_no=%s GROUP BY status""",(bid_no,)).fetchall()
        complete=sum(x["n"] for x in windows if x["status"]=="completed")
        if complete==121:
            _ev(c,bid_no,"history_10years_complete","121_months",True,
                "121/121 official monthly windows completed",
                "https://apis.data.go.kr/",{"monthly_coverage":121})
        else:
            _ev(c,bid_no,"history_10years_progress","121_months",False,
                str(complete)+"/121월 원본 검증 완료",details={"completed":complete,
                    "total":121,"states":windows})
        # Drop incorrect 8-digit-based opening evidence created by the old
        # notice-list-to-bid join. No classification from headline/parent8.
        c.execute("""DELETE FROM procureflow.g2b_case_evidence
          WHERE bid_no=%s AND (
           (evidence_type='opening_evidence' AND reference='linked_opening_database')
           OR (evidence_type='historical_bidders_linked' AND reference='existing_opening_db')
           OR (evidence_type='award_evidence' AND reference='existing_award_db'))
        """,(bid_no,))
        from g2b_exact_outcome_history import ensure_schema as exact_result_schema
        exact_result_schema()
        associated=c.execute("""SELECT r.bid_ntce_no AS bid_no,
           count(*) FILTER(WHERE r.result_kind='opening' AND r.company<>'') AS bidder_rows,
           count(*) FILTER(WHERE r.result_kind='award') AS award_rows
           FROM procureflow.bid_results r
           JOIN procureflow.g2b_case_outcome_verification v
             ON v.bid_no=r.bid_ntce_no AND v.bid_ord=r.bid_ntce_ord
              AND v.case_bid_no=%s AND v.status='verified_exact_10'
           JOIN procureflow.g2b_notice_categories cat
             ON cat.bid_no=v.bid_no AND cat.bid_ord=v.bid_ord
               AND cat.code_type='detail10' AND cat.code='8111159901'
               AND cat.evidence_level='official_direct'
           JOIN procureflow.g2b_case_10yr_history h
             ON h.case_bid_no=v.case_bid_no
              AND h.hist_notice_no=v.bid_no AND h.hist_notice_ord=v.bid_ord
           WHERE r.source='g2b' AND r.result_kind IN('opening','award')
             AND h.published_on BETWEEN %s AND %s
             AND r.bid_ntce_no<>%s
           GROUP BY r.bid_ntce_no""",(bid_no,BEGIN,END,bid_no)).fetchall()
        count_bidder=sum(x["bidder_rows"] for x in associated)
        count_award=sum(x["award_rows"] for x in associated)
        if count_bidder>0:
            _ev(c,bid_no,"opening_evidence","linked_opening_database",True,
                "10자리 세부품명 확인 후 실제 개찰 투찰기록 "+str(count_bidder)+"행",
                details={"matched":associated,"bidder_rows":count_bidder,
                         "detail10":"8111159901"})
            _ev(c,bid_no,"historical_bidders_linked","existing_opening_db",True,
                "10자리 세부품명 일치 과거 투찰업체 "+str(count_bidder)+"행",
                details={"matched_notices":associated,"rows":count_bidder,
                         "detail10":"8111159901"})
        if count_award>0:
            _ev(c,bid_no,"award_evidence","existing_award_db",True,
                "10자리 세부품명 검증 후 확정 낙찰 "+str(count_award)+"행",
                details={"award_rows":count_award,"detail10":"8111159901"})
    return {"case":bid_no,"notice_candidates_not_outcomes":h["historical_notices_stored"],
            "exact_detail_product_code":"8111159901",
            "verified_windows":complete,"total_windows":121,
            "linked_bidder_rows":count_bidder,"linked_award_rows":count_award,
            "official_current_notice":bool(exists and isinstance(exists["raw"],dict)
                                           and exists["raw"].get("bidNtceNo")==bid_no)}

# Accepted record types are purposefully narrow. A workflow flag cannot turn an
# unreviewed price/attachment/qualification into verified evidence.
MATERIAL_TYPES=frozenset({
    "classification_verified","agency","deadline","detail_original",
    "attachment_index","attachments_complete","attachment_text","requirements",
    "opening_evidence","company_registration","qualification_evaluation",
    "eligibility_documents","supplier_quotes","verified_base_amount",
    "cost_breakdown","price_rules","proposal_draft","final_package",
    "final_validation","contract_terms","industry_codes","region_codes",
    "staffing_plan","past_performance","supplier_evidence","price_scenarios",
    "company_registry","award_method","required_forms","final_review"
})

def add_evidence(bid_no,kind,reference,source_url,structured,source_verified=False):
    if bid_no!=SINGLE_CASE:raise ValueError("only selected tender")
    if kind not in MATERIAL_TYPES:raise ValueError("unsupported evidence type")
    if not isinstance(structured,dict):raise ValueError("structured evidence must be object")
    if not reference or len(reference)>150:raise ValueError("valid reference required")
    if len(json.dumps(structured,ensure_ascii=False))>600000:
        raise ValueError("evidence exceeds maximum size")
    url=source_url or ""
    # Recording user-supplied evidence is not an independent official check.
    if source_verified and not (
        url.startswith("https://www.g2b.go.kr/") or
        url.startswith("https://apis.data.go.kr/")):
        raise ValueError("verified official evidence needs official source")
    ensure_engine()
    with session() as c:
        _ev(c,bid_no,kind,reference,bool(source_verified),kind,url,structured)
        c.execute("""INSERT INTO procureflow.g2b_case_events(bid_no,action,details)
              VALUES (%s,'evidence_added',%s::jsonb)""",
              (bid_no,json.dumps({"kind":kind,"reference":reference,
                                  "verified":bool(source_verified)})))
    return {"stored":True,"verified":bool(source_verified),"kind":kind}

def put_decision(bid_no,kind,key,value):
    if bid_no!=SINGLE_CASE:raise ValueError("only selected tender")
    if kind not in ("company","eligibility","supplier","quote",
                    "staffing","cost","bid_price","proposal","approval"):
        raise ValueError("unrecognized decision kind")
    if not isinstance(value,dict):raise ValueError("value must be an object")
    if not key or len(key)>100:raise ValueError("invalid key")
    ensure_engine()
    with session() as db:
        db.execute("""INSERT INTO procureflow.g2b_case_decisions
           (bid_no,kind,key,value) VALUES (%s,%s,%s,%s::jsonb)
           ON CONFLICT(bid_no,kind,key) DO UPDATE SET
             value=excluded.value,origin='local',state='draft',updated_at=now()
        """,(bid_no,kind,key,json.dumps(value,ensure_ascii=False)))
    return {"stored":True,"state":"draft","kind":kind}

def _ready(evidence):
    verified={x["evidence_type"] for x in evidence
              if x["verified_source"] and x["state"]=="verified"}
    by_group={}
    for key,reqs in REQUIREMENTS.items():
        lacking=[x for x in reqs if x not in verified]
        by_group[key]={"verified":not lacking,"missing":lacking,
                       "confirmed_evidence":list(sorted(set(reqs)-set(lacking)))}
    return verified,by_group

def _display_feature_state(f,group_state,evidence):
    kind=f["group"]
    n=f["number"]
    actual={x["evidence_type"] for x in evidence}
    verified={x["evidence_type"] for x in evidence if x["verified_source"]}
    needed=set(FEATURE_GATES[n])
    if needed and needed<=verified:return "verified"
    # A test/UI/collector skeleton never equals business acceptance.
    if kind=="history" and n in (33,34,35,38,39,41,42,43,44,45,47):
        return "partial" if "historical_notice" in actual else "missing"
    if kind=="operations" and n in (95,96,97,98) and "history_10years_progress" in actual:
        return "partial"
    return "missing"

def dashboard(bid_no=SINGLE_CASE,event_limit=25):
    if bid_no!=SINGLE_CASE:raise ValueError("only selected tender")
    material=refresh_existing_evidence(bid_no)
    with session() as db:
        row=db.execute("""SELECT * FROM procureflow.g2b_case_control
             WHERE bid_no=%s""",(bid_no,)).fetchone()
        evidence=db.execute("""SELECT evidence_type,reference,state,
            source_url,content_sha,summary,verified_source,recorded_at
            FROM procureflow.g2b_case_evidence
            WHERE bid_no=%s ORDER BY recorded_at DESC LIMIT 400""",(bid_no,)).fetchall()
        decisions=db.execute("""SELECT kind,key,value,state,origin,updated_at
            FROM procureflow.g2b_case_decisions WHERE bid_no=%s
            ORDER BY kind,key""",(bid_no,)).fetchall()
        recent=db.execute("""SELECT id,phase,state,result,error,created_at,finished_at
            FROM procureflow.g2b_case_runs WHERE bid_no=%s
            ORDER BY id DESC LIMIT 20""",(bid_no,)).fetchall()
        events=db.execute("""SELECT id,action,details,created_at
            FROM procureflow.g2b_case_events WHERE bid_no=%s
            ORDER BY id DESC LIMIT %s""",(bid_no,max(1,min(100,int(event_limit))))).fetchall()
    confirmed,groups=_ready(evidence)
    features=[{**f,"acceptance_state":_display_feature_state(f,groups,evidence)}
              for f in FEATURES]
    stages=[{"key":key,"title":key,"start":GROUP_RANGES[key][0],
             "end":GROUP_RANGES[key][1],"ready":groups[key]["verified"],
             "missing_evidence":groups[key]["missing"]}
             for key,_ in GROUPS]
    all_final=all(f["acceptance_state"]=="verified" for f in features)
    return {"case":dict(row),"source":"live_procureflow_postgresql",
            "overview":material,"catalog_size":len(FEATURES),
            "feature_acceptance":features,"phases":stages,
            "verified_evidence_types":sorted(confirmed),
            "all_104_verified":all_final,
            "ready_for_manual_bid_participation":all_final and row["state"]=="ready_for_manual_participation",
            "bid_participation_clicked":False,"submitted":False,
            "evidence":evidence,"decisions":decisions,
            "runs":recent,"events":events}

GROUP_RANGES={"notice":(1,16),"detail":(17,32),
              "history":(33,48),"matching":(49,60),
              "eligibility":(61,76),"pricing":(77,94),"operations":(95,104)}

def readiness_check(bid_no=SINGLE_CASE):
    r=dashboard(bid_no,0)
    return {"bid_no":bid_no,"status":"ready" if r["ready_for_manual_bid_participation"]
             else "not_ready","phases":r["phases"],
            "submitted":False,"must_not_click_bid_participation":True}

def cost_summary(bid_no=SINGLE_CASE):
    """Calculation from supplied actual numerical quote evidence only."""
    if bid_no!=SINGLE_CASE:raise ValueError("only selected tender")
    with session() as con:
        rows=con.execute("""SELECT kind,key,value FROM procureflow.g2b_case_decisions
             WHERE bid_no=%s AND kind IN ('cost','quote')""",(bid_no,)).fetchall()
    cost_rows=[];incomplete=[]
    for row in rows:
        v=row["value"];raw=v.get("total_krw")
        try:
            if raw is None:raise InvalidOperation()
            amount=Decimal(str(raw))
            if not amount.is_finite() or amount<0:raise InvalidOperation()
        except (InvalidOperation,ValueError):
            incomplete.append({"kind":row["kind"],"key":row["key"]})
            continue
        cost_rows.append({"kind":row["kind"],"key":row["key"],"total_krw":str(amount)})
    total=sum((Decimal(x["total_krw"]) for x in cost_rows),Decimal(0))
    return {"bid_no":bid_no,"documented_cost_rows":cost_rows,
            "documented_sum_krw":str(total),
            "incomplete_rows":incomplete,
            "approved_bid_amount":None,
            "ready":False,"reason":"Verified budget, bid law, company eligibility, quotation originals and written approval all required."}
