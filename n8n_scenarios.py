"""Read-only, deterministic n8n demonstration contracts for ten fictional cases.

This is a *test fixture verifier*, not a general-purpose workflow engine:
n8n alone executes/links the workflow nodes. No job enqueue, G2B API,
production bid, DB write, or evidence mutation takes place here.
"""
from __future__ import annotations

from copy import deepcopy
from functools import lru_cache
import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/n8n", tags=["n8n scenario QA - no production writes"])
MANIFEST_PATH = Path(__file__).resolve().parent / "n8n" / "scenarios.json"
EXPECTED_IDS = {f"S{i:02}" for i in range(1, 11)}


@lru_cache(maxsize=1)
def read_manifest() -> dict:
    obj = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    scenarios = obj.get("scenarios", [])
    if {item["id"] for item in scenarios} != EXPECTED_IDS:
        raise RuntimeError("n8n scenario catalog must contain exactly S01-S10")
    for scenario in scenarios:
        if not scenario.get("steps"):
            raise RuntimeError(f"Empty n8n demo: {scenario['id']}")
    return obj


def get_scenario(scenario_id: str) -> dict:
    result = next((s for s in read_manifest()["scenarios"] if s["id"] == scenario_id), None)
    if result is None:
        raise HTTPException(404, "Unknown n8n demonstration scenario")
    return result


def determine_outcome(state: dict) -> tuple[str, list[str]]:
    """Scenario safety assertions only; not legal eligibility/production engine."""
    if state.get("qualified") is False:
        return "NO_BID", ["OUTSIDE_TARGET"]
    if state.get("eligibility") == "ineligible" or not state.get("deadline_open", True):
        return "NO_BID", ["MANDATORY_QUALIFICATION_OR_DEADLINE"]
    missing = []
    required = {
        "assigned": "NO_CASE",
        "official": "UNVERIFIED_ORIGINAL",
        "detail10": "UNVERIFIED_DETAIL10",
        "docs": "MISSING_DOCUMENTS",
        "history_verified": "HISTORY_NOT_FULLY_VERIFIED",
        "competitor": "COMPETITOR_ANALYSIS_MISSING",
        "price": "PRICE_UNVERIFIED",
        "package": "PACKAGE_INCOMPLETE",
        "audit": "AUDIT_NOT_CLEARED",
        "lease_valid": "WORKER_LEASE_INVALID",
    }
    for key, reason in required.items():
        if not state.get(key):
            missing.append(reason)
    if state.get("coverage_done") != state.get("coverage_total"):
        missing.append(f"HISTORY_{state.get('coverage_done', 0)}/{state.get('coverage_total', 121)}")
    if state.get("eligibility") != "eligible":
        missing.append("ELIGIBILITY_UNKNOWN")
    if state.get("quotes", 0) < state.get("quote_required", 2):
        missing.append("VALID_QUOTES_INSUFFICIENT")
    if state.get("critical_audit"):
        missing.append("CRITICAL_AUDIT_FINDING")
    if missing:
        return "HOLD", missing
    if not state.get("human"):
        return "REVIEW", ["HUMAN_APPROVAL_REQUIRED"]
    return "READY_FOR_MANUAL_PARTICIPATION", []


def run_simulation(scenario_id: str) -> dict:
    scenario = get_scenario(scenario_id)
    state = deepcopy(read_manifest()["base_state"])
    trace = []
    for step in scenario["steps"]:
        before = {key: deepcopy(state.get(key)) for key in step["patch"]}
        # No external calls: a step's output is exactly its fictional patch.
        state.update(deepcopy(step["patch"]))
        trace.append({
            "index": step["index"],
            "flow": step["flow"],
            "event": step["event"],
            "recipients": step.get("recipients", []),
            "input": before,
            "output": step["patch"],
            "after": {key: deepcopy(state.get(key)) for key in step["patch"]},
            "simulation_only": True,
        })
    verdict, missing = determine_outcome(state)
    expected = scenario["expected"]
    safety = (scenario_id != "S04" or
              (state["notice_version"] == 2 and
               state["stale_ignored"] >= 1 and not state["human"])) and (
              scenario_id != "S08" or
              (state["fenced"] and state["reconciled"] and state["lease_valid"])) and (
              scenario_id != "S09" or
              (state["critical_audit"] and not state["human"]))
    return {
        "scenario_id": scenario_id,
        "case_id": "DEMO_ONLY",
        "title": scenario["title"],
        "expected": expected,
        "verdict": verdict,
        "missing": missing,
        "passed": verdict == expected and safety,
        "safety_invariants_passed": safety,
        "state": state,
        "trace": trace,
        "processed_steps": len(trace),
        "simulation_only": True,
        "real_worker_called": False,
        "official_evidence_changed": False,
        "bid_submitted": False,
    }


class VerifyRequest(BaseModel):
    scenario_id: str
    case_id: str
    verdict: str
    state: dict[str, Any]
    trace: list[dict[str, Any]] = Field(max_length=60)
    simulation_only: bool = True
    bid_submitted: bool = False


@router.get("/scenarios", summary="List ten n8n-clickable dry-run demonstrations")
def list_n8n_scenarios():
    cases = read_manifest()["scenarios"]
    return {
        "total": 10, "test_only": True,
        "workflow_editor": "n8n (native UI, not React Flow)",
        "installed_on_live_n8n": "not_verified",
        "items": [
            {"id": s["id"], "title": s["title"], "expected": s["expected"],
             "steps": len(s["steps"]),
             "export_path": f"n8n/workflows/{s['id']}.json",
             "simulate_endpoint": f"/api/n8n/scenarios/{s['id']}/simulate"}
            for s in cases
        ],
    }


@router.get("/qa", summary="Recompute all ten purely fictional expected scenarios")
def check_all_n8n_scenarios():
    tests = [run_simulation(f"S{i:02}") for i in range(1, 11)]
    return {
        "total": len(tests), "passed": sum(x["passed"] for x in tests),
        "all_passed": all(x["passed"] for x in tests),
        "simulated_only": True,
        "actual_n8n_runs_verified": False,
        "actual_g2b_work_done": False,
        "results": [
            {"scenario_id": t["scenario_id"], "verdict": t["verdict"],
             "expected": t["expected"], "steps": t["processed_steps"],
             "passed": t["passed"]}
            for t in tests
        ],
    }


@router.get("/scenarios/{scenario_id}", summary="Inspect source scenario step inputs and expected outputs")
def n8n_scenario_definition(scenario_id: str):
    return {"test_only": True, "scenario": get_scenario(scenario_id)}


@router.get("/scenarios/{scenario_id}/simulate", summary="Run deterministic in-memory scenario verifier")
def n8n_scenario_simulate(scenario_id: str):
    return run_simulation(scenario_id)


@router.post("/scenarios/{scenario_id}/verify", summary="Verify a native n8n execution trace against immutable demo fixture")
def verify_n8n_execution(scenario_id: str, request: VerifyRequest):
    expected = run_simulation(scenario_id)
    if request.scenario_id != scenario_id or request.case_id != "DEMO_ONLY":
        raise HTTPException(422, "Scenario identity mismatch")
    if not request.simulation_only or request.bid_submitted:
        raise HTTPException(422, "Only safe fictional n8n traces can be submitted for verification")
    actual_steps = [{
        "index": row.get("index"), "flow": row.get("flow"),
        "event": row.get("event"), "recipients": row.get("recipients"),
        "input": row.get("input"), "output": row.get("output"),
        "after": row.get("after"), "simulation_only": row.get("simulation_only"),
    } for row in request.trace]
    if (request.verdict != expected["verdict"]
        or request.state != expected["state"]
        or actual_steps != expected["trace"]):
        raise HTTPException(409, {
            "passed": False, "reason": "actual_n8n_trace_does_not_match_expected_fixture",
            "expected_verdict": expected["verdict"],
            "expected_steps": expected["processed_steps"],
            "received_steps": len(request.trace),
        })
    return {
        "passed": True, "scenario_id": scenario_id,
        "verdict": expected["verdict"], "steps": len(actual_steps),
        "provenance": "fictional_n8n_demo",
        "verified_by": "deterministic_stateless_FastAPI_QA",
        "real_g2b_api_executed": False,
        "bid_submitted": False,
    }
