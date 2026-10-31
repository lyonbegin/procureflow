"""Isolated contract tests: 121 official month pages before exact G2B outcomes.

No Railway DB, official API key, live G2B access or bid submission.
"""
from contextlib import contextmanager
from datetime import date
import calendar
import json
from unittest.mock import patch

import pytest

from g2b_case_10y_official import _parse, _page_verdict, scan_month, summarize_month_cursor
from g2b_case_10y import CASE_BID
from g2b_full_runner import historical_month_batch


MONTH = {"first_day": date(2024, 3, 1), "last_day": date(2024, 3, 31),
         "status": "unsearched", "page_cursor": 1, "checked": 0, "matched": 0}


def response(items, count):
    return {"response": {"header": {"resultCode": "00"},
            "body": {"totalCount": count, "items": {"item": items}}}}


class Rows:
    def __init__(self, value):
        self.value = value

    def fetchone(self):
        return self.value


class FakeMonthDB:
    def __init__(self):
        self.inserted = []

    def execute(self, sql, params=()):
        if "SELECT first_day,last_day,status,page_cursor" in sql:
            return Rows(MONTH)
        if "INSERT INTO procureflow.g2b_case_10yr_history" in sql:
            self.inserted.append(params)
            return Rows(None)
        raise AssertionError("unexpected SQL in month test: " + sql[:110])


class FakeHTTP:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, limit):
        assert limit <= 15_000_000
        return self.payload


@contextmanager
def fake_month_session(db):
    yield db


def run_month(payload):
    db = FakeMonthDB()
    status = []
    with patch("g2b_case_10y_official.ensure_schema"), \
         patch("g2b_case_10y_official.session", lambda: fake_month_session(db)), \
         patch("g2b_case_10y_official._service_key", return_value="SENSITIVE_API_KEY"), \
         patch("g2b_case_10y_official.urlopen", return_value=FakeHTTP(payload)), \
         patch("g2b_case_10y_official._write_month", side_effect=lambda *a: status.append(a)):
        result = scan_month("2024-03-01", pages_max=1)
    return result, status, db.inserted


@pytest.mark.parametrize("inspected,total,returned,verdict", [
    (0, 0, 0, "completed"),
    (0, 1, 1, "completed"),
    (0, 1000, 500, "partial"),
    (500, 1000, 500, "completed"),
    (0, 1200, 0, "incomplete_page"),
    (0, 1200, 7, "incomplete_page"),
    (0, 0, 3, "inconsistent"),
    (500, 300, 0, "inconsistent"),
    (0, -1, 0, "inconsistent"),
    (0, 501, 501, "inconsistent"),
])
def test_pagination_never_finishes_unverified_pages(inspected, total, returned, verdict):
    assert _page_verdict(inspected, total, returned) == verdict


def test_official_total_count_required_even_when_results_empty():
    with pytest.raises(ValueError, match="total_count_missing"):
        _parse({"response": {"header": {"resultCode": "00"}, "body": {"items": []}}})


@pytest.mark.parametrize("invalid_total", [
    True, False, 1.5, 0.0, -1.0, [], {}, None,
    "1.5", "1e0", "-1", "", "NaN",
])
def test_official_total_count_never_coerces_fractional_boolean_or_noncount(invalid_total):
    # A malformed totalCount must not be silently coerced to 0/1 and
    # mark a month completed, even when the API returns no items.
    result, statuses, inserted = run_month(response([], invalid_total))
    assert result["status"] == "error"
    assert result["reason"] == "official_api_request_or_parse_failed:ValueError"
    assert statuses[0][2] == "error"
    assert not inserted


@pytest.mark.parametrize("valid_total", [0, 1, "0", "1", " 1 "])
def test_official_total_count_accepts_only_integer_count_representations(valid_total):
    items, total = _parse(response([], valid_total))
    assert items == []
    assert total == int(valid_total)
    assert type(total) is int


@pytest.mark.parametrize("invalid_items", [
    0, False, "", "not-an-array", 1.5,
    {"item": 0}, {"item": False}, {"item": ""},
])
def test_official_scalar_items_cannot_forge_empty_completed_month(invalid_items):
    payload = {"response": {"header": {"resultCode": "00"},
               "body": {"totalCount": 0, "items": invalid_items}}}
    result, statuses, inserted = run_month(payload)
    assert result["status"] == "error"
    assert result["reason"] == "official_api_request_or_parse_failed:ValueError"
    assert statuses[0][2] == "error"
    assert not inserted


@pytest.mark.parametrize("empty_items", [None, [], {}, {"item": None}, {"item": []}])
def test_official_null_or_empty_items_remain_valid_zero_result_response(empty_items):
    payload = {"response": {"header": {"resultCode": "00"},
               "body": {"totalCount": 0, "items": empty_items}}}
    items, total = _parse(payload)
    assert items == [] and total == 0


def test_empty_page_cannot_finish_month_if_server_says_there_are_results():
    result, statuses, inserted = run_month(response([], 1200))
    assert result["status"] == "blocked_incomplete_api_page"
    assert result["official_total_count"] == 1200
    assert statuses[0][2] == "blocked_incomplete_api_page"
    assert not inserted


def test_out_of_month_candidate_cannot_be_used_to_mark_month_complete():
    wrong_month = {"prdctClsfcNo": "81111599", "bidNtceNo": "R24BK12345678",
                   "bidNtceOrd": "000", "bidNtceDt": "2024-04-07"}
    result, statuses, inserted = run_month(response([wrong_month], 1))
    assert result["status"] == "blocked_unverified_response_scope"
    assert result["invalid_scope_rows"] == 1
    assert statuses[0][2] == "blocked_unverified_response_scope"
    assert not inserted


def test_invalid_identifier_does_not_disappear_from_completion_check():
    wrong = {"prdctClsfcNo": "81111599", "bidNtceNo": "not-a-number",
             "bidNtceOrd": "000", "bidNtceDt": "2024-03-07"}
    result, statuses, inserted = run_month(response([wrong], 1))
    assert result["invalid_scope_rows"] == 1
    assert not inserted


def test_malformed_official_item_fails_before_month_completion():
    # API can return a non-object item even when totalCount looks complete.
    result, statuses, inserted = run_month(response(["unexpected string"], 1))
    assert result["status"] == "error"
    assert result["reason"] == "official_api_request_or_parse_failed:ValueError"
    assert statuses[0][2] == "error"
    assert not inserted


@pytest.mark.parametrize("amount", ["not-a-number", "-100", "1.5", 1.5, True, [], {}])
def test_malformed_or_negative_official_amount_blocks_month(amount):
    candidate = {"prdctClsfcNo": "81111599", "bidNtceNo": "R24BK12345678",
                 "bidNtceOrd": "000", "bidNtceDt": "2024-03-07",
                 "asignBdgtAmt": amount}
    result, statuses, inserted = run_month(response([candidate], 1))
    assert result["status"] == "blocked_unverified_response_scope"
    assert result["invalid_scope_rows"] == 1
    assert statuses[0][2] == "blocked_unverified_response_scope"
    assert not inserted


@pytest.mark.parametrize("cursor_fields", [
    {"page_cursor": 2},  # first page skipped
    {"checked": 501, "page_cursor": 2},  # incomplete prior page
    {"checked": 500, "matched": 501, "page_cursor": 2},  # impossible match count
    {"checked": -1},  # negative count
])
def test_corrupt_month_cursor_fails_closed_before_http(cursor_fields):
    # A false page cursor must never certify coverage by starting at page 2.
    # run_month uses the global MONTH fixture as its isolated DB row.
    with patch.dict(MONTH, cursor_fields):
        result, statuses, inserted = run_month(response([], 0))
    assert result["status"] == "blocked_invalid_page_cursor"
    assert result["read_only"] is True
    assert statuses[0][2] == "blocked_invalid_page_cursor"
    assert not inserted


def test_valid_resumed_full_page_cursor_can_finish_next_official_page():
    # A correctly persisted first 500-row page may resume at page 2.
    good = {"prdctClsfcNo": "81111599", "bidNtceNo": "R24BK12345678",
            "bidNtceOrd": "000", "bidNtceDt": "2024-03-07",
            "asignBdgtAmt": "120000"}
    with patch.dict(MONTH, {"status": "partial", "checked": 500,
                            "matched": 200, "page_cursor": 2}):
        result, statuses, inserted = run_month(response([good], 501))
    assert result["status"] == "completed"
    assert result["checked"] == 501 and result["matched"] == 201
    assert len(inserted) == 1 and inserted[0][7] == 120000
    assert statuses[0][2] == "completed"


def test_verified_month_stores_only_parent8_candidate_not_award():
    good = {"prdctClsfcNo": "81111599", "bidNtceNo": "R24BK12345678",
            "bidNtceOrd": "000", "bidNtceDt": "2024-03-07",
            "bidNtceNm": "실제 공개 공고"}
    result, statuses, inserted = run_month(response([good], 1))
    assert result["status"] == "completed"
    assert len(inserted) == 1
    assert inserted[0][3] == "81111599"  # NEVER fabricated detail10
    assert statuses[0][2] == "completed"
    assert "award" not in json.dumps(result)


def test_official_request_error_never_leaks_service_key_in_db_or_output():
    db = FakeMonthDB()
    errors = []
    with patch("g2b_case_10y_official.ensure_schema"), \
         patch("g2b_case_10y_official.session", lambda: fake_month_session(db)), \
         patch("g2b_case_10y_official._service_key", return_value="SENSITIVE_API_KEY"), \
         patch("g2b_case_10y_official.urlopen",
               side_effect=RuntimeError("https://official.invalid/?serviceKey=SENSITIVE_API_KEY")), \
         patch("g2b_case_10y_official._write_month", side_effect=lambda *a: errors.append(a)):
        result = scan_month("2024-03-01", pages_max=1)
    assert result["status"] == "error"
    assert "SENSITIVE_API_KEY" not in repr(result)
    assert "SENSITIVE_API_KEY" not in repr(errors)


class FakeCycleDB:
    def __init__(self, month=MONTH, total=121, completed=0):
        self.month, self.total, self.completed = month, total, completed

    def execute(self, sql, params=()):
        assert params == (CASE_BID,)
        if "WHERE case_bid_no=%s AND status<>'completed'" in sql:
            return Rows(self.month)
        if "COUNT(*) AS total" in sql:
            return Rows({"total": self.total, "completed": self.completed})
        raise AssertionError(sql)


@contextmanager
def fake_cycle_session(db):
    yield db


OFFICIAL_CTX = {"original_notice_verified": True,
                "official_detail10": ["8111159901"]}


def test_real_history_worker_runs_one_bounded_month_then_exact_outcomes():
    db = FakeCycleDB()
    recorded = []
    outcome = {"verified_exact_code": 2, "opening_bidder_rows_saved": 9,
               "final_awards_verified": 1, "candidate_checked": 3}
    with patch("g2b_case_10y.ensure_schema"), \
         patch("g2b_full_runner.session", lambda: fake_cycle_session(db)), \
         patch("g2b_feature_api.notice_context", return_value=OFFICIAL_CTX), \
         patch("g2b_full_runner.scan_month", side_effect=lambda *a, **k:
               recorded.append((a, k)) or {"status": "partial", "next_page": 2}), \
         patch("g2b_exact_outcome_history.run_batch", return_value=outcome) as results:
        result = historical_month_batch(candidate_limit=2, opening_limit=1,
                                        month_pages_max=1)
    assert recorded == [((MONTH["first_day"],), {"pages_max": 1})]
    results.assert_called_once_with(limit=2, opening_limit=1)
    assert result["status"] == "partial_exact_results"
    assert result["official_month"]["status"] == "partial"
    assert result["confirmed_final_awards"] == 1
    assert not result["ten_year_outcome_coverage_complete"]
    assert not result["bid_submitted"]


def test_absent_exact_selected_category_stops_before_any_history_db_call():
    with patch("g2b_feature_api.notice_context", return_value={
         "original_notice_verified": False, "official_detail10": ["8111159901"]}), \
         patch("g2b_full_runner.session") as db:
        result = historical_month_batch()
    assert result["status"] == "blocked"
    assert not result["official_discovery_started"]
    db.assert_not_called()


def test_blocked_month_does_not_dispatch_opening_api_again():
    db = FakeCycleDB()
    with patch("g2b_case_10y.ensure_schema"), \
         patch("g2b_full_runner.session", lambda: fake_cycle_session(db)), \
         patch("g2b_feature_api.notice_context", return_value=OFFICIAL_CTX), \
         patch("g2b_full_runner.scan_month", return_value={
             "status": "blocked_missing_official_api_key"}), \
         patch("g2b_exact_outcome_history.run_batch") as results:
        result = historical_month_batch()
    assert result["reason"] == "official_month_scan_not_verified"
    assert result["official_month"]["status"] == "blocked_missing_official_api_key"
    assert not result["bid_submitted"]
    results.assert_not_called()


def test_incomplete_registry_never_claims_full_ten_year_horizon():
    db = FakeCycleDB(total=120, completed=120)
    with patch("g2b_case_10y.ensure_schema"), \
         patch("g2b_full_runner.session", lambda: fake_cycle_session(db)), \
         patch("g2b_feature_api.notice_context", return_value=OFFICIAL_CTX), \
         patch("g2b_full_runner.scan_month") as month:
        result = historical_month_batch()
    assert result["reason"] == "official_month_registry_incomplete"
    month.assert_not_called()


def _all_registered_months():
    rows=[]
    for year in range(2016, 2027):
        for month in range(1,13):
            first=max(date(2016,10,24),date(year,month,1))
            last=min(date(2026,10,24),date(year,month,calendar.monthrange(year,month)[1]))
            if first<=last:
                rows.append({"first_day":first,"last_day":last,
                             "status":"completed","checked":0,
                             "matched":0,"page_cursor":1,
                             "last_error":"serviceKey=SENSITIVE_API_KEY"})
    return rows


def test_all_121_months_done_still_do_not_prove_ten_year_opening_or_award():
    rows=_all_registered_months()
    result=summarize_month_cursor(rows)
    assert len(rows)==121
    assert result["registry_complete"]
    assert result["discovery_months_completed"]==121
    assert result["eight_digit_notice_discovery_complete"] is True
    assert result["ten_year_exact_opening_and_award_complete"] is False
    assert not result["bid_submitted"]
    assert "SENSITIVE_API_KEY" not in repr(result)


def test_missing_window_or_duplicate_disables_completion_and_prefers_partial_cursor():
    rows=_all_registered_months()
    rows[2]["status"]="unsearched"
    rows[3]["status"]="partial"
    rows[3]["page_cursor"]=7
    result=summarize_month_cursor(rows)
    assert result["eight_digit_notice_discovery_complete"] is False
    assert result["next_month"]["first_day"]==rows[3]["first_day"].isoformat()
    assert result["next_month"]["next_page"]==7
    broken=summarize_month_cursor(rows[:-1]+[rows[-2]])
    assert broken["registry_complete"] is False
    assert broken["invalid_or_duplicate_rows"]==1


def test_native_progress_endpoint_only_reports_db_cursor_without_collector_calls():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from n8n_job_bridge import router
    app=FastAPI()
    app.include_router(router)
    expected=summarize_month_cursor(_all_registered_months())
    with patch("g2b_case_10y_official.official_month_progress",return_value=expected) as read:
        response=TestClient(app).get("/api/n8n/operational/history/month-progress")
    assert response.status_code==200,response.text
    body=response.json()
    assert body["read_only"] and not body["job_enqueued"]
    assert body["ten_year_exact_opening_and_award_complete"] is False
    read.assert_called_once()
