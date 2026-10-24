"""Parser for clearly labeled 10-digit G2B detail category codes on public notice pages.
Classification evidence source is preserved separately from official records.
"""
import re
from html.parser import HTMLParser

class TextParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts=[]
    def handle_data(self,data):
        self.parts.append(data)

def parse_category_labels(html, bid_no):
    p=TextParser()
    p.feed(html)
    text=" ".join(p.parts)
    if bid_no not in text:
        return []
    matches=re.findall(r"분류\s*(?:\|\s*)?[^()]{1,65}\((\d{10})\)",text)
    return sorted(set(matches))


def enrich_saved_bid_notices(limit=12):
    """Fetch a small bounded set of public G2B notice summaries with provenance."""
    import json
    import logging
    import time
    from playwright.sync_api import sync_playwright
    from db import session
    from g2b_categories import upsert_verified_codes
    limit=max(1,min(30,int(limit)))
    with session() as con:
        rows=con.execute("""SELECT DISTINCT ON (r.bid_ntce_no,r.bid_ntce_ord)
                 r.bid_ntce_no,r.bid_ntce_ord,r.title,r.category
              FROM procureflow.bid_results r
              LEFT JOIN procureflow.g2b_notice_categories c
                ON c.bid_no=r.bid_ntce_no AND c.bid_ord=r.bid_ntce_ord
                AND c.code_type='detail10'
              WHERE r.source='g2b' AND r.result_kind IN ('opening_status','award')
                AND r.bid_ntce_no ~ '^R[0-9]{2}BK[0-9]{8}$'
                AND c.bid_no IS NULL
              ORDER BY r.bid_ntce_no,r.bid_ntce_ord,r.title DESC
              LIMIT %s""",(limit,)).fetchall()
    result={"attempted":0,"enriched":0,"codes":0,"sources":[],
            "statuses":{},"errors":[],"official_direct":False}
    with sync_playwright() as pw:
        ctx=pw.request.new_context(
            user_agent="Mozilla/5.0 (compatible; ProcureFlowCategoryLookup/1.0)",
            extra_http_headers={"Accept":"text/html"},timeout=12000)
        try:
            for row in rows:
                bid_no=row["bid_ntce_no"]
                url="https://bid24.kr/b/"+bid_no
                status="missing"
                result["attempted"]+=1
                try:
                    response=ctx.get(url)
                    if response.status==200:
                        codes=parse_category_labels(response.text(),bid_no)
                        if codes:
                            data={"items":[{"dtilPrdctClsfcNo":code}
                                           for code in codes]}
                            category=row["category"]
                            if category not in ("goods","service"):category=""
                            saved=upsert_verified_codes(bid_no,row["bid_ntce_ord"],
                                category,data,url,evidence_level="secondary_public")
                            result["codes"]+=len(saved)
                            result["enriched"]+=int(bool(saved))
                            status="category_saved"
                            if len(result["sources"])<15:
                                result["sources"].append({"bid_no":bid_no,
                                      "codes":codes,"url":url})
                        else:status="no_code"
                    else:status="http_"+str(response.status)
                except Exception as exc:
                    status="error"
                    if len(result["errors"])<12:
                        result["errors"].append(bid_no+":"+type(exc).__name__+":"+str(exc)[:120])
                result["statuses"][status]=result["statuses"].get(status,0)+1
                logging.info("G2B_MIRRORED_CATEGORY bid=%s status=%s",bid_no,status)
                time.sleep(.5)
        finally:ctx.dispose()
    result["status"]="collected" if result["enriched"] else (
                     "partial" if result["attempted"] else "empty")
    return result
