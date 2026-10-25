from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from n8n_native_probe import inspect_native_n8n, router


def test_disconnected_is_truthful(monkeypatch):
    monkeypatch.delenv("N8N_ADMIN_API_URL",raising=False)
    monkeypatch.delenv("N8N_ADMIN_API_KEY",raising=False)
    status=inspect_native_n8n()
    assert status["connected"] is False
    assert status["native_successful_scenarios"] == 0
    assert status["all_ten_native_executions_verified"] is False
    app=FastAPI();app.include_router(router)
    assert TestClient(app).get("/api/n8n/native/status").json()==status


def test_actual_execution_counts_are_not_assumed(monkeypatch):
    monkeypatch.setenv("N8N_ADMIN_API_URL","https://n8n.example")
    monkeypatch.setenv("N8N_ADMIN_API_KEY","ci-key-not-real")
    fake_workflows={"data":[{"id":f"wf-{i}","name":f"[테스트 S{i:02}] case"} for i in range(1,11)]}
    fake_executions={"data":[
        {"workflowId":f"wf-{i}","status":"success"} for i in range(1,6)
    ]+[{"workflowId":"wf-6","status":"error"}]}
    def fake(path,base,key):
        assert base=="https://n8n.example" and key=="ci-key-not-real"
        return fake_workflows if "/workflows?" in path else fake_executions
    with patch("n8n_native_probe._remote_json",side_effect=fake):
        state=inspect_native_n8n()
    assert state["connected"]
    assert state["imported_scenarios"]==10
    assert state["native_successful_scenarios"]==5
    assert not state["all_ten_native_executions_verified"]


def test_ten_real_successes_are_required(monkeypatch):
    monkeypatch.setenv("N8N_ADMIN_API_URL","https://n8n.example")
    monkeypatch.setenv("N8N_ADMIN_API_KEY","token")
    workflows={"data":[{"id":f"work-{i}","name":f"[테스트 S{i:02}] case"} for i in range(1,11)]}
    executions={"data":[{"workflowId":f"work-{i}","status":"success"} for i in range(1,11)]}
    with patch("n8n_native_probe._remote_json",side_effect=[workflows,executions]):
        state=inspect_native_n8n()
    assert state["all_ten_native_executions_verified"]
    assert state["native_successful_scenarios"]==10
    assert state["actual_g2b_work_verified"] is False


def test_credentials_and_internal_url_never_leak(monkeypatch):
    monkeypatch.setenv("N8N_ADMIN_API_URL","https://private-n8n.example")
    monkeypatch.setenv("N8N_ADMIN_API_KEY","very-sensitive-token")
    with patch("n8n_native_probe._remote_json",side_effect=OSError("secret-host")):
        state=inspect_native_n8n()
    assert state["reason"]=="n8n_api_unreachable_or_unauthorized"
    assert "very-sensitive-token" not in str(state)
    assert "private-n8n.example" not in str(state)
    assert "secret-host" not in str(state)
