"""n8n-only operational contract: 15 flows, 43 blocks, 104 distinct functions.

This module only reads the ACTUAL G2B PostgreSQL evidence for native n8n
business-node input/output. It is not a DAG interpreter or independent
workflow runner. Native n8n is solely responsible for workflow routing.

Writes are forbidden on every GET; explicit POST uses the existing authenticated
individual G2B feature worker queue. No bid submission.
"""
from __future__ import annotations

from functools import lru_cache
import json
from pathlib import Path

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field

from g2b_case_10y import CASE_BID
from g2b_feature_registry import FEATURE_GATES, FEATURES
from g2b_feature_api import FeatureRunRequest, feature_contract, notice_context, queue_one

router = APIRouter(prefix="/api/n8n/operational", tags=["n8n native 15 PF operations"])
PATH = Path(__file__).parent / "n8n" / "operational_manifest.json"
VALID_PF = {f"PF{i:02}" for i in range(1, 16)}


@lru_cache(maxsize=1)
def manifest() -> dict:
    data = json.loads(PATH.read_text(encoding="utf-8"))
    flows = data["flows"]
    blocks = data["blocks"]
    if {x["id"] for x in flows} != VALID_PF or len(blocks) != 43:
        raise RuntimeError("Invalid 15-flow/43-block manifest")
    from_manifest = [n for b in blocks for n in b["features"]]
    if sorted(from_manifest) != list(range(1, 105)):
        raise RuntimeError("Each registered G2B function must be owned exactly once")
    if {n for f in flows for n in f["business_features"]} != set(range(1, 105)):
        raise RuntimeError("Every G2B function must belong to a PF flow")
    for f in flows:
        assert set(f["business_features"]) == {
            n for b in blocks if b["id"] in f["owned_blocks"] for n in b["features"]
        }
    return data


def _get_flow(flow_id: str) -> dict:
    f = next((x for x in manifest()["flows"] if x["id"] == flow_id), None)
    if not f:
        raise HTTPException(404, "Unknown PF flow")
    return f


def _selected_case(bid_no: str) -> None:
    if bid_no != CASE_BID:
        raise HTTPException(422, "This source collector only supports the selected official G2B case; multi-case support is not implemented")


def _materialized(flow: dict, context: dict, snapshot: dict) -> dict:
    accepted = set(snapshot.get("verified_evidence_types") or ())
    feature_map = {f["number"]: f for f in FEATURES}
    gates_by_number = {
        no: list(FEATURE_GATES[no]) for no in flow["business_features"]
    }
    feature_states = {r["number"]: r.get("acceptance_state", "missing")
                      for r in snapshot.get("feature_acceptance", [])}
    blocks = []
    for block_id in flow["owned_blocks"]:
        definition = next(b for b in manifest()["blocks"] if b["id"] == block_id)
        steps = []
        missing = set()
        for number in definition["features"]:
            gates = gates_by_number[number]
            absent = [g for g in gates if g not in accepted]
            missing.update(absent)
            steps.append({
                "feature_no":number,
                "label":feature_map[number]["label"],
                "acceptance":feature_states.get(number, "missing"),
                "verified_gates":[g for g in gates if g in accepted],
                "missing_gates":absent,
                "input_contract": {
                    "official_bid_no":context["bid_no"],
                    "official_bid_ord":context["bid_ord"],
                    "required_evidence":gates,
                },
                "inspect_endpoint": f"/api/g2b/cases/{context['bid_no']}/features/{number}",
                "execute_endpoint": f"/api/g2b/cases/{context['bid_no']}/features/{number}/run",
            })
        verdict = ("verified" if steps and all(s["acceptance"] == "verified" and
                   not s["missing_gates"] for s in steps) else "blocked")
        blocks.append({
            "id":block_id,
            "name":definition["label"],
            "input":definition["input"],
            "output":definition["output"],
            "output_value": {
                "evidence_verified":verdict == "verified",
                "verified_evidence_keys": sorted({
                    g for step in steps for g in step["verified_gates"]
                }),
                "missing_evidence_keys":sorted(missing),
                "real_api_result_state":verdict,
                "artifact_references_available": bool(accepted),
            },
            "next_blocks":definition["to"],
            "status":verdict,
            "features":steps,
            "real_data":True,
            "simulation_only":False,
            "job_enqueued":False,
        })
    # No PF flow can be declared complete from an API route existing alone.
    complete = bool(blocks) and all(b["status"] == "verified" for b in blocks)
    if not context.get("original_notice_verified"):
        complete = False
    if flow["id"] in ("PF05", "PF06"):
        if not context.get("official_detail10"):
            complete = False
        if "outcome_10years_complete" not in accepted:
            complete = False
    return {
        "flow_id":flow["id"], "flow_name":flow["label"],
        "case_id":context["bid_no"],"bid_ord":context["bid_ord"],
        "official_notice_verified":bool(context["original_notice_verified"]),
        "official_detail10":context.get("official_detail10") or [],
        "source_provenance":"live_procureflow_postgresql_verified_evidence",
        "blocks":blocks,
        "nodes":sum(len(x["features"]) for x in blocks),
        "blocks_total":len(blocks),
        "blocks_verified":sum(b["status"]=="verified" for b in blocks),
        "business_state":"VERIFIED" if complete else "BLOCKED_OR_PENDING",
        "pending_missing_evidence":sorted({
            key for b in blocks for key in b["output_value"]["missing_evidence_keys"]
        }),
        "downstream_flows":flow["next"],
        "output_event":flow["event"],
        "workflow_execution_engine":"native_n8n_only",
        "simulation_only":False,
        "read_only":True,
        "actual_job_executed":False,
        "automatic_bid_submission":False,
        "caution":"Node API observation is not job execution; gaps remain blocked until official evidence accepted.",
    }


def inspect_flow(flow_id: str, bid_no: str = CASE_BID) -> dict:
    f = _get_flow(flow_id)
    _selected_case(bid_no)
    context = notice_context(bid_no)
    from g2b_case_engine import dashboard
    snap = dashboard(bid_no, 15, refresh=False)
    return _materialized(f, context, snap)


@router.get("/manifest")
def api_operation_manifest():
    return manifest()


@router.get("/flows")
def api_all_operational_flows():
    data = manifest()
    return {
        "engine":"n8n_only",
        "total_flows":len(data["flows"]),
        "total_blocks":len(data["blocks"]),
        "total_features":sum(len(b["features"]) for b in data["blocks"]),
        "selected_case_only":True,
        "workflow_files":[
            {"id":f["id"],"label":f["label"],"filename":f"n8n/operational/{f['id']}.json",
             "features":len(f["business_features"]),"owned_blocks":f["owned_blocks"]}
            for f in data["flows"]
        ],
    }


@router.get("/flows/{flow_id}/inspect")
def api_inspect_flow(flow_id: str, bid_no: str = Query(CASE_BID)):
    return inspect_flow(flow_id,bid_no)


@router.get("/flows/{flow_id}/blocks/{block_id}/inspect")
def api_inspect_block(flow_id: str, block_id: str, bid_no: str = Query(CASE_BID)):
    result = inspect_flow(flow_id,bid_no)
    block = next((x for x in result["blocks"] if x["id"] == block_id), None)
    if not block:
        raise HTTPException(404,"Block does not belong to this n8n flow")
    return {
        "flow_id":flow_id,"bid_no":bid_no,"block":block,
        "source":"actual_G2B_business_evidence","no_work_started":True,
    }


class ExecuteIndividualFeature(BaseModel):
    bid_no: str = Field(min_length=1, max_length=70)
    feature_no: int = Field(ge=1, le=104)
    mode: str = "check"
    parameters: dict = Field(default_factory=dict)


@router.post("/flows/{flow_id}/execute-feature")
def api_execute_feature(flow_id: str, request: ExecuteIndividualFeature,
                        authorization: str | None = Header(None)):
    # Unlike scenario fixtures and the read-only inspector, this endpoint
    # creates an actual DB job when mode=collect. It is always authenticated.
    from main import guard
    guard(authorization)
    flow = _get_flow(flow_id)
    _selected_case(request.bid_no)
    if request.feature_no not in flow["business_features"]:
        raise HTTPException(422, "Function belongs to another PF flow")
    if request.mode not in ("check", "collect"):
        raise HTTPException(422, "mode must be check or collect")
    return {
        "flow_id":flow_id,
        **queue_one(request.bid_no,request.feature_no,
                    FeatureRunRequest(mode=request.mode, parameters=request.parameters)),
        "automatic_bid_submission":False,
        "runner":"original_railway_G2B_business_worker",
    }
