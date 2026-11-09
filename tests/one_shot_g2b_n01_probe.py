"""One-time public N01 factual verification, NO DB, NO Worker or bid.

This file is the only automatic trigger for the dedicated one-shot CI. It
accesses public official NURI and G2B files only, then exits immediately.
"""
import json
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"n8n/unified"))
import live_nine_test as g2b

def main():
    client=g2b._client()
    g2b._once(client)
    original_cache={}
    result=g2b._live_notice(client,original_cache)
    if result.get("bid_no")!=g2b.CASE:
        raise AssertionError("OFFICIAL_TENDER_NUMBER_MISMATCH")
    if result.get("official_fields_verified") is not True:
        raise AssertionError("N01_FALSE_SUCCESS_NO_FIELD_EVIDENCE")
    title=result.get("title")
    agency=result.get("agency")
    if not isinstance(title,str) or not title.strip():
        raise AssertionError("N01_TITLE_NULL_OR_EMPTY")
    if not isinstance(agency,str) or not agency.strip():
        raise AssertionError("N01_AGENCY_NULL_OR_EMPTY")
    if not all(g2b.re.sub(r"\s+","",token) in g2b.re.sub(r"\s+","",title)
               for token in g2b.TEST_TITLE_TOKENS):
        raise AssertionError("N01_OFFICIAL_TITLE_CONTENT_MISMATCH")
    if "전남테크노파크" not in g2b.re.sub(r"\s+","",agency):
        raise AssertionError("N01_OFFICIAL_AGENCY_CONTENT_MISMATCH")
    safe={key:result.get(key) for key in
          ("bid_no","bid_ord","title","agency","budget",
           "source","verified_by","official_fields_verified",
           "source_file_bytes","source_file_sha256","notice_list",
           "notice_list_error","extracted_from","source_text_sha256")}
    print("N01_LIVE_ORIGINAL_EVIDENCE",json.dumps(safe,ensure_ascii=False),flush=True)
    print("N01_REAL_ORIGINAL_METADATA_VERIFIED",flush=True)

if __name__=="__main__":
    main()
