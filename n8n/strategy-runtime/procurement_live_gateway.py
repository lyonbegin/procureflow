"""One origin-scoped, explicit API gateway for the EXISTING real G2B backend.

Used by the preinstalled shared Studio and the public9 admin page. It is NOT
another auction crawler, n8n engine or evidence store. Only allowlisted HTTPS
GET endpoints and an explicitly administrator-authorized POST can be called.
"""
from __future__ import annotations
import json
import re
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.parse import urlencode
from urllib.error import HTTPError

API="https://procureflow-api-production.up.railway.app"
JOB_ID=re.compile(r"^[1-9][0-9]{0,11}$")
PUBLIC_ID="R26BK01787028"
MAX_REPLY=2_500_000

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        raise ValueError("PUBLIC_API_REDIRECT_REFUSED")

def _request(path,method="GET",body=None,token=None,*,opener=None):
    if not path.startswith("/api/g2b/public/") or "://" in path or ("?" in path and not path.startswith("/api/g2b/public/notices?")):
        raise ValueError("UNREGISTERED_BACKEND_ENDPOINT")
    if method not in ("GET","POST"):
        raise ValueError("INVALID_METHOD")
    if method=="POST" and (not token or not 12<=len(token)<=300):
        raise ValueError("ADMIN_TOKEN_REQUIRED")
    headers={"Accept":"application/json","User-Agent":"ProcureFlow-Shared-Studio-Public9/1"}
    raw=None
    if method=="POST":
        raw=json.dumps(body,ensure_ascii=False).encode("utf-8")
        if len(raw)>1200:
            raise ValueError("POST_BODY_TOO_LARGE")
        headers["Content-Type"]="application/json"
        headers["Authorization"]="Bearer "+token
    transport=opener or build_opener(NoRedirect())
    try:
        response=transport.open(Request(API+path,data=raw,headers=headers,method=method),timeout=16)
        with response as stream:
            if stream.status not in (200,202):
                raise ValueError("BACKEND_BAD_STATUS")
            if "application/json" not in stream.headers.get("Content-Type",""):
                raise ValueError("BACKEND_JSON_REQUIRED")
            buf=stream.read(MAX_REPLY+1)
            if len(buf)>MAX_REPLY:
                raise ValueError("BACKEND_RESPONSE_TOO_LARGE")
            data=json.loads(buf)
    except HTTPError as exc:
        # Do not echo the supplied token or raw server messages to the browser.
        return exc.code,{"error":"BACKEND_REJECTED_REQUEST","http_status":exc.code}
    if not isinstance(data,dict):
        raise ValueError("BACKEND_NOT_JSON_OBJECT")
    return (202 if method=="POST" else 200),data


def _stage1_actual_notice_nodes(query):
    """Run N01 DB read and N02 identifier/branch classification on real source.
    This is not a G2B crawl or an n8n Execution; unknown states stay unknown.
    """
    from datetime import datetime, timezone
    status,notice=proxy_get("notices",query)
    if status!=200 or notice.get("source")!="actual_procureflow_postgresql_g2b_notices" or not isinstance(notice.get("items"),list):
        raise ValueError("STAGE1_REQUIRES_ACTUAL_POSTGRESQL_NOTICES")
    rows=notice["items"]
    stamp=datetime.now(timezone.utc).isoformat()
    n01_input={"query":query,"operation":"read_existing_g2b_postgresql","crawl_requested":False}
    n01_output={"source":notice["source"],"records":rows,"returned_count":len(rows),
                "total":notice.get("total"),"read_at_utc":stamp}
    identified=[]
    seen=set()
    for row in rows:
        if not isinstance(row,dict):
            raise ValueError("INVALID_SOURCE_NOTICE_ROW")
        bid=row.get("bid_no")
        ord_=row.get("bid_ord")
        if not isinstance(bid,str) or not re.fullmatch(r"[A-Za-z0-9-]{5,50}",bid):
            raise ValueError("INVALID_SOURCE_BID_IDENTIFIER")
        if ord_ is not None and not isinstance(ord_,str):
            raise ValueError("INVALID_SOURCE_BID_ORDINAL")
        key=(bid,ord_)
        if key in seen:
            continue
        seen.add(key)
        raw_state=str(row.get("notice_status") or row.get("notice_type") or "").lower().strip()
        if row.get("is_cancelled") is True or raw_state in ("cancelled","canceled","취소"):
            branch="cancelled"
        elif row.get("is_amended") is True or raw_state in ("amended","corrected","정정"):
            branch="amended"
        elif row.get("is_new") is True or raw_state in ("new","신규"):
            branch="new"
        else:
            branch="unknown_unverified"
        identified.append({"bid_no":bid,"bid_ord":ord_,"title":row.get("title"),
                           "agency":row.get("agency"),"notice_date":row.get("notice_date"),
                           "deadline":row.get("deadline"),"branch":branch,
                           "can_run_full_evidence":row.get("can_run_full_evidence") is True})
    n02_input={"upstream_node_id":"N01","source":n01_output["source"],
               "records":n01_output["records"]}
    n02_output={"tender_identifiers":identified,"unique_count":len(identified),
                "duplicate_rows_filtered":len(rows)-len(identified),
                "branches":{"new":sum(x["branch"]=="new" for x in identified),
                            "amended":sum(x["branch"]=="amended" for x in identified),
                            "cancelled":sum(x["branch"]=="cancelled" for x in identified),
                            "unknown_unverified":sum(x["branch"]=="unknown_unverified" for x in identified)}}
    return 200,{"source":notice["source"],"notices":notice,
                "execution_kind":"actual_database_read_and_identifier_processing_not_n8n",
                "crawler_executed":False,"worker_executed":False,
                "nodes":[{"id":"N01","name":"기존 PostgreSQL 공고 후보 확보",
                          "status":"db_read_executed","input":n01_input,"output":n01_output},
                         {"id":"N02","name":"공고번호·차수 식별과 분기 판단",
                          "status":"identification_executed","input":n02_input,"output":n02_output}],
                "connections":[{"from":"N01","to":"N02","field":"output.records -> input.records"},
                               {"from":"N02","to":"N05","condition":"user_selected_and_official_detail_required"},
                               {"from":"N02","to":"O01","condition":"user_selected_and_case_claim_required"},
                               {"from":"N02","to":"PF13","condition":"amended"},
                               {"from":"N02","to":"HOLD","condition":"cancelled_or_unverified"}]}

def proxy_get(route,query=""):
    """Known live endpoints only; no arbitrary paths/SSRF/credential leaking."""
    from urllib.parse import parse_qs
    if route=="stage1":
        return _stage1_actual_notice_nodes(query)
    if route=="notices":
        params=parse_qs(query,keep_blank_values=True)
        if set(params)-{"q","status","limit","offset"}:
            raise ValueError("UNKNOWN_LIST_FILTER")
        q=params.get("q",[""])[0]
        status=params.get("status",["all"])[0]
        limit=params.get("limit",["30"])[0]
        offset=params.get("offset",["0"])[0]
        if not isinstance(q,str) or len(q)>120 or any(ord(ch)<32 for ch in q) or status not in ("all","open","closed"):
            raise ValueError("INVALID_LIST_FILTER")
        if not limit.isdigit() or not 1<=int(limit)<=100:
            raise ValueError("INVALID_LIST_LIMIT")
        if not offset.isdigit() or int(offset)>10000:
            raise ValueError("INVALID_LIST_OFFSET")
        return _request("/api/g2b/public/notices?"+urlencode({
            "q":q,"status":status,"limit":limit,"offset":offset}))
    if route=="latest":
        return _request("/api/g2b/public/selected/prepare-jobs/latest")
    if route.startswith("job/"):
        id=route.removeprefix("job/")
        if not JOB_ID.fullmatch(id):
            raise ValueError("INVALID_PUBLIC_JOB_ID")
        return _request("/api/g2b/public/selected/prepare-jobs/"+id)
    if route=="catalog":
        return 200,{"workflow":"operations/PF00-public-nine-real.json",
            "actual_worker_source":"g2b_public_prepare",
            "native_n8n_execution_connected":False,
            "supported_case_bid_no":PUBLIC_ID,
            "real_source_only":True,"business_nodes":9,
            "manual_bid_submit":True}
    raise ValueError("UNREGISTERED_PUBLIC_ROUTE")

def start_real_case(payload,authorization):
    """Only queue actual existing Worker, with user's existing admin token.

    This endpoint does not pass credentials to the Studio node or store them.
    Other selected tenders fail closed until original case engine is generalized.
    """
    if not isinstance(payload,dict) or set(payload)-{
        "bid_no","start","end","detail10","agency"}:
        raise ValueError("UNREGISTERED_PUBLIC_PREPARATION_INPUT")
    if payload.get("bid_no")!=PUBLIC_ID or payload.get("detail10")!="8111159901":
        raise ValueError("SELECTED_CASE_ENGINE_NOT_YET_CONNECTED")
    import datetime
    try:
        start=datetime.date.fromisoformat(payload["start"])
        end=datetime.date.fromisoformat(payload["end"])
    except (KeyError,ValueError,TypeError):
        raise ValueError("INVALID_DATE_FILTER") from None
    if not(datetime.date(2016,10,24)<=start<=end<=datetime.date(2026,10,22)):
        raise ValueError("OUT_OF_SELECTED_CASE_DATE_RANGE")
    agency=payload.get("agency","")
    if not isinstance(agency,str) or len(agency)>100 or any(ord(c)<32 for c in agency):
        raise ValueError("INVALID_AGENCY")
    if not isinstance(authorization,str) or not authorization.startswith("Bearer "):
        raise ValueError("EXISTING_ADMIN_AUTHORIZATION_REQUIRED")
    token=authorization[7:]
    return _request("/api/g2b/public/selected/prepare","POST",
        {"start":start.isoformat(),"end":end.isoformat(),
         "detail10":"8111159901","agency":agency},token)
