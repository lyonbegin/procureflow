"""Single-case, exact 8-digit G2B category history, 2016-10-24 to 2026-10-24.

The chosen tender is R26BK01787028/000, category 81111599.
No LLM, title similarity, other tender selection or bidder predictions.
Only verified codes from source content and publication dates in horizon are stored.
"""
from __future__ import annotations
import calendar
import os
import re
from datetime import date
from html.parser import HTMLParser
from urllib.parse import urlparse
from db import session

CASE_BID="R26BK01787028"
CASE_ORD="000"
CAT8="81111599"
SUB10="8111159901"
BEGIN=date(2016,10,24)
END=date(2026,10,24)
KNOWN_URLS=(
 "https://sujubut.com/bid/domestic/2903402/", # 2020
 "https://sujubut.com/bid/domestic/2344204/", # 2021
 "https://sujubut.com/bid/domestic/2530913/", # 2021
 "https://sujubut.com/bid/domestic/2095935/", # 2022
 "https://sujubut.com/bid/domestic/1355173/", # 2023
 "https://sujubut.com/bid/domestic/1352562/", # 2023
 "https://sujubut.com/bid/domestic/972286/",  # 2024
 "https://bid24.kr/b/R26BK01705258",          # 2026
 "https://bid24.kr/b/R26BK01716629",          # 2026
 "https://bid24.kr/b/R26BK01730736",          # 2026
 "https://bid24.kr/b/R26BK01743916",          # 2026
 "https://bid24.kr/b/R26BK01762537",          # 2026
 "https://bid24.kr/b/R26BK01759439",          # 2026
)
NO_RE=re.compile(r"^(R\d{2}BK\d{8}|\d{11})$")
PUB_DATE_RE=re.compile(r"(20\d{2})[-./](\d{2})[-./](\d{2})")
CLASS_RE=re.compile(r"정보시스템개발서비스\s*\(?\s*81111599\s*\)?")
DIGITS8_RE=re.compile(r"(?:^|\D)81111599(?:\D|$)")

class PlainText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.text=[]
        self.h1=[]
        self.level=0
    def handle_starttag(self,tag,attrs):
        if tag=="h1":self.level+=1
    def handle_endtag(self,tag):
        if tag=="h1":self.level=max(0,self.level-1)
    def handle_data(self,data):
        s=" ".join(data.split())
        if s:
            self.text.append(s)
            if self.level:self.h1.append(s)

def parse_8digit_notice(html,origin):
    """Extract only explicit code in page notice detail, not title similarity."""
    p=PlainText();p.feed(html or "")
    title=" ".join(p.h1)
    raw=" ".join(p.text)
    if not CLASS_RE.search(raw):
        return None, "no_explicit_81111599"
    if "bid24.kr" in origin:
        n=re.search(r"공고번호\s*\|\s*(R\d{2}BK\d{8})",raw)
        d=re.search(r"공고일시\s*\|\s*(\d{1,2})월\s*(\d{1,2})일",raw)
        if not n:return None,"missing_bid_no"
        year=int(n.group(1)[1:3])+2000
        if not d:return None,"missing_pubdate"
        published=date(year,int(d.group(1)),int(d.group(2)))
        agency=""
        budget=None
    elif "sujubut.com" in origin:
        n=re.search(r"공고번호\s+(\d{11})\s*\(차수\s+(\d{3})\)",raw)
        d=re.search(r"게시일\s+(20\d{2}-\d{2}-\d{2})",raw)
        if not n:return None,"missing_legacy_no"
        if not d:return None,"missing_pubdate"
        published=date.fromisoformat(d.group(1))
        agency_match=re.search(r"수요기관\s+(.{3,90}?)\s+(?:사전규격|통합공고|첨부 파일)",raw)
        agency=agency_match.group(1)[:100] if agency_match else ""
        budget_match=re.search(r"사업금액\s+([\d,]+)원",raw)
        budget=int(budget_match.group(1).replace(",","")) if budget_match else None
    else:return None,"unrecognized_host"
    no=n.group(1)
    if not NO_RE.fullmatch(no):return None,"invalid_bid_no"
    if not BEGIN<=published<=END:return None,"outside_10year_window"
    if no==CASE_BID:return None,"target_not_historical"
    if not title:return None,"missing_title"
    return {"notice_no":no,
            "notice_ord":n.group(2) if "sujubut.com" in origin else "000",
            "published_on":published.isoformat(),"title":title[:350],
            "agency":agency,"amount":budget,"classification":"81111599",
            "source_url":origin,"evidence":"secondary_public_extracted"},None

def ensure_schema():
    with session() as con:
        con.execute("""CREATE TABLE IF NOT EXISTS procureflow.g2b_case_10yr_history(
              case_bid_no text NOT NULL,
              hist_notice_no text NOT NULL,
              hist_notice_ord text NOT NULL,
              classification8 text NOT NULL,
              published_on date NOT NULL,
              title text NOT NULL,
              agency text NOT NULL DEFAULT '',
              amount numeric,
              source_url text NOT NULL,
              evidence text NOT NULL,
              collected_at timestamptz NOT NULL DEFAULT now(),
              PRIMARY KEY(case_bid_no,hist_notice_no,hist_notice_ord)
        )""")
        con.execute("""CREATE INDEX IF NOT EXISTS ix_pf_10yr_case_date
          ON procureflow.g2b_case_10yr_history(case_bid_no,published_on DESC)""")
        con.execute("""CREATE TABLE IF NOT EXISTS procureflow.g2b_case_10yr_windows(
           case_bid_no text NOT NULL,
           first_day date NOT NULL,
           last_day date NOT NULL,
           status text NOT NULL DEFAULT 'unsearched',
           source text NOT NULL DEFAULT '',
           matched int NOT NULL DEFAULT 0,
           checked int NOT NULL DEFAULT 0,
           page_cursor int NOT NULL DEFAULT 1,
           last_error text NOT NULL DEFAULT '',
           updated_at timestamptz NOT NULL DEFAULT now(),
           PRIMARY KEY(case_bid_no,first_day)
        )""")
        for year in range(2016,2027):
            for month in range(1,13):
                if (year,month)<(2016,10) or (year,month)>(2026,10):continue
                first=date(year,month,1)
                last=date(year,month,calendar.monthrange(year,month)[1])
                first=max(first,BEGIN);last=min(last,END)
                con.execute("""INSERT INTO procureflow.g2b_case_10yr_windows(
                     case_bid_no,first_day,last_day) VALUES (%s,%s,%s)
                     ON CONFLICT DO NOTHING""",(CASE_BID,first,last))

def ingest_known_secondary(limit=13):
    """Bounded direct evidence extraction for older and newer published public notices."""
    from playwright.sync_api import sync_playwright
    from g2b_categories import ensure_schema as ensure_category_schema
    ensure_category_schema()
    ensure_schema()
    out={"target":CASE_BID,"classification":CAT8,"horizon":[str(BEGIN),str(END)],
         "attempted":0,"saved":0,"examples":[],"errors":[]}
    with sync_playwright() as pw:
        request=pw.request.new_context(timeout=14000)
        try:
            for uri in KNOWN_URLS[:max(1,min(13,int(limit)))]:
                out["attempted"]+=1
                try:
                    resp=request.get(uri)
                    if resp.status!=200:
                        out["errors"].append({"url":uri,"status":resp.status})
                        continue
                    row,err=parse_8digit_notice(resp.text(),uri)
                    if not row:
                        out["errors"].append({"url":uri,"reason":err})
                        continue
                    with session() as con:
                        con.execute("""INSERT INTO procureflow.g2b_case_10yr_history(
                           case_bid_no,hist_notice_no,hist_notice_ord,classification8,
                           published_on,title,agency,amount,source_url,evidence)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                           ON CONFLICT(case_bid_no,hist_notice_no,hist_notice_ord)
                           DO UPDATE SET published_on=excluded.published_on,
                           title=excluded.title,agency=excluded.agency,
                           amount=excluded.amount,source_url=excluded.source_url,
                           evidence=excluded.evidence,collected_at=now()
                        """,(CASE_BID,row["notice_no"],row["notice_ord"],CAT8,
                             row["published_on"],row["title"],row["agency"],
                             row["amount"],uri,row["evidence"]))
                    out["saved"]+=1
                    if len(out["examples"])<13:out["examples"].append(row)
                except Exception as exc:
                    out["errors"].append({"url":uri,
                         "reason":type(exc).__name__+":"+str(exc)[:120]})
        finally:request.dispose()
    return out

def status(limit=100):
    ensure_schema()
    with session() as con:
        all_years=con.execute("""SELECT extract(year from published_on)::int AS year,
                 count(*) AS n FROM procureflow.g2b_case_10yr_history
                 WHERE case_bid_no=%s AND classification8=%s
                 AND published_on BETWEEN %s AND %s
                 GROUP BY 1 ORDER BY year
             """,(CASE_BID,CAT8,BEGIN,END)).fetchall()
        windows=con.execute("""SELECT status,count(*) AS windows
              FROM procureflow.g2b_case_10yr_windows WHERE case_bid_no=%s
              GROUP BY status ORDER BY status""",(CASE_BID,)).fetchall()
        rows=con.execute("""SELECT hist_notice_no,hist_notice_ord,published_on,
                    title,agency,amount,source_url,evidence
               FROM procureflow.g2b_case_10yr_history
               WHERE case_bid_no=%s AND classification8=%s
                 AND published_on BETWEEN %s AND %s
               ORDER BY published_on DESC,hist_notice_no DESC LIMIT %s
             """,(CASE_BID,CAT8,BEGIN,END,max(1,min(int(limit),1000)))).fetchall()
        total=con.execute("""SELECT count(*) AS n FROM procureflow.g2b_case_10yr_history
               WHERE case_bid_no=%s AND classification8=%s
               AND published_on BETWEEN %s AND %s
            """,(CASE_BID,CAT8,BEGIN,END)).fetchone()["n"]
    return {"target_notice":CASE_BID+"-"+CASE_ORD,
            "target_category":CAT8,"target_detail_category":SUB10,
            "search_begin":BEGIN.isoformat(),"search_end":END.isoformat(),
            "region_filter":None,"agency_filter":None,
            "historical_notices_stored":total,
            "yearly_count":all_years,"monthly_window_states":windows,
            "windows_total":121,
            "exhaustive_ten_year_search_complete":False,
            "qualification":"verified classification in indexed secondary pages; not full G2B universe",
            "history":rows,"llm_used":False,"title_similarity_used":False}
