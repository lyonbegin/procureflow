"""Tests for 15 native n8n operational workflows and their real-data contracts.

No fake PASS for official G2B evidence: all missing gates block PF readiness.
"""
import json
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from n8n_operational import manifest, inspect_flow, _materialized, router

ROOT=Path(__file__).resolve().parents[1]
CONTEXT={"bid_no":"R26BK01787028","bid_ord":"000",
         "original_notice_verified":True,"official_detail10":["8111159901"]}
SNAPSHOT={"verified_evidence_types":[],"feature_acceptance":[
    {"number":i,"acceptance_state":"missing"} for i in range(1,105)]}


def test_all_15_flows_and_43_distinct_blocks_cover_exactly_104_functions():
    data=manifest()
    assert len(data["flows"])==15
    assert len(data["blocks"])==43
    nums=sorted(x for b in data["blocks"] for x in b["features"])
    assert nums==list(range(1,105))
    assert len({b["id"] for b in data["blocks"]})==43
    assert all(f["mode"]=="business_evidence_read_only_by_default" for f in data["flows"])
    assert all(f["never_submit_bid"] for f in data["flows"])


def test_missing_official_evidence_never_marked_completed():
    data=manifest()
    for flow in data["flows"]:
        result=_materialized(flow,CONTEXT,SNAPSHOT)
        assert result["flow_id"]==flow["id"]
        assert result["business_state"]=="BLOCKED_OR_PENDING"
        assert result["actual_job_executed"] is False
        assert result["read_only"] is True
        assert result["simulation_only"] is False
        assert result["automatic_bid_submission"] is False
        assert result["nodes"]==len(flow["business_features"])
        assert all(block["status"]=="blocked" for block in result["blocks"])
        for block in result["blocks"]:
            assert all(f["missing_gates"] for f in block["features"])


def test_native_flow_exports_are_manual_trigger_native_http_and_not_react_dag():
    data=manifest()
    for flow in data["flows"]:
        src=ROOT/"n8n"/"operational"/(flow["id"]+".json")
        wf=json.loads(src.read_text(encoding="utf-8"))
        assert wf["active"] is False
        assert wf["id"]==f"PFOP2026{flow['id']}WF"
        assert wf["nodes"][0]["type"]=="n8n-nodes-base.manualTrigger"
        assert wf["nodes"][2]["type"]=="n8n-nodes-base.httpRequest"
        assert "/api/n8n/operational/flows/"+flow["id"]+"/inspect?" in wf["nodes"][2]["parameters"]["url"]
        assert len(wf["nodes"])==len(flow["owned_blocks"])+13
        assert len(wf["connections"])==len(wf["nodes"])-2
        names=[n["name"] for n in wf["nodes"]]
        assert len(names)==len(set(names))
        assert all(x["type"] in (
            "n8n-nodes-base.code","n8n-nodes-base.manualTrigger",
            "n8n-nodes-base.httpRequest","n8n-nodes-base.if",
            "n8n-nodes-base.wait") for x in wf["nodes"])
        for block_id in flow["owned_blocks"]:
            assert any(n["name"].startswith(block_id+" · ") for n in wf["nodes"])
        assert "R26BK01787028" in wf["nodes"][1]["parameters"]["jsCode"]
        assert not any(n["type"].endswith("webhook") for n in wf["nodes"])
        assert sum(n["type"] == "n8n-nodes-base.httpRequest" and n["parameters"].get("genericAuthType") == "httpHeaderAuth" for n in wf["nodes"]) == 2
        assert all("adminToken" not in json.dumps(n["parameters"]) for n in wf["nodes"])
        assert 'mode:"inspect"' in wf["nodes"][1]["parameters"]["jsCode"]
        branches=wf["connections"]["실제 Worker Job 실행 여부"]["main"]
        assert branches[0][0]["node"]=="관리자 인증 · 실제 Worker Job 등록"
        assert branches[1][0]["node"]=="조회 결과 종료 · 실제 Job 미실행"
        assert wf["nodes"][-7]["type"]=="n8n-nodes-base.code"



def test_readonly_operational_api_and_auth_before_actual_worker_job():
    app=FastAPI();app.include_router(router)
    client=TestClient(app)
    result=client.get("/api/n8n/operational/flows").json()
    assert result["total_flows"]==15
    assert result["total_blocks"]==43
    assert result["total_features"]==104
    with patch("n8n_operational.notice_context",return_value=CONTEXT),patch(
        "g2b_case_engine.dashboard",return_value=SNAPSHOT
    ):
        pf=client.get("/api/n8n/operational/flows/PF05/inspect")
        assert pf.status_code==200
        assert pf.json()["blocks_total"]==8
        assert pf.json()["business_state"]=="BLOCKED_OR_PENDING"
        wrong=client.get("/api/n8n/operational/flows/PF05/inspect?bid_no=R26BK99999999")
        assert wrong.status_code==422
        block=client.get("/api/n8n/operational/flows/PF05/blocks/H07/inspect")
        assert block.status_code==200
        assert set(x["feature_no"] for x in block.json()["block"]["features"])=={46,50,54}
        missing=client.get("/api/n8n/operational/flows/PF05/blocks/N05/inspect")
        assert missing.status_code==404
    guarded=client.post("/api/n8n/operational/flows/PF05/execute-feature",
        json={"bid_no":"R26BK01787028","feature_no":50,"mode":"collect"})
    assert guarded.status_code in (401,503)
    assert client.post("/api/n8n/operational/flows/PF05/execute-feature",
        json={"bid_no":"R26BK01787028","feature_no":1,"mode":"collect"}).status_code in (401,503)
    assert client.get("/api/n8n/operational/flows/PF16/inspect").status_code==404


def test_selected_notice_never_replaced_by_client():
    app=FastAPI();app.include_router(router)
    client=TestClient(app)
    assert client.get("/api/n8n/operational/flows/PF01/inspect?bid_no=changed").status_code==422
