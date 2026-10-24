"""Contract checks for the non-submitting ProcureFlow bid preview."""
from datetime import datetime
from zoneinfo import ZoneInfo
from bid_simulation import deadline_state, money_number, topic_for

def test_topic_is_named_not_generic():
    assert topic_for("[서울] 경비용역 사업자 선정 입찰 재공고") == "경비"
    assert topic_for("입찰 재공고") == ""

def test_amount_never_guessed():
    assert money_number("69,400,000원") == 69400000
    assert money_number("예산 미공개") is None

def test_deadline_requires_exact_time():
    now = datetime(2026, 10, 24, 14, 0, tzinfo=ZoneInfo("Asia/Seoul"))
    assert deadline_state("2026-10-26 17:00:00", now) == "open_by_recorded_deadline"
    assert deadline_state("202610", now) == "unverified"
    assert deadline_state("2026-10-20 17:00:00", now) == "past_recorded_deadline"
