"""104 individually addressable, evidence-gated G2B APIs.

Every operation starts from the ONE selected G2B notice in the existing database.
A function's endpoint exists independently of whether its collector is implemented.
Never report success from a queued job, manually supplied text, or a collector
that produced no independently verified acceptance evidence.
"""
from __future__ import annotations

import json
from typing import Any, Literal

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field

from db import session
from g2b_case_10y import CASE_BID, CASE_ORD, CAT8, SUB10, BEGIN, END
from g2b_feature_registry import FEATURES, FEATURE_GATES

router = APIRouter(prefix="/api/g2b/cases", tags=["G2B selected-notice 104 functions"])
CATALOG = {item["number"]: item for item in FEATURES}
assert len(CATALOG) == 104

# Only collector arguments actually used by the existing implementation are
# accepted. Notice identifiers, institution and classification are NEVER
# caller-supplied overrides.
HISTORY_PARAMS = {
    "candidate_limit": {"type": "integer", "minimum": 1, "maximum": 4, "default": 4,
                        "description": "Number of original-detail candidates to inspect in this run"},
    "opening_limit": {"type": "integer", "minimum": 1, "maximum": 2, "default": 2,
                      "description": "Number of verified opening details to inspect"},
}
FILE_PARAMS = {
    "file_id": {"type": "string", "maxLength": 150,
                "description": "Optional specific attachment ID; omitted means process listed originals"},
}
ACTIONS = {
    "notice": "refresh_selected_official_notice",
    "detail": "verify_stored_evidence",
    "history": "collect_exact_ten_digit_outcomes",
    "matching": "collect_exact_ten_digit_outcomes",
    "eligibility": "evaluate_company_eligibility",
    "pricing": "evaluate_cost_or_proposal",
    "operations": "evaluate_readiness",
}
# These individual business rules are not implemented as collectors yet.
# Their endpoint can still inspect evidence and report missing dependencies.
SUPPORTED_DETAIL = {17, 18, 19, 20, 21, 22, 23, 28, 29, 30, 31, 32}
SUPPORTED_NOTICE = set(range(1, 17))
SUPPORTED_HISTORY = set(range(33, 61))
SUPPORTED_ELIGIBILITY = set(range(61, 77))
SUPPORTED_PRICING = set(range(77, 95))
SUPPORTED_OPERATIONS = set(range(95, 105))


class FeatureRunRequest(BaseModel):
    mode: Literal["check", "collect"] = "collect"
    parameters: dict[str, Any] = Field(default_factory=dict, description="Per-function parameters only; never put a second bid number here")


def _case(bid_no: str) -> str:
    if bid_no != CASE_BID:
        raise HTTPException(status_code=404, detail="Only the selected G2B notice is active")
    return bid_no


def contract_params(number: int) -> dict:
    if number in SUPPORTED_HISTORY:
        return HISTORY_PARAMS
    if number == 29:
        return FILE_PARAMS
    return {}


def normalize_params(number: int, supplied: dict) -> dict:
    if not isinstance(supplied, dict):
        raise ValueError("parameters must be an object")
    spec = contract_params(number)
    unknown = set(supplied) - set(spec)
    if unknown:
        raise ValueError("Unsupported parameters: " + ", ".join(sorted(unknown)))
    clean = {}
    for key, value in supplied.items():
        definition = spec[key]
        if definition["type"] == "integer":
            if type(value) is not int or not definition["minimum"] <= value <= definition["maximum"]:
                raise ValueError(key + " must be an integer in permitted range")
        elif definition["type"] == "string":
            if not isinstance(value, str) or not value.strip() or len(value) > definition["maxLength"]:
                raise ValueError(key + " must be a non-empty attachment identifier")
            if any(char in value for char in ("/", "\\", "\x00")):
                raise ValueError("Invalid attachment identifier")
        clean[key] = value
    return clean


def collection_action(number: int) -> str:
    if number in SUPPORTED_NOTICE or 17 <= number <= 23:
        return "refresh_selected_official_notice"
    if number in (28, 30):
        return "list_original_attachments"
    if number == 29:
        return "download_original_attachments"
    if number in (31, 32):
        return "extract_original_documents"
    if number in SUPPORTED_HISTORY:
        return "collect_exact_ten_digit_outcomes"
    if number in SUPPORTED_ELIGIBILITY:
        return "evaluate_company_eligibility"
    if number in SUPPORTED_PRICING:
        return "evaluate_cost_or_proposal"
    if number in SUPPORTED_OPERATIONS:
        return "evaluate_readiness"
    return "verify_stored_evidence"


def notice_context(bid_no: str) -> dict:
    """Rehydrate facts from actual selected official notice, never from client input."""
    _case(bid_no)
    with session() as con:
        current = con.execute("""SELECT source,external_id,title,agency,category,
                notice_date,deadline,method,source_url,raw
                FROM procureflow.tenders
                WHERE source='g2b' AND external_id=%s""", (bid_no,)).fetchone()
        control = con.execute("""SELECT bid_no,bid_ord,category8,title,state
                FROM procureflow.g2b_case_control WHERE bid_no=%s""",
                              (bid_no,)).fetchone()
        codes = con.execute("""SELECT code_type,code,evidence_level,source_uri
                FROM procureflow.g2b_notice_categories
                WHERE bid_no=%s AND bid_ord=%s""",
                            (bid_no, CASE_ORD)).fetchall()
    row = dict(current) if current else {}
    raw = row.get("raw") if isinstance(row.get("raw"), dict) else {}
    original = raw.get("bidNtceNo") == bid_no
    official = [dict(c) for c in codes if c["evidence_level"] == "official_direct"]
    exact10 = sorted({str(c["code"]) for c in official
                      if c["code_type"] == "detail10"
                      and len(str(c["code"])) == 10})
    parent8 = sorted({str(c["code"]) for c in official
                      if len(str(c["code"])) == 8})
    parent8.extend([x[:8] for x in exact10 if x[:8] not in parent8])
    return {
        "bid_no": bid_no, "bid_ord": CASE_ORD, "data_source": "procureflow.tenders",
        "original_notice_verified": original, "title": row.get("title") or (control or {}).get("title"),
        "agency": row.get("agency") if original else None,
        "agency_code": raw.get("ntceInsttCd") if original else None,
        "notice_date": row.get("notice_date") if original else None,
        "deadline": row.get("deadline") if original else None,
        "method": row.get("method") if original else None,
        "source_url": row.get("source_url") if original else None,
        "official_parent8": sorted(set(parent8)),
        "official_detail10": exact10,
        "configured_historical_target": {
            "category8": CAT8, "detail10": SUB10,
            "begin": BEGIN.isoformat(), "end": END.isoformat(),
            "note": "Target configuration, not proof of official classification or 10-year coverage",
        },
        "missing_notice": not original,
    }


def _snapshot(bid_no: str) -> dict:
    from g2b_case_engine import dashboard
    return dashboard(bid_no, 15)


def feature_contract(number: int, context: dict, snapshot: dict) -> dict:
    item = CATALOG[number]
    found = next(x for x in snapshot["feature_acceptance"] if x["number"] == number)
    accepted = set(snapshot.get("verified_evidence_types") or ())
    gate = list(FEATURE_GATES[number])
    done = [x for x in gate if x in accepted]
    not_done = [x for x in gate if x not in accepted]
    action = collection_action(number)
    return {
        "number": number, "name": item["label"], "group": item["group"],
        "source_bid_no": context["bid_no"], "source_bid_ord": context["bid_ord"],
        "endpoint": f"/api/g2b/cases/{context['bid_no']}/features/{number}",
        "execute_endpoint": f"/api/g2b/cases/{context['bid_no']}/features/{number}/run",
        "runs_endpoint": f"/api/g2b/cases/{context['bid_no']}/features/{number}/runs",
        "input_contract": {
            "method": "POST", "body": {"mode": "collect", "parameters": {}},
            "parameters": contract_params(number),
            "additional_properties_allowed": False,
            "auto_from_selected_notice": [
                {"name": "bid_no", "value": context["bid_no"], "source": "selected_notice"},
                {"name": "bid_ord", "value": context["bid_ord"], "source": "selected_notice"},
                {"name": "title", "value": context["title"], "source": "selected_notice"},
                {"name": "agency", "value": context["agency"], "source": "official_notice"},
                {"name": "agency_code", "value": context["agency_code"], "source": "official_notice"},
                {"name": "deadline", "value": context["deadline"], "source": "official_notice"},
                {"name": "detail10", "value": context["official_detail10"], "source": "official_classification"},
                {"name": "parent8", "value": context["official_parent8"], "source": "official_classification"},
            ],
            "required_verified_evidence": gate,
            "missing_verified_evidence": not_done,
            "manual_material_entry_endpoint": "/api/g2b/full/evidence",
            "company_or_cost_draft_entry_endpoint": "/api/g2b/full/decision",
            "manual_input_does_not_verify_original": True,
        },
        "execution": {
            "action": action,
            "execution_kind": ("evidence_check_only" if action == "verify_stored_evidence" else "shared_existing_collector_or_evaluator"),
            "business_acceptance_requires_independent_evidence": True,
            "explanation": "Only individually verified evidence gates determine acceptance. "
                           "Shared source collectors may refresh facts for several functions.",
            "never_submit_bid": True,
        },
        "output_contract": {
            "GET": ["number", "name", "input_contract", "execution", "observation",
                    "acceptance_state", "verified_evidence", "missing_evidence", "source_context"],
            "POST": ["job_id", "job_status", "feature_no", "source_bid_no", "status_url"],
            "job_result": ["feature_no", "source_bid_no", "action", "state",
                           "acceptance_state", "missing_evidence", "collector_result"],
        },
        "acceptance_state": found["acceptance_state"],
        "verified_evidence": done, "missing_evidence": not_done,
    }


def inspect_feature(bid_no: str, number: int, context=None, snapshot=None) -> dict:
    _case(bid_no)
    if number not in CATALOG:
        raise HTTPException(404, "Unknown feature number")
    context = context if context is not None else notice_context(bid_no)
    snapshot = snapshot if snapshot is not None else _snapshot(bid_no)
    from g2b_feature_data import feature_observation
    return {**feature_contract(number, context, snapshot),
            "source_context": context,
            "observation": feature_observation(number, context)}


@router.get("/{bid_no}/context", summary="Selected official tender facts for all 104 functions")
def api_selected_context(bid_no: str):
    return notice_context(bid_no)


@router.get("/{bid_no}/features", summary="All 104 functions, their parameters, acceptance and independent endpoint URLs")
def api_features(bid_no: str, state: str = Query("all", pattern="^(all|verified|partial|missing|blocked|error)$")):
    _case(bid_no)
    context = notice_context(bid_no)
    snapshot = _snapshot(bid_no)
    all_rows = [feature_contract(no, context, snapshot) for no in sorted(CATALOG)]
    rows = all_rows if state == "all" else [r for r in all_rows if r["acceptance_state"] == state]
    return {"bid_no": bid_no, "context": context, "total": 104,
            "matching": len(rows), "features": rows,
            "submit_button_clicked": False}


@router.get("/{bid_no}/features/{feature_no}/runs", summary="Independent execution history of an individual function")
def api_feature_runs(bid_no: str, feature_no: int, limit: int = Query(15, ge=1, le=50)):
    _case(bid_no)
    if feature_no not in CATALOG:
        raise HTTPException(404, "Unknown feature")
    with session() as con:
        rows = con.execute("""SELECT id,phase,state,result,error,started_at,
                          finished_at,created_at FROM procureflow.g2b_case_runs
                          WHERE bid_no=%s AND phase=%s
                          ORDER BY id DESC LIMIT %s""",
                           (bid_no, f"feature:{feature_no:03}", limit)).fetchall()
    return {"bid_no": bid_no, "feature_no": feature_no, "runs": [dict(x) for x in rows]}


@router.get("/{bid_no}/feature-jobs/{job_id}", summary="Inspect the outcome of one asynchronous function call")
def api_feature_job(bid_no: str, job_id: int, authorization: str | None = Header(None)):
    from main import guard
    guard(authorization)
    _case(bid_no)
    with session() as con:
        job = con.execute("""SELECT id,state,config,message,last_error,
                          created_at,started_at,finished_at FROM procureflow.jobs
                          WHERE id=%s AND source='g2b_feature'""", (job_id,)).fetchone()
        if not job or job["config"].get("bid_no") != bid_no:
            raise HTTPException(404, "Feature job not found")
        run_id=job["config"].get("run_id")
        run=None
        if isinstance(run_id,int) and run_id>0:
            run=con.execute("""SELECT id,phase,state,result,error,created_at,
                      started_at,finished_at FROM procureflow.g2b_case_runs
                      WHERE bid_no=%s AND id=%s
                        AND phase=%s""",
                      (bid_no,run_id,f"feature:{int(job['config']['feature_no']):03}")).fetchone()
    return {"job_id": job_id, "state": job["state"],
            "feature_no": job["config"]["feature_no"],
            "message": job["message"], "error": job["last_error"],
            "created_at": job["created_at"], "started_at": job["started_at"],
            "finished_at": job["finished_at"],
            "run_id":run_id if run else None,
            "execution_result":dict(run) if run else None,
            "acceptance_is_independent_of_worker_completion":True}


def queue_one(bid_no: str, number: int, request: FeatureRunRequest,
              *, n8n_request_key: str | None = None,
              n8n_flow_id: str | None = None) -> dict:
    _case(bid_no)
    if number not in CATALOG:
        raise HTTPException(404, "Unknown feature")
    try:
        params = normalize_params(number, request.parameters)
    except ValueError as err:
        raise HTTPException(422, str(err)) from None
    # Check mode is a lightweight independent evidence evaluation, not a
    # secret collector or a claim that the step was successfully executed.
    if request.mode == "check":
        detail = inspect_feature(bid_no, number)
        return {"bid_no": bid_no, "feature_no": number, "mode": "check",
                "state": detail["acceptance_state"], "details": detail}
    resource = collection_action(number)
    config = {"bid_no": bid_no, "bid_ord": CASE_ORD, "feature_no": number,
              "parameters": params, "resource_key": resource}
    if n8n_request_key is not None:
        # Internal n8n dispatch idempotency handle, never sourced from
        # arbitrary collector params. Allows crashed HTTP responses to
        # recover the original created job without enqueuing a second one.
        if not n8n_flow_id or len(n8n_request_key) > 120:
            raise HTTPException(422,"Invalid internal n8n dispatch metadata")
        config["n8n_request_key"] = n8n_request_key
        config["n8n_flow_id"] = n8n_flow_id
    with session() as con:
        # Only conflicting *collector resources* are serialized. A live 10-year
        # opening collector must not prevent an unrelated document or eligibility
        # operation from being queued for the same bid. The case row is locked
        # only to make the conflict check + insert atomic.
        owner=con.execute("""SELECT bid_no FROM procureflow.g2b_case_control
                          WHERE bid_no=%s FOR UPDATE""",(bid_no,)).fetchone()
        if not owner:
            raise HTTPException(404,"Selected tender control record not initialized")
        active_rows = con.execute("""SELECT id,config->>'feature_no' AS feature_no,
                               config->>'resource_key' AS resource_key
                     FROM procureflow.jobs
                     WHERE source='g2b_feature' AND config->>'bid_no'=%s
                       AND state IN ('queued','running')
                     ORDER BY id""", (bid_no,)).fetchall()
        if len(active_rows) >= 3:
            raise HTTPException(409, "Maximum 3 active G2B feature collector jobs per selected tender")
        conflicting = next(
            (row for row in active_rows
             if row.get("resource_key") == resource or (
                 not row.get("resource_key") and
                 collection_action(int(row["feature_no"])) == resource)),
            None,
        )
        if conflicting:
            raise HTTPException(409, f"Conflicting collector {resource} still active in job {conflicting['id']} (feature {conflicting['feature_no']})")
        job_id = con.execute("""INSERT INTO procureflow.jobs(source,config,message)
                      VALUES ('g2b_feature',%s::jsonb,%s) RETURNING id""",
                      (json.dumps(config, ensure_ascii=False),
                       f"One selected notice; independent G2B function {number}")).fetchone()["id"]
    return {"job_id": job_id, "job_status": "queued", "feature_no": number,
            "source_bid_no": bid_no,
            "status_url": f"/api/g2b/cases/{bid_no}/feature-jobs/{job_id}",
            "submitted": False, "verified": False}


def execute_one(bid_no: str, number: int, parameters: dict | None = None) -> dict:
    """Called ONLY in Railway worker. Perform existing safe collector or gate check."""
    _case(bid_no)
    if number not in CATALOG:
        raise ValueError("Unknown feature number")
    args = normalize_params(number, parameters or {})
    action = collection_action(number)
    with session() as con:
        run_id = con.execute("""INSERT INTO procureflow.g2b_case_runs(
              bid_no,phase,state,started_at)
              VALUES(%s,%s,'running',now()) RETURNING id""",
              (bid_no, f"feature:{number:03}")).fetchone()["id"]
    state = "blocked"
    error = ""
    result: dict[str, Any] = {}
    try:
        context = notice_context(bid_no)
        # Collector preconditions are inherited solely from the selected
        # notice; never silently accept a user-supplied classification.
        if (action == "collect_exact_ten_digit_outcomes" and
                (not context["original_notice_verified"] or
                 SUB10 not in context["official_detail10"])):
            result = {"status": "blocked", "reason": "selected_notice_official_detail10_not_verified",
                      "configured_detail10_is_not_evidence": SUB10}
        elif action == "refresh_selected_official_notice":
            from g2b_full_runner import official_selected_notice
            result = official_selected_notice()
        elif action == "list_original_attachments":
            from g2b_documents import list_documents
            result = list_documents(bid_no, CASE_ORD)
        elif action == "download_original_attachments":
            from g2b_documents import acquire_one
            if "file_id" in args:
                result = acquire_one(bid_no, CASE_ORD, args["file_id"])
            else:
                from g2b_full_runner import documents_batch
                result = documents_batch()
        elif action == "extract_original_documents":
            from g2b_original_reparse import run
            result = run()
        elif action == "collect_exact_ten_digit_outcomes":
            from g2b_exact_outcome_history import run_batch
            result = run_batch(limit=args.get("candidate_limit", 4),
                               opening_limit=args.get("opening_limit", 2))
        elif action == "evaluate_company_eligibility":
            from g2b_bid_package import evaluate_eligibility
            result = evaluate_eligibility(bid_no)
        elif action == "evaluate_cost_or_proposal":
            if number <= 88:
                from g2b_case_engine import cost_summary
                result = cost_summary(bid_no)
            elif number <= 91:
                from g2b_bid_package import documented_price_scenarios
                result = documented_price_scenarios(bid_no)
            else:
                from g2b_bid_package import proposal_contents
                result = proposal_contents(bid_no)
        elif action == "evaluate_readiness":
            from g2b_case_engine import readiness_check
            result = readiness_check(bid_no)
        else:
            result = {"status": "blocked", "reason": "no_individual_collector_implemented",
                      "required_evidence": list(FEATURE_GATES[number])}
        detail = inspect_feature(bid_no, number)
        state = detail["acceptance_state"]
        if state != "verified" and (result.get("status") in ("error", "failed")):
            state = "error"
        elif state != "verified" and result.get("status") in ("blocked", "unknown", "not_ready"):
            state = "blocked"
        elif state != "verified" and action != "verify_stored_evidence":
            state = "partial" if result.get("status") not in ("blocked", "blocked_missing_official_api_key") else "blocked"
        payload = {
            "run_id": run_id, "source_bid_no": bid_no, "feature_no": number,
            "action": action, "state": state,
            "acceptance_state": detail["acceptance_state"],
            "missing_evidence": detail["missing_evidence"],
            "verified_evidence": detail["verified_evidence"],
            "collector_result": result,
            "observation": detail["observation"],
            "submitted": False, "bid_participation_clicked": False,
        }
    except Exception as exc:
        state = "error"
        error = type(exc).__name__ + ":" + str(exc)[:350]
        payload = {"run_id": run_id, "source_bid_no": bid_no, "feature_no": number,
                   "action": action, "state": "error", "error": error,
                   "submitted": False, "bid_participation_clicked": False}
    with session() as con:
        con.execute("""UPDATE procureflow.g2b_case_runs
                  SET state=%s,result=%s::jsonb,error=%s,finished_at=now()
                  WHERE id=%s""",
                    (state, json.dumps(payload, ensure_ascii=False, default=str)[:50000],
                     error, run_id))
        con.execute("""UPDATE procureflow.g2b_case_features
                  SET state=%s,note=%s,attempt=attempt+1,updated_at=now()
                  WHERE bid_no=%s AND feature_no=%s""",
                    ("verified" if payload.get("acceptance_state") == "verified" else state,
                     (error or ",".join(payload.get("missing_evidence", [])))[:250],
                     bid_no, number))
    return payload


def _make_routes(number: int) -> None:
    f = CATALOG[number]
    path = f"/{{bid_no}}/features/{number}"

    def get_one(bid_no: str):
        return inspect_feature(bid_no, number)

    def run_one(bid_no: str, request: FeatureRunRequest,
                authorization: str | None = Header(None)):
        from main import guard
        guard(authorization)
        return queue_one(bid_no, number, request)

    get_one.__name__ = f"g2b_feature_{number:03d}_inspect"
    run_one.__name__ = f"g2b_feature_{number:03d}_run"
    router.add_api_route(path, get_one, methods=["GET"],
                         summary=f"{number:03d} {f['label']} — 입력·결과·증빙",
                         description="Selected tender -> original facts -> evidence gates -> result.",
                         operation_id=f"g2b_feature_{number:03d}_inspect")
    router.add_api_route(path + "/run", run_one, methods=["POST"],
                         summary=f"{number:03d} {f['label']} — 독립 검사·실행",
                         description="mode=check evaluates evidence; mode=collect enqueues a safe, audited worker action. "
                                     "No bid participation, signing or submission.",
                         operation_id=f"g2b_feature_{number:03d}_run")


for _number in sorted(CATALOG):
    _make_routes(_number)
