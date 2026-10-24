"""Explicitly activated tender agents: no automatic startup and deadline priority."""
from datetime import datetime
from zoneinfo import ZoneInfo
import pytest
import agent_orchestrator as a

def test_deadline_parser_accepts_exact_korean_formats():
    ko=ZoneInfo("Asia/Seoul")
    assert a._deadline_at("2026-10-25 17:00:00")==datetime(2026,10,25,17,0,tzinfo=ko)
    assert a._deadline_at("202610251700")==datetime(2026,10,25,17,0,tzinfo=ko)
    assert a._deadline_at("20261025170000")==datetime(2026,10,25,17,0,tzinfo=ko)
    assert a._deadline_at("2026-10-25") is None
    assert a._deadline_at("2026-13-01 17:00:00") is None

def test_three_slot_bound():
    assert a.AGENT_COUNT==3

class FakeCursor:
    def __init__(self, rows):
        self.rows=rows
        self.calls=[]
    def execute(self, query, params=None):
        self.calls.append((query,params))
        if "SELECT t.source" in query:
            return Result(self.rows)
        if "INSERT INTO procureflow.agent_cases" in query:
            return Result([{"attempt":1}])
        raise AssertionError("unexpected query "+query[:100])
class Result:
    def __init__(self,rows):self.rows=rows
    def fetchall(self):return self.rows
    def fetchone(self):return self.rows[0] if self.rows else None

def test_prioritize_nearest_deadline_even_when_notice_order_is_newest_first():
    import copy
    vals=[
        {"source":"kapt","external_id":"20261020122222222","deadline":"2026-11-12 17:00:00","attempts":0},
        {"source":"kapt","external_id":"20261020111111111","deadline":"2026-10-26 17:00:00","attempts":0},
        {"source":"kapt","external_id":"20261020133333333","deadline":"2026-11-01 17:00:00","attempts":0},
    ]
    if datetime.now(ZoneInfo("Asia/Seoul")) > datetime(2026,10,26,17,tzinfo=ZoneInfo("Asia/Seoul")):
        pytest.skip("time-sensitive fixture was designed for 2026-10-24")
    fake=FakeCursor(vals)
    found,attempt=a._get_candidate(fake,1)
    assert found["external_id"]=="20261020111111111"
    assert attempt==1

def test_no_activation_without_user_button_in_claim():
    src=__import__("inspect").getsource(a.claim)
    assert 'if not owned["enabled"]' in src

def test_service_main_starts_idle_slot_listeners_only():
    src=__import__("inspect").getsource(a.slot_main)
    assert 'if not active or not active["enabled"]' in src
