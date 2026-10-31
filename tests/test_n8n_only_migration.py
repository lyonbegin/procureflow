"""Regression gates: no second workflow editor/engine after n8n migration."""
from pathlib import Path
from fastapi.testclient import TestClient
from main import app
from n8n_landing import scenario_editor_url, editor_base

ROOT=Path(__file__).resolve().parents[1]


def test_old_python_dag_and_react_frontend_were_really_removed():
    for filename in ("g2b_dag_api.py","g2b_dag_core.py","g2b_workflow_ops.py",
                     "frontend/src/App.jsx","frontend/src/FlowWorkspace.jsx",
                     "frontend/src/DAGEditor.jsx"):
        assert not (ROOT / filename).exists(), filename
    assert not (ROOT / "frontend").exists(), "Frontend build must be gone"
    dockerfile=(ROOT / "Dockerfile").read_text()
    assert "studio-build" not in dockerfile
    assert "COPY frontend" not in dockerfile
    assert "node:" not in dockerfile


def test_root_is_not_an_unapproved_react_flow_editor():
    client=TestClient(app)
    response=client.get("/")
    assert response.status_code==200
    assert "n8n 단일 워크플로" in response.text
    assert "React Flow나 자체 DAG" in response.text
    assert "10개 운영 시나리오" in response.text
    assert "/api/n8n/scenarios/S01/simulate" in response.text
    assert client.get("/flow").status_code==200


def test_retired_dag_api_and_vite_bundle_not_served():
    routes={r.path for r in app.routes}
    assert "/api/g2b/cases/{bid_no}/workflow/designs" not in routes
    assert "/api/g2b/cases/{bid_no}/workflow/debug-runs/{run_id}/actions" not in routes
    assert "/api/g2b/cases/{bid_no}/workflow/advance" not in routes
    assert not any(path.startswith("/studio") for path in routes)
    assert "/api/g2b/cases/{bid_no}/features" in routes
    assert "/api/n8n/scenarios" in routes
    assert "/api/n8n/scenarios/{scenario_id}/verify" in routes


def test_native_n8n_editor_url_only_after_configuration(monkeypatch):
    monkeypatch.delenv("N8N_EDITOR_URL",raising=False)
    assert editor_base()==""
    assert scenario_editor_url("S01")==""
    monkeypatch.setenv("N8N_EDITOR_URL","https://n8n.internal.example")
    assert scenario_editor_url("S01")=="https://n8n.internal.example/workflow/PFDEMO2026S01WF"
    assert scenario_editor_url("S10").endswith("/workflow/PFDEMO2026S10WF")
    assert scenario_editor_url("S00")==""
    assert scenario_editor_url("S99")==""
    monkeypatch.setenv("N8N_EDITOR_URL","javascript:alert(1)")
    assert editor_base()==""


def test_official_shared_n8n_is_only_editor_and_requires_verified_rollout(monkeypatch):
    from n8n_landing import official_workflow_url, shared_editor_ready
    client = TestClient(app)
    monkeypatch.setenv("N8N_EDITOR_URL", "https://n8n.internal.example")
    monkeypatch.delenv("N8N_SHARED_EDITOR_VERIFIED", raising=False)
    assert not shared_editor_ready()
    assert client.get("/editor").status_code == 503
    assert client.get("/editor/workflow/PFOP2026PF05WF").status_code == 503
    assert client.get("/n8n/native-preview").status_code == 503
    assert not official_workflow_url("PFOP2026PF05WF")

    monkeypatch.setenv("N8N_SHARED_EDITOR_VERIFIED", "1")
    assert shared_editor_ready()
    assert official_workflow_url("PFORCH2026MAINWF").endswith("/workflow/PFORCH2026MAINWF")
    assert official_workflow_url("PFOP2026PF05WF").endswith("/workflow/PFOP2026PF05WF")
    assert official_workflow_url("PFDEMO2026S10WF").endswith("/workflow/PFDEMO2026S10WF")
    for invalid in ["PFOP2026PF99WF", "PFDEMO2026S11WF", "//attacker.example", "../setup", ""]:
        assert not official_workflow_url(invalid)
        assert client.get("/editor/workflow/" + invalid.replace("/", "%2F"), follow_redirects=False).status_code in (404, 405)
    res = client.get("/flow", follow_redirects=False)
    assert res.status_code == 307 and res.headers["location"] == "https://n8n.internal.example"
    res = client.get("/editor/workflow/PFOP2026PF05WF", follow_redirects=False)
    assert res.status_code == 307 and res.headers["location"].endswith("/workflow/PFOP2026PF05WF")
    res = client.get("/n8n/native-preview", follow_redirects=False)
    assert res.status_code == 307 and res.headers["location"] == "https://n8n.internal.example"

