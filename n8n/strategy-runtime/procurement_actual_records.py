"""Actual existing ProcureFlow G2B source records for one selected notice.

GET-only, no crawler, no writes, no secrets, no n8n access, no bid submission.
Fetches the REAL stored opening bidder rows, official source attachment hashes,
actual 10-year evidence coverage and price blockers from existing FastAPI.
Never upgrades preliminary opening rank into confirmed award.
"""
from __future__ import annotations
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.parse import quote
import json, re

API="https://procureflow-api-production.up.railway.app"
CASE="R26BK01787028"
MAX_BYTES=1_400_000
class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("ORIGINAL_RECORDS_REDIRECT_FORBIDDEN")

PATHS={
 "outcomes":"/api/g2b/full/exact-outcomes",
 "documents":"/api/g2b/full/documents",
 "schedule":"/api/g2b/full/schedule",
 "price":"/api/g2b/full/price",
 "context":"/api/g2b/cases/"+CASE+"/context",
}
def _get(key,*,opener=None):
    if key not in PATHS:raise ValueError("UNREGISTERED_PUBLIC_DATA_PATH")
    link=API+PATHS[key]
    transport=opener or build_opener(NoRedirect())
    with transport.open(Request(link,method="GET",headers={
        "Accept":"application/json","User-Agent":"ProcureFlow-Actual-G2B-Records/1.0"}),timeout=12) as response:
        if response.status!=200 or "application/json" not in (response.headers.get("content-type") or ""):
            raise ValueError("UPSTREAM_RESPONSE_INVALID")
        raw=response.read(MAX_BYTES+1)
        if len(raw)>MAX_BYTES:raise ValueError("UPSTREAM_TOO_LARGE")
        data=json.loads(raw)
    if not isinstance(data,dict):raise ValueError("UPSTREAM_NOT_OBJECT")
    return data

def read_actual(*,fetcher=None):
    get=fetcher or _get
    outcome=get("outcomes")
    docs=get("documents")
    schedule=get("schedule")
    price=get("price")
    context=get("context")
    if outcome.get("target_bid_no")!=CASE or docs.get("bid_no")!=CASE or context.get("bid_no")!=CASE:
        raise ValueError("CROSS_TENDER_SOURCE_REJECTED")
    if str(context.get("bid_ord"))!="000":raise ValueError("TENDER_ORD_MISMATCH")
    if outcome.get("exact_detail_product_code")!="8111159901":raise ValueError("DETAIL10_WRONG")
    counts=outcome.get("verified_exact_code_history_and_result_counts")
    if not isinstance(counts,dict):raise ValueError("NO_REAL_OUTCOME_COUNTS")
    for name in ("verified_notice_rounds","opening_bidder_rows","opening_amount_rows","confirmed_award_rows"):
        if type(counts.get(name)) is not int or counts[name]<0:raise ValueError("INVALID_REAL_COUNT")
    if type(outcome.get("candidate_notice_count_not_results")) is not int:
        raise ValueError("NO_CANDIDATE_COUNT")
    raw=outcome.get("actual_opening_and_award_rows",[])
    if not isinstance(raw,list):raise ValueError("INVALID_REAL_RECORD_LIST")
    rows=[]
    for x in raw[:140]:
        if not isinstance(x,dict):continue
        no=x.get("bid_ntce_no")
        if not isinstance(no,str) or not re.fullmatch(r"(R\d{2}BK\d{8}|\d{11})",no):continue
        kind=x.get("result_kind")
        if kind not in ("opening","award"):continue
        # This is an observed OPENING result, not an official certified award.
        rows.append({"bid_no":no,"bid_ord":str(x.get("bid_ntce_ord","000")),
            "company":str(x.get("company") or "")[:180],
            "amount":str(x.get("amount") or "")[:25],
            "rate":str(x.get("rate") or "")[:25],
            "rank":str(x.get("rank") or "")[:12],
            "kind":kind,"agency":str(x.get("agency") or "")[:180],
            "notice_date":str(x.get("historical_notice_date") or "")[:32],
            "original_evidence_url":str(x.get("detail_code_original_url") or "")[:600],
            "original_sha256":str(x.get("detail_code_original_sha256") or "")[:70],
            "result_status":str(x.get("result_status") or "")[:55]})
    files=docs.get("original_index",[])
    if not isinstance(files,list):raise ValueError("DOCUMENT_INDEX_INVALID")
    documents=[]
    for x in files[:20]:
        source_url=x.get("source_url")
        if not isinstance(source_url,str) or not source_url.startswith("https://www.g2b.go.kr/"):
            continue
        documents.append({"filename":str(x.get("file_label") or "")[:200],
          "source_url":source_url,"sha256":str(x.get("content_sha") or ""),
          "bytes":x.get("bytes_size"),"state":x.get("state")})
    return {"mode":"actual_existing_g2b_records","case_bid_no":CASE,"bid_ord":"000",
      "title":context.get("title"),"agency":context.get("agency"),
      "deadline":str(context.get("deadline") or ""),
      "method":context.get("method"),
      "official_notice_verified":context.get("original_notice_verified") is True,
      "official_detail10":context.get("official_detail10",[]),
      "configured_detail10":"8111159901",
      "historical_period":{"from":outcome.get("period_start"),"to":outcome.get("period_end")},
      "candidate_notices_not_results":outcome["candidate_notice_count_not_results"],
      "actual_counts":counts,
      "original_verification_states":outcome.get("verification_states",[]),
      "ten_year_coverage_complete":outcome.get("ten_year_coverage_completed") is True,
      "actual_opening_rows":rows,"displayed_rows":len(rows),
      "documents":documents,"documents_listed":docs.get("files_listed"),
      "documents_downloaded":docs.get("files_downloaded"),
      "official_api_key_present":schedule.get("official_api_key_present") is True,
      "price_status":price.get("status"),"price_missing":price.get("missing",[]),
      "price_eligibility":price.get("eligibility"),
      "real_recommended_price":price.get("recommended_bid_price"),
      "actual_job_executed_by_this_request":False,
      "new_collection_started":False,"bid_submitted":False,
      "warning":"Already collected real G2B opening records, NOT a completed 10-year corpus or final-award certification."}
