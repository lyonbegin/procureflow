"""Actual n8n-to-G2B Worker API: authorization, idempotency, true evidence gates."""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from g2b_case_10y import CASE_BID
from n8n_job_bridge import compute_next_action, progress_snapshot, router

NOW=datetime(2026,10,25,4,0,tzinfo=timezone.utc)
CONTEXT={"bid_no":CASE_BID,"bid_ord":"000",
         "original_notice_verified":True,"official_detail10":["8111159901"]}
MISSING={"flow_id":"PF05","business_state":"BLOCKED_OR_PENDING",
         "blocks":[{"id":"H01","features":[
            {"feature_no":49,"acceptance":"missing","missing_gates":["classification_verified"]},
            {"feature_no":53,"acceptance":"missing","missing_gates":["outcome_window_register"]},
            {"feature_no":50,"acceptance":"missing","missing_gates":["outcome_10years_complete"]}]}]}


def policy(fid="PF05",ctx=None,jobs=None,obs=None):
    return compute_next_action(fid,CASE_BID,obs or MISSING,ctx or CONTEXT,jobs or [],NOW)


def test_exact_code_missing_blocks_historical_run_without_fabricating_acceptance():
    response=policy(ctx={**CONTEXT,"official_detail10":[]})
    assert response["status"]=="BLOCKED_OR_COMPLETE"
    assert response["candidate"] is None
    assert response["blocked"][0]["reason"]=="official_selected_10_digit_code_missing"
    assert response["business_state"]=="BLOCKED_OR_PENDING"
    assert response["bid_submitted"] is False


def test_real_supported_collector_plan_is_bounded_and_has_explicit_gaps():
    response=policy()
    assert response["status"]=="ACTIONABLE"
    assert response["candidate"]["feature_no"]==49
    assert response["candidate"]["resource"]=="collect_exact_ten_digit_outcomes"
    assert response["candidate"]["missing_evidence"]==["classification_verified"]
    assert response["active_jobs"]==0
    assert response["resource_limit"]==3
    # Three PF05 feature numbers share exactly one expensive history collector.
    assert response["other_candidates"]==[]


def test_queued_shared_collector_is_not_started_twice():
    busy=[{"state":"running","config":{"feature_no":50},"created_at":NOW}]
    response=policy(jobs=busy)
    assert response["status"]=="BLOCKED_OR_COMPLETE"
    assert response["candidate"] is None
    assert response["blocked"][0]["reason"]=="collector_job_already_queued_or_running"


def test_recent_failed_job_is_cooled_down_and_is_not_claimed_completed():
    recent=[{"state":"failed","config":{"feature_no":51},
             "created_at":NOW-timedelta(minutes=10)}]
    response=policy(jobs=recent)
    assert response["candidate"] is None
    assert response["blocked"][0]["reason"]=="collector_cooldown"
    expired=[{**recent[0],"created_at":NOW-timedelta(minutes=50)}]
    assert policy(jobs=expired)["status"]=="ACTIONABLE"


def test_capacity_hard_limit_across_independent_collectors():
    queue=[{"state":"queued","config":{"feature_no":n},"created_at":NOW}
           for n in (1,29,66)]
    x=policy(jobs=queue)
    assert x["status"]=="WAIT_CAPACITY"
    assert x["candidate"] is None
    assert x["active_jobs"]==3


def test_only_notice_refresh_allowed_when_original_not_verified():
    unverified={**CONTEXT,"original_notice_verified":False,"official_detail10":[]}
    assert policy(ctx=unverified)["candidate"] is None
    notice={"flow_id":"PF01","business_state":"BLOCKED_OR_PENDING","blocks":[
        {"features":[{"feature_no":1,"acceptance":"missing","missing_gates":["notice_official"]}]}]}
    first=policy("PF01",unverified,[],notice)
    assert first["status"]=="ACTIONABLE"
    assert first["candidate"]["resource"]=="refresh_selected_official_notice"


def test_final_review_cannot_queue_jobs_even_if_feature_gates_missing():
    assert policy("PF12")["status"]=="MANUAL_ONLY"
    assert policy("PF14")["status"]=="MANUAL_ONLY"
    assert policy("PF15")["status"]=="MANUAL_ONLY"


def test_verified_feature_is_skipped():
    verified={"flow_id":"PF05","business_state":"VERIFIED","blocks":[
        {"features":[{"feature_no":49,"acceptance":"verified","missing_gates":[]}]}]}
    x=policy(obs=verified)
    assert x["candidate"] is None


def test_wrong_case_and_outside_flow_fail_closed():
    app=FastAPI();app.include_router(router)
    c=TestClient(app)
    assert c.get("/api/n8n/operational/flows/PF05/next-action?bid_no=FAKE").status_code==422
    assert c.get("/api/n8n/operational/flows/PF99/next-action").status_code==404
    payload={"bid_no":CASE_BID,"feature_no":49,"request_key":"request-123456789"}
    unauthorized=c.post("/api/n8n/operational/flows/PF05/dispatch",json=payload)
    assert unauthorized.status_code in (401,503)
    assert c.get("/api/n8n/operational/flows/PF05/jobs/1234").status_code in (401,503)
    assert c.get("/api/n8n/operational/flows/PF05/dispatch-history").status_code in (401,503)


class Row:
    def __init__(self,record):self.record=record
    def fetchone(self):return self.record


class FakeDB:
    def __init__(self):self.saved={};self.jobs=[]
    def execute(self,sql,params=None):
        key=(CASE_BID,"PF05","idempotency-key-001")
        if "INSERT INTO procureflow.n8n_feature_dispatch" in sql:
            request=(params[0],params[1],params[2])
            if request in self.saved:return Row(None)
            self.saved[request]={"feature_no":params[3],"job_id":None,"state":"reserved","error":""}
            return Row({"request_key":params[2]})
        if "SELECT feature_no,job_id,state,error" in sql:
            return Row(self.saved.get(tuple(params)))
        if "UPDATE procureflow.n8n_feature_dispatch" in sql:
            if "SET job_id=" in sql:
                self.saved[(params[1],params[2],params[3])].update(job_id=params[0],state="queued")
            else:self.saved[(params[1],params[2],params[3])].update(state="rejected",error=params[0])
            return Row(None)
        raise AssertionError("Unexpected SQL: "+sql[:100])


def test_exactly_once_real_job_dispatch_and_replay():
    db=FakeDB()
    @contextmanager
    def db_session():yield db
    payload={"bid_no":CASE_BID,"feature_no":49,"request_key":"idempotency-key-001"}
    app=FastAPI();app.include_router(router)
    c=TestClient(app)
    calls=[]
    def real_queue(bid_no,number,request):
        calls.append((bid_no,number,request.mode))
        return {"job_id":991,"job_status":"queued"}
    with patch("main.guard",return_value=None),patch("n8n_job_bridge.session",db_session),\
         patch("n8n_job_bridge.ensure_dispatch_schema",return_value=None),\
         patch("n8n_job_bridge.notice_context",return_value=CONTEXT),\
         patch("n8n_job_bridge.inspect_flow",return_value=MISSING),\
         patch("n8n_job_bridge._recent_jobs",return_value=[]),\
         patch("n8n_job_bridge.queue_one",side_effect=real_queue):
        first=c.post("/api/n8n/operational/flows/PF05/dispatch",json=payload)
        assert first.status_code==200,first.text
        assert first.json()["job_id"]==991
        assert first.json()["deduplicated"] is False
        replay=c.post("/api/n8n/operational/flows/PF05/dispatch",json=payload)
        assert replay.status_code==200
        assert replay.json()["job_id"]==991
        assert replay.json()["deduplicated"] is True
    assert calls==[(CASE_BID,49,"collect")]


def test_invalid_key_and_off_flow_feature_do_not_touch_database():
    app=FastAPI();app.include_router(router)
    c=TestClient(app)
    with patch("main.guard",return_value=None),\
         patch("n8n_job_bridge.notice_context",return_value=CONTEXT):
        bad=c.post("/api/n8n/operational/flows/PF05/dispatch",json={
            "bid_no":CASE_BID,"feature_no":49,"request_key":"invalid key whitespace"})
        assert bad.status_code==422
        wrong=c.post("/api/n8n/operational/flows/PF05/dispatch",json={
            "bid_no":CASE_BID,"feature_no":1,"request_key":"legal-123456789"})
        assert wrong.status_code==409


def test_queue_capacity_is_atomic_under_case_lock_not_just_a_planning_hint():
    """A competing parallel n8n dispatch cannot create a fourth active job."""
    from fastapi import HTTPException
    from g2b_feature_api import FeatureRunRequest, queue_one
    class FakeRows:
        def __init__(self, value):self.value=value
        def fetchone(self):return self.value
        def fetchall(self):return self.value
    class LockedCase:
        def execute(self, sql, args=None):
            if "FOR UPDATE" in sql:
                return FakeRows({"bid_no":CASE_BID})
            if "FROM procureflow.jobs" in sql:
                return FakeRows([
                    {"id":1,"feature_no":"1","resource_key":"refresh_selected_official_notice"},
                    {"id":2,"feature_no":"29","resource_key":"download_original_attachments"},
                    {"id":3,"feature_no":"50","resource_key":"collect_exact_ten_digit_outcomes"},
                ])
            raise AssertionError("A fourth job must never reach INSERT")
    @contextmanager
    def fake_session():
        yield LockedCase()
    with patch("g2b_feature_api.session",fake_session):
        try:
            queue_one(CASE_BID,66,FeatureRunRequest(mode="collect",parameters={}))
        except HTTPException as err:
            assert err.status_code==409
            assert "Maximum 3" in str(err.detail)
        else:
            raise AssertionError("Concurrent collector capacity not enforced")



def test_read_only_progress_shows_true_worker_state_without_secret_config():
    observation={"business_state":"BLOCKED_OR_PENDING","blocks_total":8,
                 "blocks_verified":1,
                 "pending_missing_evidence":["outcome_10years_complete"]}
    jobs=[
        {"id":199,"state":"running","config":{"feature_no":49,
          "private_token":"must-never-leak"},"created_at":NOW,
          "started_at":NOW,"finished_at":None},
        {"id":198,"state":"failed","config":{"feature_no":50,
          "parameters":{"supplier_bank_secret":"must-not-disclose"}},
         "created_at":NOW,"started_at":NOW,"finished_at":NOW},
        {"id":197,"state":"running","config":{"feature_no":1},
         "created_at":NOW,"started_at":NOW,"finished_at":None},
    ]
    result=progress_snapshot("PF05",CASE_BID,observation,jobs)
    assert result["workflow_status"]=="COLLECTING"
    assert result["active_jobs_count"]==1
    assert result["recent_job_failures"]==1
    assert [x["job_id"] for x in result["recent_jobs"]]==[199,198]
    assert result["blocks_verified"]==1
    assert result["read_only"] is True and result["job_enqueued"] is False
    assert result["bid_submitted"] is False
    import json
    exported=json.dumps(result,default=str)
    assert "must-never-leak" not in exported
    assert "must-not-disclose" not in exported
    assert "config" not in exported


def test_progress_handler_and_monitor_route_contracts():
    from pathlib import Path
    base=Path(__file__).resolve().parents[1]
    main=(base/"main.py").read_text(encoding="utf-8")
    monitor=(base/"n8n/progress.html").read_text(encoding="utf-8")
    assert '@app.get("/n8n/progress"' in main
    assert "/api/n8n/operational/flows/" in monitor
    assert "replaceChildren" in monitor and "textContent" in monitor
    assert "innerHTML" not in monitor
    assert "setInterval" in monitor
    app=FastAPI();app.include_router(router)
    client=TestClient(app)
    snap={"business_state":"BLOCKED_OR_PENDING","blocks_total":8,
          "blocks_verified":0,
          "pending_missing_evidence":["award_evidence"]}
    with patch("n8n_job_bridge.inspect_flow",return_value=snap),\
         patch("n8n_job_bridge._recent_jobs",return_value=[]):
        result=client.get("/api/n8n/operational/flows/PF05/progress")
        assert result.status_code==200,result.text
        body=result.json()
        assert body["workflow_status"]=="BLOCKED_OR_PENDING"
        assert body["active_jobs_count"]==0
        assert body["features_total"]==24
        assert body["read_only"] is True
        assert client.get("/api/n8n/operational/flows/PF99/progress").status_code==404
        assert client.get("/api/n8n/operational/flows/PF05/progress?bid_no=FORGED").status_code==422
