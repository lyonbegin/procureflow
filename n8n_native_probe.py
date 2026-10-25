"""Server-side, read-only n8n API probe for genuine native executions.

Never accepts a user URL. Credentials are read only from server env and are
not returned or logged. This is separate from /api/n8n/qa, which validates
fictional deterministic scenarios without running n8n.
"""
from __future__ import annotations
import json
import os
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from fastapi import APIRouter

router = APIRouter(prefix="/api/n8n", tags=["n8n true execution status"])
EXPECTED = {f"S{i:02}" for i in range(1,11)}
OPERATIONAL = {f"PF{i:02}" for i in range(1,16)}


def _remote_json(endpoint: str, base: str, key: str) -> dict:
    request = Request(base.rstrip("/") + endpoint,
                      headers={"X-N8N-API-KEY":key,"Accept":"application/json",
                               "User-Agent":"ProcureFlow-server-native-execution-check/1.0"})
    with urlopen(request, timeout=7) as response:
        if response.status != 200:
            raise ValueError("unexpected-n8n-status")
        return json.loads(response.read(500_000).decode("utf-8"))


def inspect_native_n8n() -> dict:
    base = os.getenv("N8N_ADMIN_API_URL","").strip().rstrip("/")
    key = os.getenv("N8N_ADMIN_API_KEY","").strip()
    fallback = {
        "connected":False, "n8n_editor_available":False,
        "imported_scenarios":0, "native_successful_scenarios":0,
        "imported_operational_flows":0, "native_successful_operational_flows":0,
        "all_fifteen_operational_native_executions_verified":False,
        "all_ten_native_executions_verified":False,
        "source":"n8n_native_admin_api_not_stateless_simulator",
        "reason":"n8n_admin_api_not_configured",
    }
    parsed = urlparse(base)
    if (not base or not key or parsed.scheme not in ("https","http")
            or not parsed.netloc or parsed.username or parsed.password):
        return fallback
    try:
        workflows = _remote_json("/api/v1/workflows?limit=100",base,key)
        executions = _remote_json("/api/v1/executions?limit=100",base,key)
    except (HTTPError,URLError,TimeoutError,OSError,ValueError,KeyError,
            json.JSONDecodeError):
        return {**fallback, "reason":"n8n_api_unreachable_or_unauthorized"}
    if not isinstance(workflows.get("data"),list) or not isinstance(executions.get("data"),list):
        return {**fallback,"reason":"invalid_n8n_api_schema"}
    found = {}
    for workflow in workflows["data"]:
        name=workflow.get("name","")
        if not isinstance(name,str):
            continue
        for sid in EXPECTED:
            if name.startswith(f"[테스트 {sid}]"):
                found[sid]=workflow.get("id")
    operational={}
    for workflow in workflows["data"]:
        name=workflow.get("name","")
        if isinstance(name,str):
            for pf in OPERATIONAL:
                if name.startswith(f"[운영 {pf}]"):
                    operational[pf]=workflow.get("id")
    success=set()
    operational_success=set()
    for execution in executions["data"]:
        if execution.get("status") != "success":
            continue
        for sid,workflow_id in found.items():
            if workflow_id is not None and str(execution.get("workflowId"))==str(workflow_id):
                success.add(sid)
        for pf,workflow_id in operational.items():
            if workflow_id is not None and str(execution.get("workflowId"))==str(workflow_id):
                operational_success.add(pf)
    imported=sorted(found)
    verified=sorted(success)
    return {
        "connected":True, "n8n_editor_available":True,
        "imported_scenarios":len(imported),
        "imported_ids":imported,
        "native_successful_scenarios":len(verified),
        "native_successful_ids":verified,
        "all_ten_native_executions_verified":len(verified)==10,
        "imported_operational_flows":len(operational),
        "operational_imported_ids":sorted(operational),
        "native_successful_operational_flows":len(operational_success),
        "native_successful_operational_ids":sorted(operational_success),
        "all_fifteen_operational_native_executions_verified":len(operational_success)==15,
        "source":"n8n_native_admin_api_not_stateless_simulator",
        "reason":"ok",
        "actual_g2b_work_verified":False,
        "bid_submitted":False,
    }


@router.get("/native/status", summary="Actual n8n workflow import & execution audit; not the in-memory demo")
def native_execution_status():
    return inspect_native_n8n()
