"""Read-only automatic test for a selected public tender.

This performs real DB-backed GETs and validates the exact cookie-scoped saved
Studio graph. It never invokes a worker, uploads a tender, or requires a token.
"""
import datetime
import json
import re
import sqlite3
from urllib.parse import urlencode, urlsplit, parse_qs

CASE = "R26BK01787028"
DETAIL = "8111159901"
FLOW = "operations/PF00-public-nine-real.json"

def approved_filter(workflow):
    import procurement_live_gateway as live
    if not isinstance(workflow,dict) or len(workflow.get("nodes",[]))!=10:
        raise ValueError("APPROVED_TEN_NODE_GRAPH_REQUIRED")
    nodes={n["id"]:n for n in workflow["nodes"] if isinstance(n,dict) and "id" in n}
    ids=["public9-trigger"]+[f"public9-{i:02d}" for i in range(1,10)]
    if len(nodes)!=10 or set(nodes)!=set(ids):
        raise ValueError("APPROVED_GRAPH_IDS_REQUIRED")
    for src,dst in zip(ids,ids[1:]):
        frm,to=nodes[src],nodes[dst]
        edges=workflow.get("connections",{}).get(frm.get("name"),{}).get("main",[[]])
        if len(edges)!=1 or len(edges[0])!=1 or edges[0][0].get("node")!=to.get("name"):
            raise ValueError("APPROVED_GRAPH_CONNECTIONS_REQUIRED")
    fourth=nodes["public9-04"]
    if fourth.get("type")!="n8n-nodes-base.httpRequest" or fourth.get("parameters",{}).get("method")!="GET":
        raise ValueError("SEARCH_NODE_METHOD_NOT_APPROVED")
    url=urlsplit(fourth.get("parameters",{}).get("url",""))
    if (url.scheme,url.netloc,url.path)!=("https","procureflow-api-production.up.railway.app","/api/g2b/public/selected/search"):
        raise ValueError("SEARCH_NODE_SOURCE_NOT_APPROVED")
    params=parse_qs(url.query,keep_blank_values=True)
    allowed={"start","end","detail10","kind","agency","limit","offset"}
    required={"start","end","detail10","kind"}
    if not required.issubset(params) or set(params)-allowed or any(len(v)!=1 for v in params.values()):
        raise ValueError("SEARCH_NODE_QUERY_NOT_APPROVED")
    limit,offset=params.get("limit",["100"])[0],params.get("offset",["0"])[0]
    if not limit.isdigit() or not 1<=int(limit)<=200 or not offset.isdigit() or not 0<=int(offset)<=50000:
        raise ValueError("SEARCH_NODE_PAGINATION_NOT_APPROVED")
    start,end=params["start"][0],params["end"][0]
    if params["detail10"][0]!=DETAIL or params["kind"][0]!="opening":
        raise ValueError("SEARCH_NODE_TENDER_CATEGORY_NOT_APPROVED")
    try:
        a,b=datetime.date.fromisoformat(start),datetime.date.fromisoformat(end)
    except ValueError:
        raise ValueError("SEARCH_NODE_DATE_INVALID") from None
    if not datetime.date(2016,10,24)<=a<=b<=datetime.date(2026,10,22):
        raise ValueError("SEARCH_NODE_DATE_OUT_OF_RANGE")
    agency=params.get("agency",[""])[0]
    if len(agency)>100 or any(ord(c)<32 for c in agency):
        raise ValueError("SEARCH_NODE_AGENCY_INVALID")
    return {"start":start,"end":end,"agency":agency,"detail10":DETAIL,"kind":"opening"}

def run(sid,db_path,fixture_path,body):
    """Return test result with exact verification provenance; absolutely no POST."""
    import procurement_live_gateway as live
    if not isinstance(body,dict) or set(body)!={"bid_no","detail10"} or body["bid_no"]!=CASE or body["detail10"]!=DETAIL:
        raise ValueError("EXACT_SELECTED_TENDER_REQUIRED")
    with sqlite3.connect(db_path,timeout=8) as db:
        row=db.execute("SELECT payload FROM snapshots WHERE sid=? AND path=?",(sid,FLOW)).fetchone()
    workflow=json.loads(row[0]) if row else json.loads(fixture_path(FLOW).read_text())
    filters=approved_filter(workflow)
    status,stage1=live.proxy_get("stage1",urlencode({"q":"","status":"all","limit":"30","offset":"0","selected_bid_no":CASE}))
    if status!=200 or stage1.get("source")!="actual_procureflow_postgresql_g2b_notices":
        raise ValueError("ACTUAL_POSTGRESQL_STAGE1_UNAVAILABLE")
    selected=stage1.get("selected_route",{}).get("selected") or {}
    if selected.get("bid_no")!=CASE:
        raise ValueError("SELECTED_TENDER_NOT_IN_ACTUAL_SOURCE")
    url="/api/g2b/public/selected/search?"+urlencode({**filters,"limit":10,"offset":0})
    search_status,search=live._request(url,method="GET")
    if search_status!=200 or not isinstance(search,dict):
        raise ValueError("REAL_HISTORY_SEARCH_UNAVAILABLE")
    # Never claim that read-only data retrieval constitutes all nine steps.
    steps=[
        {"node":"N01","status":"ACTUAL_DB_READ","source":"actual_procureflow_postgresql_g2b_notices"},
        {"node":"N02","status":"IDENTIFIERS_VERIFIED","bid_no":CASE,"branch":selected.get("branch","unknown")},
        {"node":"N04","status":"READ_ONLY_SEARCH_SUCCESS","source":"existing_public_G2B_search_endpoint"},
    ]
    return {"mode":"read_only_automated_test","status":"PARTIAL_READ_ONLY_VERIFIED",
        "test_passed":True,"selected_bid_no":CASE,"detail10":DETAIL,
        "search_filter":filters,"source":"actual_procureflow_postgresql_g2b_notices",
        "selected_route":stage1.get("selected_route",{}).get("route"),
        "search_result_keys":sorted(search.keys())[:20],
        "verified_steps":steps,"remaining_nodes":"NOT_EXECUTED",
        "worker_executed":False,"worker_job_created":False,"bid_submitted":False,
        "electronic_signature":False,
        "note":"N01/N02 실제 DB 조회 + N04 실제 과거 검색 확인. 나머지 업무 노드 및 Worker 실행 아님."}
