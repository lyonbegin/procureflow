"""Credential-gated bridge from native n8n to EXISTING G2B worker jobs.

This module is an API and event log, never a second workflow runner. n8n owns
decisions, branches and wait/retry. Live dispatch requires an explicit real
collector, verified source preconditions, a request-id for idempotency and an
authenticated administrator. NO submitted bids and NO accepting mock fixtures.
"""
from __future__ import annotations

import json
import re
import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field
from db import session
from g2b_case_10y import CASE_BID
from g2b_feature_api import FeatureRunRequest, collection_action, notice_context, queue_one
from n8n_operational import _get_flow, _selected_case, inspect_flow

router = APIRouter(prefix="/api/n8n/operational", tags=["n8n real G2B worker bridge"])
REQUEST_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{11,119}$")
COLLECTORS = frozenset({
    "refresh_selected_official_notice",
    "list_original_attachments",
    "download_original_attachments",
    "extract_original_documents",
    "collect_exact_ten_digit_outcomes",
    "evaluate_company_eligibility",
    "evaluate_cost_or_proposal",
    "evaluate_readiness",
})
COOLDOWN_MINUTES = 30
MAX_ACTIVE_G2B_FEATURE_JOBS = 3
MANUAL_REVIEW_FLOWS = {"PF12", "PF14", "PF15"}


def ensure_dispatch_schema():
    with session() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS procureflow.n8n_feature_dispatch(
            bid_no text NOT NULL,
            flow_id text NOT NULL,
            request_key text NOT NULL,
            feature_no integer NOT NULL,
            job_id bigint,
            state text NOT NULL DEFAULT 'reserved',
            error text NOT NULL DEFAULT '',
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY(bid_no,flow_id,request_key),
            CHECK(feature_no BETWEEN 1 AND 104),
            CHECK(state IN ('reserved','queued','rejected'))
        )""")
        c.execute("""CREATE INDEX IF NOT EXISTS ix_n8n_feature_dispatch_recent
                     ON procureflow.n8n_feature_dispatch(bid_no,flow_id,created_at DESC)""")


def _collector_allowed(flow_id: str, number: int, context: dict) -> tuple[bool,str]:
    f = _get_flow(flow_id)
    if flow_id in MANUAL_REVIEW_FLOWS:
        return False,"review_or_resource_management_is_manual_only"
    if number not in f["business_features"]:
        return False,"feature_not_owned_by_this_pf_flow"
    action=collection_action(number)
    if action not in COLLECTORS or action=="verify_stored_evidence":
        return False,"no_individual_collector"
    # Official selected notice must be in DB for everything except fetching it.
    if action!="refresh_selected_official_notice" and not context.get("original_notice_verified"):
        return False,"original_notice_not_verified"
    # The configured 10-digit code is NOT official G2B evidence.
    if action=="collect_exact_ten_digit_outcomes":
        from g2b_case_10y import SUB10
        if SUB10 not in (context.get("official_detail10") or []):
            return False,"official_selected_10_digit_code_missing"
    return True,"real_collector_available"


def _recent_jobs(bid_no: str) -> list[dict]:
    with session() as c:
        rows=c.execute("""SELECT id,state,config,created_at,started_at,finished_at
            FROM procureflow.jobs
            WHERE source='g2b_feature' AND config->>'bid_no'=%s
            ORDER BY id DESC LIMIT 120""", (bid_no,)).fetchall()
    return [dict(x) for x in rows]


def compute_next_action(flow_id: str, bid_no: str, observed: dict,
                        context: dict, jobs: list[dict], now: datetime|None=None) -> dict:
    """Pure policy for testability. One distinct shared-collector call per run.

    Sources: actual materialized 104 acceptance states, official notice facts,
    real worker queue state. No fabricated DONE or silent batch enqueues.
    """
    _selected_case(bid_no)
    _get_flow(flow_id)
    now=now or datetime.now(timezone.utc)
    if flow_id in MANUAL_REVIEW_FLOWS:
        return {"status":"MANUAL_ONLY","candidate":None,
                "reason":"final_approval_or_recovery_requires_human_and_separate_worker_checks"}
    features=[step for block in observed["blocks"] for step in block["features"]]
    candidates=[]
    blocked=[]
    seen=set()
    active=sum(j.get("state") in ("queued","running") for j in jobs)
    for step in features:
        number=step["feature_no"]
        resource=collection_action(number)
        if resource in seen or step.get("acceptance")=="verified":
            continue
        seen.add(resource)
        permitted,reason=_collector_allowed(flow_id,number,context)
        if not permitted:
            blocked.append({"feature_no":number,"reason":reason})
            continue
        recent=[j for j in jobs if
                collection_action(int(j.get("config",{}).get("feature_no",0)))==resource
                if 1<=int(j.get("config",{}).get("feature_no",0))<=104]
        if any(j.get("state") in ("queued","running") for j in recent):
            blocked.append({"feature_no":number,"reason":"collector_job_already_queued_or_running"})
            continue
        cooldown=False
        for j in recent:
            created=j.get("created_at")
            if isinstance(created,datetime) and j.get("state") in ("completed","completed_partial","failed"):
                if created.tzinfo is None:
                    created=created.replace(tzinfo=timezone.utc)
                elapsed=(now-created).total_seconds()
                if 0<=elapsed < COOLDOWN_MINUTES*60:
                    cooldown=True
                    break
        if cooldown:
            blocked.append({"feature_no":number,"reason":"collector_cooldown"})
            continue
        candidates.append({"feature_no":number,
                           "resource":resource,
                           "missing_evidence":step.get("missing_gates",[]),
                           "source":"verified_procureflow_business_registry"})
    if active >= MAX_ACTIVE_G2B_FEATURE_JOBS:
        return {"status":"WAIT_CAPACITY","candidate":None,
                "active_jobs":active,"resource_limit":MAX_ACTIVE_G2B_FEATURE_JOBS,
                "blocked":blocked}
    candidate=candidates[0] if candidates else None
    return {"status":"ACTIONABLE" if candidate else "BLOCKED_OR_COMPLETE",
            "candidate":candidate,
            "reason":"bounded_real_worker_job_available" if candidate else
                     "all_evidence_verified_or_collectors_waiting_or_unimplemented",
            "active_jobs":active,"resource_limit":MAX_ACTIVE_G2B_FEATURE_JOBS,
            "other_candidates":candidates[1:],
            "blocked":blocked[:20],
            "business_state":observed["business_state"],
            "bid_submitted":False}


@router.get("/flows/{flow_id}/next-action", summary="Read-only plan for one actually supported collector")
def next_action(flow_id:str, bid_no: str = Query(CASE_BID)):
    _selected_case(bid_no)
    observed=inspect_flow(flow_id,bid_no)
    ctx=notice_context(bid_no)
    policy=compute_next_action(flow_id,bid_no,observed,ctx,_recent_jobs(bid_no))
    return {**policy,"flow_id":flow_id,"bid_no":bid_no,
            "request_key":secrets.token_urlsafe(24),
            "read_only":True,"job_enqueued":False,
            "official_detail10":ctx.get("official_detail10") or []}


class DispatchRequest(BaseModel):
    bid_no: str=Field(min_length=1,max_length=70)
    feature_no:int=Field(ge=1,le=104)
    request_key:str=Field(min_length=12,max_length=120)
    parameters:dict=Field(default_factory=dict)


@router.post("/flows/{flow_id}/dispatch", summary="Enqueue exactly one real, credential-gated G2B Worker job")
def dispatch(flow_id:str, body:DispatchRequest,
             authorization:str|None=Header(None)):
    from main import guard
    guard(authorization)
    _selected_case(body.bid_no)
    if not REQUEST_KEY.fullmatch(body.request_key):
        raise HTTPException(422,"Invalid idempotency request key")
    context=notice_context(body.bid_no)
    allowed,reason=_collector_allowed(flow_id,body.feature_no,context)
    if not allowed:
        raise HTTPException(409,reason)
    ensure_dispatch_schema()
    with session() as c:
        inserted=c.execute("""INSERT INTO procureflow.n8n_feature_dispatch(
          bid_no,flow_id,request_key,feature_no,state)
          VALUES(%s,%s,%s,%s,'reserved') ON CONFLICT DO NOTHING
          RETURNING request_key""",
          (body.bid_no,flow_id,body.request_key,body.feature_no)).fetchone()
        if not inserted:
            old=c.execute("""SELECT feature_no,job_id,state,error
                 FROM procureflow.n8n_feature_dispatch
                 WHERE bid_no=%s AND flow_id=%s AND request_key=%s""",
                 (body.bid_no,flow_id,body.request_key)).fetchone()
            if not old:
                raise HTTPException(409,"Request reservation being committed; retry safely")
            if old["feature_no"]!=body.feature_no:
                raise HTTPException(409,"Idempotency key reused for a different feature")
            return {"flow_id":flow_id,"bid_no":body.bid_no,"feature_no":body.feature_no,
                    "job_id":old["job_id"],"state":old["state"],
                    "deduplicated":True,"submitted":False}
    try:
        # The insert above makes a one-time reservation before queueing. A
        # process crash leaves a reserved row, NOT another uncontrolled enqueue.
        observed=inspect_flow(flow_id,body.bid_no)
        policy=compute_next_action(flow_id,body.bid_no,observed,context,
                                   _recent_jobs(body.bid_no))
        if (policy["status"]!="ACTIONABLE" or
            policy["candidate"]["resource"]!=collection_action(body.feature_no)):
            raise HTTPException(409,"Collector unavailable: "+policy["status"])
        job=queue_one(body.bid_no,body.feature_no,
                      FeatureRunRequest(mode="collect",parameters=body.parameters))
        with session() as c:
            c.execute("""UPDATE procureflow.n8n_feature_dispatch
                SET job_id=%s,state='queued',updated_at=now()
                WHERE bid_no=%s AND flow_id=%s AND request_key=%s""",
                (job["job_id"],body.bid_no,flow_id,body.request_key))
        return {"flow_id":flow_id,"bid_no":body.bid_no,
                "feature_no":body.feature_no,
                "job_id":job["job_id"],"state":"queued",
                "status_url":f"/api/n8n/operational/flows/{flow_id}/jobs/{job['job_id']}",
                "deduplicated":False,"submitted":False,
                "acceptance_is_not_inferred_from_job_queue":True}
    except Exception as exc:
        with session() as c:
            c.execute("""UPDATE procureflow.n8n_feature_dispatch
                SET state='rejected',error=%s,updated_at=now()
                WHERE bid_no=%s AND flow_id=%s AND request_key=%s""",
                (type(exc).__name__[:60],body.bid_no,flow_id,body.request_key))
        raise


@router.get("/flows/{flow_id}/jobs/{job_id}", summary="Read actual worker completion and independent evidence gate")
def job_status(flow_id:str,job_id:int,bid_no:str=Query(CASE_BID),
               authorization:str|None=Header(None)):
    from main import guard
    guard(authorization)
    _selected_case(bid_no)
    flow=_get_flow(flow_id)
    from g2b_feature_api import api_feature_job
    detail=api_feature_job(bid_no,job_id,authorization)
    if int(detail["feature_no"]) not in flow["business_features"]:
        raise HTTPException(404,"Job does not belong to the PF flow")
    terminal=detail["state"] in ("completed","completed_partial","failed","cancelled")
    # Another fresh DB read: worker state != acceptance state.
    from g2b_feature_api import inspect_feature
    from g2b_case_engine import dashboard
    acceptance=inspect_feature(
        bid_no,int(detail["feature_no"]),
        snapshot=dashboard(bid_no,15,refresh=False),
    )
    return {"flow_id":flow_id,"bid_no":bid_no,"job_id":job_id,
            "worker_state":detail["state"],
            "worker_terminal":terminal,
            "worker_error":detail["error"],
            "run_id":detail["run_id"],
            "worker_execution":detail["execution_result"],
            "feature_no":detail["feature_no"],
            "independently_verified":acceptance["acceptance_state"]=="verified",
            "missing_evidence":acceptance["missing_evidence"],
            "business_state":"VERIFIED" if acceptance["acceptance_state"]=="verified" else "BLOCKED_OR_PENDING",
            "bid_submitted":False}


@router.get("/flows/{flow_id}/dispatch-history",summary="Authenticated last 30 n8n real job dispatches")
def dispatch_history(flow_id:str,bid_no:str=Query(CASE_BID),
                     authorization:str|None=Header(None)):
    from main import guard
    guard(authorization)
    _selected_case(bid_no)
    _get_flow(flow_id)
    ensure_dispatch_schema()
    with session() as c:
        rows=c.execute("""SELECT request_key,feature_no,job_id,state,error,
                              created_at,updated_at
            FROM procureflow.n8n_feature_dispatch
            WHERE flow_id=%s AND bid_no=%s
            ORDER BY created_at DESC LIMIT 30""",(flow_id,bid_no)).fetchall()
    return {"flow_id":flow_id,"bid_no":bid_no,"items":[dict(x) for x in rows],
            "bid_submitted":False}
