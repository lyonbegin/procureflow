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

def proxy_get(route,query=""):
    """Known live endpoints only; no arbitrary paths/SSRF/credential leaking."""
    from urllib.parse import parse_qs
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
