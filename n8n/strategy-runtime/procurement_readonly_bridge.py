"""Read-only projection of EXISTING ProcureFlow G2B FastAPI and PostgreSQL evidence.

No G2B crawling, writes, collector POST, n8n owner login, bidding or worker actions.
All upstream endpoints are hard-coded to /api/n8n/operational/flows/PFxx/inspect.
Never allow a browser-supplied host/path or trust a synthetic success as verified.
"""
from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.request import build_opener, Request, HTTPRedirectHandler
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
import json
import re

API="https://procureflow-api-production.up.railway.app"
CASE_BID="R26BK01787028"
CASE_ORD="000"
FLOW_IDS=tuple("PF"+str(i).zfill(2) for i in range(1,16))
SOURCE="live_procureflow_postgresql_verified_evidence"
MAX_BYTES=1_000_000

class StrictNoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("API_REDIRECT_FORBIDDEN")

def _fetch(flow_id, *, opener=None):
    if flow_id not in FLOW_IDS:
        raise ValueError("UNKNOWN_OPERATIONAL_FLOW")
    url=(API+"/api/n8n/operational/flows/"+flow_id+"/inspect?"
         +urlencode({"bid_no":CASE_BID}))
    op=opener or build_opener(StrictNoRedirect())
    with op.open(Request(url,headers={"Accept":"application/json","User-Agent":"ProcureFlow-Readonly-CaseEvidence/1.0"},method="GET"),
                 timeout=10) as response:
        if response.status!=200:raise ValueError("UPSTREAM_STATUS_"+str(response.status))
        if "application/json" not in (response.headers.get("content-type") or ""):
            raise ValueError("UPSTREAM_NOT_JSON")
        raw=response.read(MAX_BYTES+1)
        if len(raw)>MAX_BYTES:raise ValueError("UPSTREAM_RESPONSE_TOO_LARGE")
        result=json.loads(raw)
    if not isinstance(result,dict) or result.get("flow_id")!=flow_id or result.get("case_id")!=CASE_BID:
        raise ValueError("UPSTREAM_CASE_OR_FLOW_MISMATCH")
    if result.get("source_provenance")!=SOURCE or result.get("read_only") is not True:
        raise ValueError("UPSTREAM_SOURCE_NOT_ORIGINAL_VERIFIED_DB")
    if result.get("simulation_only") is not False or result.get("actual_job_executed") is not False:
        raise ValueError("UPSTREAM_IS_EXECUTING_WORK_NOT_INSPECTING")
    if result.get("automatic_bid_submission") is not False:raise ValueError("UPSTREAM_BID_SUBMISSION_NOT_DISABLED")
    if result.get("bid_ord")!=CASE_ORD:raise ValueError("UPSTREAM_BID_ORD_MISMATCH")
    if not isinstance(result.get("blocks"),list):raise ValueError("UPSTREAM_BLOCKS_MISSING")
    return result

def read_original_evidence(*,fetcher=None):
    """Read existing DB snapshots; never refresh or mark acceptance evidence."""
    get=fetcher or _fetch
    results={}
    # Each response uses the ORIGINAL 104 feature acceptance rules as returned
    # by n8n_operational._materialized() over g2b_case_engine.dashboard(refresh=False).
    with ThreadPoolExecutor(max_workers=5) as pool:
        future_to_flow={pool.submit(get,flow):flow for flow in FLOW_IDS}
        for future in as_completed(future_to_flow):
            flow=future_to_flow[future]
            results[flow]=future.result()
    features={}
    blocks={}
    official_details=set()
    notice_verified=False
    for flow in FLOW_IDS:
        obj=results[flow]
        notice_verified=notice_verified or bool(obj.get("official_notice_verified"))
        for code in obj.get("official_detail10") or []:
            if re.fullmatch(r"\d{10}",str(code)):official_details.add(str(code))
        for b in obj["blocks"]:
            block_id=b.get("id")
            if not isinstance(block_id,str) or not re.fullmatch(r"[NHSQPRO]\d{2}",block_id):
                raise ValueError("ORIGINAL_BLOCK_ID_INVALID")
            if block_id in blocks:raise ValueError("DUPLICATE_BUSINESS_BLOCK")
            steps=b.get("features")
            if not isinstance(steps,list) or not steps:raise ValueError("ORIGINAL_BLOCK_FEATURES_EMPTY")
            for step in steps:
                no=step.get("feature_no")
                if type(no) is not int or not 1<=no<=104 or no in features:
                    raise ValueError("DUPLICATE_OR_INVALID_FEATURE")
                missing=step.get("missing_gates")
                verified=step.get("verified_gates")
                acceptance=step.get("acceptance")
                if not isinstance(missing,list) or not isinstance(verified,list):
                    raise ValueError("MISSING_ORIGINAL_EVIDENCE_GATE")
                if acceptance=="verified" and missing:
                    raise ValueError("UPSTREAM_FALSE_VERIFIED_FEATURE")
                features[no]={
                    "number":no,"name":step.get("label",""),
                    "block_id":block_id,"original_flow":flow,
                    "acceptance_state":acceptance,
                    "verified_evidence":verified,"missing_evidence":missing,
                    "existing_api_inspect_endpoint":step.get("inspect_endpoint"),
                    "actual_job_executed":False
                }
            blocks[block_id]={
                "id":block_id,"name":b.get("name",""),
                "original_flow":flow,"status":b.get("status"),
                "missing_evidence":b.get("output_value",{}).get("missing_evidence_keys",[]),
                "feature_numbers":[x["feature_no"] for x in steps]
            }
    if len(blocks)!=43 or len(features)!=104 or set(features)!=set(range(1,105)):
        raise ValueError("ORIGINAL_43_BLOCK_104_FEATURE_COVERAGE_INVALID")
    confirmed=sum(x["acceptance_state"]=="verified" and not x["missing_evidence"] for x in features.values())
    return {
        "mode":"original_postgresql_read_only","source_provenance":SOURCE,
        "bid_no":CASE_BID,"bid_ord":CASE_ORD,"official_notice_verified":notice_verified,
        "verified_official_detail10":sorted(official_details),
        "original_flows_checked":len(results),"business_blocks_checked":len(blocks),
        "features_checked":len(features),"features_officially_verified":confirmed,
        "features_missing_or_blocked":104-confirmed,
        "eligible_for_manual_bid_participation":bool(
            confirmed==104 and notice_verified and
            all(x["status"]=="verified" for x in blocks.values())
        ),
        "features":[features[i] for i in range(1,105)],
        "blocks":[blocks[i] for i in sorted(blocks)],
        "automatic_bid_submission":False,"actual_job_executed":False,
        "bid_participation_clicked":False,"official_api_crawl_performed":False,
        "disclaimer":"Existing original DB evidence inspection only; not execution or a tender submission."
    }
