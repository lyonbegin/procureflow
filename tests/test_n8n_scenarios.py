"""Acceptance tests for 10 n8n-native scenario workflows and public read-only QA."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from n8n_scenarios import read_manifest, run_simulation, router

ROOT = Path(__file__).resolve().parents[1]
SCENARIOS = read_manifest()["scenarios"]
EXPECTED = {
    "S01": "READY_FOR_MANUAL_PARTICIPATION",
    "S02": "NO_BID", "S03": "HOLD", "S04": "HOLD",
    "S05": "HOLD", "S06": "NO_BID", "S07": "HOLD",
    "S08": "REVIEW", "S09": "HOLD", "S10": "HOLD",
}


def test_catalog_has_ten_original_business_cases():
    assert {row["id"]: row["expected"] for row in SCENARIOS} == EXPECTED
    assert all(row["steps"] for row in SCENARIOS)
    assert sum(len(row["steps"]) for row in SCENARIOS) >= 80


def test_qa_fails_closed_and_preserves_test_data_origin():
    for scenario_id, expected in EXPECTED.items():
        data = run_simulation(scenario_id)
        assert data["passed"], (scenario_id, data["missing"])
        assert data["verdict"] == expected
        assert data["processed_steps"] == len(data["trace"])
        assert not data["bid_submitted"]
        assert not data["real_worker_called"]
        assert not data["official_evidence_changed"]
        assert all(row["simulation_only"] for row in data["trace"])


def test_sensitive_fail_closed_behavior():
    stale = run_simulation("S04")
    assert stale["state"]["notice_version"] == 2
    assert stale["state"]["stale_ignored"] == 1
    assert stale["state"]["human"] is False
    assert stale["verdict"] == "HOLD"

    limits = run_simulation("S05")["state"]
    assert limits["coverage_done"] == 114
    assert limits["coverage_total"] == 121
    assert limits["rate_limit_429"] == 4 and limits["upstream_503"] == 3

    lease = run_simulation("S08")["state"]
    assert lease["fenced"] and lease["reconciled"] and lease["lease_valid"]

    audit = run_simulation("S09")["state"]
    assert audit["critical_audit"] and audit["human"] is False
    assert audit["price"] is False and audit["package"] is False

    resources = run_simulation("S10")["state"]
    assert resources["resource_deferred"] == ["B", "C"]


def test_each_file_is_a_real_n8n_workflow_with_manual_trigger_and_visible_per_step_nodes():
    for entry in SCENARIOS:
        wf = json.loads((ROOT/"n8n"/"workflows"/f"{entry['id']}.json").read_text())
        assert wf["active"] is False
        assert wf["name"].startswith("[테스트 "+entry["id"]+"]")
        assert len(wf["nodes"]) == len(entry["steps"]) + 5
        assert wf["nodes"][0]["type"] == "n8n-nodes-base.manualTrigger"
        assert wf["nodes"][1]["type"] == "n8n-nodes-base.code"
        assert all(n["type"] in (
            "n8n-nodes-base.manualTrigger",
            "n8n-nodes-base.code",
            "n8n-nodes-base.httpRequest",
        ) for n in wf["nodes"])
        assert wf["nodes"][-2]["type"] == "n8n-nodes-base.httpRequest"
        assert wf["nodes"][-2]["parameters"]["url"].endswith(f"/{entry['id']}/verify")
        assert sum(n["type"] == "n8n-nodes-base.code" for n in wf["nodes"]) >= len(entry["steps"]) + 2
        assert len(wf["connections"]) == len(wf["nodes"])-1
        assert all(node["name"] != "Execute Bid" for node in wf["nodes"])
        assert "n8n-nodes-base.webhook" not in str(wf)
        assert "R26BK01787028" not in str(wf)  # no production tender in demo JSON


def test_one_to_one_flow_names_and_last_node_connections():
    for entry in SCENARIOS:
        wf = json.loads((ROOT/"n8n"/"workflows"/f"{entry['id']}.json").read_text())
        names = [n["name"] for n in wf["nodes"]]
        assert len(set(names)) == len(names)
        traversed = [names[0]]
        while traversed[-1] in wf["connections"]:
            target = wf["connections"][traversed[-1]]["main"][0][0]["node"]
            assert target not in traversed
            traversed.append(target)
        assert traversed == names


def test_public_stateless_endpoint_and_tamper_rejection():
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    catalog = client.get("/api/n8n/scenarios").json()
    assert catalog["total"] == 10
    qa = client.get("/api/n8n/qa").json()
    assert qa["total"] == 10 and qa["passed"] == 10 and qa["all_passed"]
    assert not qa["actual_n8n_runs_verified"]

    for sid in EXPECTED:
        result = client.get(f"/api/n8n/scenarios/{sid}/simulate").json()
        payload = {field: result[field] for field in (
            "scenario_id", "case_id", "verdict", "state", "trace", "simulation_only", "bid_submitted"
        )}
        ok = client.post(f"/api/n8n/scenarios/{sid}/verify", json=payload)
        assert ok.status_code == 200, (sid, ok.text)
        assert ok.json()["passed"]
        payload["trace"][0]["event"] = "FORGED"
        blocked = client.post(f"/api/n8n/scenarios/{sid}/verify", json=payload)
        assert blocked.status_code == 409
    assert client.get("/api/n8n/scenarios/S99/simulate").status_code == 404


def test_n8n_code_nodes_execute_individually_in_nodejs():
    """Actual JS from exported Code nodes, executed with n8n's $input shape."""
    check = ROOT/"scripts"/"qa_n8n_code_nodes.cjs"
    result = subprocess.run(["node", str(check)], cwd=ROOT,
                            capture_output=True, text=True, timeout=25)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "N8N_NATIVE_NODE_JS_10_SCENARIOS_PASSED" in result.stdout
