"""Read-only public mirror adapter for ONE selected G2B tender.

It obtains the real R26BK01787028 public metadata and extracts exact original
www.g2b.go.kr download URLs from the source HTML; it does not use title
similarity, fabricated documents, credentials, or click any submission action.
Secondary metadata is NEVER misrepresented as official source verification.
"""
from __future__ import annotations
from html.parser import HTMLParser
from urllib.parse import urljoin,urlparse,parse_qs
from datetime import datetime
from hashlib import sha256
import json,re
from playwright.sync_api import sync_playwright
from db import session
from g2b_case_engine import ensure_engine
from g2b_categories import upsert_verified_codes
from g2b_documents import ensure_documents
from g2b_official_notices import ensure_notice_schema

BID="R26BK01787028";ORD="000"
SOURCE="https://bid24.kr/b/"+BID
DIRECT="https://www.g2b.go.kr/link/PNPE027_01/single/?bidPbancNo="+BID+"&bidPbancOrd=000"
EXPECTED_FILES={
  "1":"1. 공고문.hwp",
  "2":"2. 과업지시서(스마트실증장비 모니터링시스템용 소프트웨어 개발).hwp",
  "3":"3. 공내역서.xlsx",
  "4":"1. 공고문.pdf"
}
class PublicPage(HTMLParser):
    def __init__(self):
        super().__init__();self.t=[];self.links=[];self.active=None
        self.capture_title=False;self.headings=[]
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if tag=="a":self.active={"href":a.get("href",""),"text":""}
        if tag=="h1":self.capture_title=True
    def handle_endtag(self,tag):
        if tag=="a" and self.active:
            self.links.append(self.active);self.active=None
        if tag=="h1":self.capture_title=False
        if tag in ("tr","td","th","p","div","li","h1","h2"):
            self.t.append("\n")
    def handle_data(self,data):
        x=" ".join(data.split())
        if x:
            self.t.append(x+" ")
            if self.active:self.active["text"]+=x
            if self.capture_title:self.headings.append(x)

def parse_selected_page(html):
    p=PublicPage();p.feed(html)
    title=" ".join(p.headings).strip()
    body=" ".join("".join(p.t).split())
    if BID not in body or "정보시스템개발서비스" not in body or "81111599" not in body:
        raise ValueError("target ID or source classification missing")
    if "철강·금속" not in title or "모니터링" not in title:
        raise ValueError("not the selected notice title")
    # Classification must appear in the page's explicit category label.
    cls=re.search(r"분류\s+.{0,100}?정보시스템개발서비스\s*\(81111599\)",body)
    if not cls:raise ValueError("missing explicit category and 8-digit code")
    links={}
    for a in p.links:
        href=urljoin(SOURCE,a["href"])
        u=urlparse(href)
        if (u.scheme!="https" or u.hostname!="www.g2b.go.kr" or
             u.path!="/pn/pnp/pnpe/UntyAtchFile/downloadFile.do"):
            continue
        params=parse_qs(u.query)
        if params.get("bidPbancNo")!=[BID] or params.get("bidPbancOrd")!=[ORD]:
            continue
        seq=params.get("fileSeq",[""])[0]
        if seq not in EXPECTED_FILES:continue
        if not a["text"].strip().lower().endswith(
            EXPECTED_FILES[seq].rsplit(".",1)[-1].lower()):
            continue
        links[seq]={"file_id":"official_attached_"+seq,
                    "file_label":a["text"].strip(),
                    "source_url":href}
    # public dates are displayed without year; infer only from exact R26BK ID
    # and independently verified expected 2026 announcement year.
    def clock(label):
        m=re.search(label+r"\s+(\d{1,2})월\s+(\d{1,2})일.{0,12}?(\d{1,2}):(\d{2})",body)
        if not m:return ""
        return f"2026-{int(m[1]):02d}-{int(m[2]):02d} {int(m[3]):02d}:{m[4]}"
    agency=""
    for string in ("재단법인전남테크노파크","(재)전남테크노파크"):
        if string in body:agency=string;break
    money=re.search(r"배정예산\s+([\d,]+)만원",body)
    return {"bid_no":BID,"ord":ORD,"title":title[:500],
            "agency":agency,"category8":"81111599",
            "posted":clock("공고일시"),
            "bid_begin":clock("입찰개시"),
            "bid_deadline":clock("입찰마감"),
            "budget_display":money.group(1)+"만원" if money else "",
            "file_index":list(links.values()),
            "file_count":len(links),"source":SOURCE,
            "secondary_mirror":True,"official_detail_url":DIRECT}

def ingest_selected_public():
    ensure_notice_schema();ensure_documents();ensure_engine()
    with sync_playwright() as pw:
        ctx=pw.request.new_context(timeout=18000)
        try:
            response=ctx.get(SOURCE)
            if response.status!=200:
                return {"status":"blocked","reason":"mirror_http_"+str(response.status)}
            data=parse_selected_page(response.text())
        finally:ctx.dispose()
    if not data["posted"] or not data["bid_deadline"]:
        return {"status":"blocked","reason":"dates_not_found","parsed":data}
    raw={"secondary_mirror":True,"secondary_source":SOURCE,
         "observed_bid_no":BID,"official_bid_no_unverified":True,
         "category8":"81111599","mirror_snapshot_sha256":
             sha256(json.dumps(data,ensure_ascii=False,sort_keys=True).encode()).hexdigest(),
         "deadline":data["bid_deadline"],"bid_begin":data["bid_begin"],
         "category_evidence":"public_mirror_explicit_classification",
         "claimed_budget_display":data["budget_display"]}
    with session() as c:
        c.execute("""INSERT INTO procureflow.tenders
         (source,external_id,title,agency,category,notice_date,deadline,
          status,method,source_url,raw)
         VALUES('g2b',%s,%s,%s,'일반용역',%s,%s,%s,%s,%s,%s::jsonb)
         ON CONFLICT(source,external_id) DO UPDATE SET
           title=CASE WHEN tenders.raw ? 'bidNtceNo' THEN tenders.title ELSE excluded.title END,
           agency=CASE WHEN tenders.raw ? 'bidNtceNo' THEN tenders.agency ELSE excluded.agency END,
           category=excluded.category,
           notice_date=CASE WHEN tenders.raw ? 'bidNtceNo' THEN tenders.notice_date ELSE excluded.notice_date END,
           deadline=CASE WHEN tenders.raw ? 'bidNtceNo' THEN tenders.deadline ELSE excluded.deadline END,
           source_url=CASE WHEN tenders.raw ? 'bidNtceNo' THEN tenders.source_url ELSE excluded.source_url END,
           raw=CASE WHEN tenders.raw ? 'bidNtceNo' THEN tenders.raw ELSE excluded.raw END,
           last_seen=now()""",(BID,data["title"],data["agency"],
                  data["posted"],data["bid_deadline"],"등록공고",
                  "소액수의견적",SOURCE,json.dumps(raw,ensure_ascii=False)))
        for file in data["file_index"]:
            c.execute("""INSERT INTO procureflow.g2b_notice_source_files
              (bid_no,bid_ord,file_id,source_url,file_label)
              VALUES (%s,%s,%s,%s,%s)
              ON CONFLICT(bid_no,bid_ord,file_id) DO UPDATE SET
              source_url=excluded.source_url,
              file_label=excluded.file_label,last_seen=now()""",
                (BID,ORD,file["file_id"],file["source_url"],file["file_label"]))
    upsert_verified_codes(BID,ORD,"service",{"prdctClsfcNo":"81111599"},
                          SOURCE,evidence_level="secondary_public")
    from g2b_case_engine import add_evidence
    add_evidence(BID,"requirements","public_bid_mirror_overview",
                 SOURCE,data,False)
    return {"status":"collected_secondary_public",
            "notice":BID,"files_indexed":data["file_count"],
            "category":"81111599","deadline":data["bid_deadline"],
            "original_files_downloaded":0,
            "official_classification_verified":False,
            "metadata":data}
