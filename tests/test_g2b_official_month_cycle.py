"""Isolated contract tests: 121 official month pages before exact G2B outcomes.

No Railway DB, official API key, live G2B access or bid submission.
"""
from contextlib import contextmanager
from datetime import date
import calendar
import json
from unittest.mock import patch

import pytest

from g2b_case_10y_official import (
    MAX_OFFICIAL_RESPONSE_BYTES, _parse, _page_verdict, scan_month,
    summarize_month_cursor,
)
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

    def fetchall(self):
        return self.value


class FakeMonthDB:
    def __init__(self, prior_keys=None):
        self.inserted = []
        # When the fixture starts on page 2, synthesize the matched official
        # page-1 IDs that the persisted cursor claims already exist. Tests
        # may override these IDs to exercise duplicate and tampered history.
        self.prior_keys = prior_keys

    def execute(self, sql, params=()):
        if "SELECT first_day,last_day,status,page_cursor" in sql:
            return Rows(MONTH)
        if "SELECT hist_notice_no,hist_notice_ord" in sql:
            assert params == (
                CASE_BID, MONTH["first_day"], MONTH["last_day"],
                "81111599", "official_openapi_explicit_code"
            )
            keys = self.prior_keys
            if keys is None:
                keys = [
                    (f"R24BK{90000000+i:08d}", "000")
                    for i in range(MONTH["matched"])
                ] if MONTH["checked"] else []
            return Rows([
                {"hist_notice_no": no, "hist_notice_ord": ord_}
                for no, ord_ in keys
            ])
        if "INSERT INTO procureflow.g2b_case_10yr_history" in sql:
            self.inserted.append(params)
            return Rows(None)
        raise AssertionError("unexpected SQL in month test: " + sql[:110])


class FakeHTTP:
    def __init__(self, payload, status=200, headers=None):
        self.payload = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        self.status = status
        self.headers = headers if headers is not None else {}
        self.read_calls = 0

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, limit):
        # Match HTTPResponse.read(n): never return more than n bytes.
        self.read_calls += 1
        assert limit <= MAX_OFFICIAL_RESPONSE_BYTES + 1
        return self.payload[:limit]


@contextmanager
def fake_month_session(db):
    yield db


def run_month(payload, prior_keys=None, first="2024-03-01", *, http_response=None):
    db = FakeMonthDB(prior_keys=prior_keys)
    status = []
    fake_http = http_response if http_response is not None else FakeHTTP(payload)
    with patch("g2b_case_10y_official.ensure_schema"), \
         patch("g2b_case_10y_official.session", lambda: fake_month_session(db)), \
         patch("g2b_case_10y_official._service_key", return_value="SENSITIVE_API_KEY"), \
         patch("g2b_case_10y_official.urlopen", return_value=fake_http), \
         patch("g2b_case_10y_official._write_month", side_effect=lambda *a: status.append(a)):
        result = scan_month(first, pages_max=1)
    return result, status, db.inserted



@pytest.mark.parametrize("first_day,last_day,request_first", [
    # A forged end date must never let March scan April or silently omit
    # March 31 while claiming the March window was completed.
    (date(2024, 3, 1), date(2024, 4, 1), "2024-03-01"),
    (date(2024, 3, 1), date(2024, 3, 30), "2024-03-01"),
    # A forged first day must not bypass the registered month boundaries.
    (date(2024, 3, 2), date(2024, 3, 31), "2024-03-01"),
    # A forged window cannot extend beyond the selected ten-year horizon.
    (date(2024, 3, 1), date(2027, 3, 31), "2024-03-01"),
    (date(2024, 3, 1), None, "2024-03-01"),
    # The caller may not start from the middle of an otherwise valid month.
    (date(2024, 3, 1), date(2024, 3, 31), "2024-03-02"),
    # No forged outside-horizon month may become completed.
    (date(2015, 10, 1), date(2015, 10, 31), "2015-10-01"),
])
def test_tampered_month_boundaries_block_before_official_http_or_db_mutation(
        first_day, last_day, request_first):
    # FakeHTTP/FakeDB only. If the window check were missing, the mock zero
    # result would mark the wrong window completed; this must stay read-only.
    with patch.dict(MONTH, {"first_day": first_day, "last_day": last_day}):
        result, statuses, inserted = run_month(response([], 0), first=request_first)
    assert result["status"] == "blocked_invalid_month_window"
    assert result["reason"] == "persisted_month_boundary_mismatch"
    assert result["read_only"] is True
    assert statuses == []
    assert inserted == []


@pytest.mark.parametrize("first_day,last_day", [
    (date(2016, 10, 24), date(2016, 10, 31)),
    (date(2024, 3, 1), date(2024, 3, 31)),
    (date(2026, 10, 1), date(2026, 10, 24)),
])
def test_valid_partial_horizon_and_full_month_boundaries_remain_compatible(
        first_day, last_day):
    with patch.dict(MONTH, {"first_day": first_day, "last_day": last_day}):
        result, statuses, inserted = run_month(
            response([], 0), first=first_day.isoformat())
    assert result["status"] == "completed"
    assert statuses and statuses[-1][2] == "completed"
    assert inserted == []


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
@pytest.mark.parametrize("placement", [
    "root_metadata", "header_metadata", "body_metadata", "notice_metadata",
])
def test_nonstandard_official_json_constants_never_certify_month(constant, placement):
    """Reject non-JSON numeric literals at any depth before history INSERT.

    CPython json.loads otherwise accepts NaN/Infinity even though the official
    provider contract is JSON. All network and DB dependencies are fakes.
    """
    notice = {
        "prdctClsfcNo": "81111599",
        "bidNtceNo": "R24BK90000000",
        "bidNtceOrd": "000",
        "bidNtceDt": "20240312",
    }
    raw = response([notice], 1)
    if placement == "root_metadata":
        raw["extra"] = "__NONFINITE__"
    elif placement == "header_metadata":
        raw["response"]["header"]["extra"] = "__NONFINITE__"
    elif placement == "body_metadata":
        raw["response"]["body"]["extra"] = "__NONFINITE__"
    else:
        notice["extra"] = "__NONFINITE__"
    payload = json.dumps(raw).replace('"__NONFINITE__"', constant).encode("utf-8")
    result, statuses, inserted = run_month(payload)
    assert result["status"] == "error"
    assert result["reason"] == "official_api_request_or_parse_failed:ValueError"
    assert statuses and statuses[-1][2] == "error"
    assert inserted == []


def test_oversized_official_json_never_certifies_month_after_truncated_valid_prefix():
    """An old read(15 MB) discarded trailing bytes without detecting them.

    A valid zero-result JSON response padded to exactly 15 MB is followed by
    conflicting extra JSON. The old parser would see only valid JSON and
    falsely complete the month; the bounded 15 MB + 1 read must reject it.
    FakeHTTP/FakeDB only; no official API, credentials, Worker or bid calls.
    """
    valid=json.dumps(response([], 0)).encode("utf-8")
    payload=(valid + b" " * (MAX_OFFICIAL_RESPONSE_BYTES-len(valid))
             + b'{"response":{"header":{"resultCode":"99"}}}')
    result, statuses, inserted=run_month(payload)
    assert result["status"]=="error"
    assert result["reason"]=="official_api_request_or_parse_failed:ValueError"
    assert statuses and statuses[-1][2]=="error"
    assert inserted==[]
    assert not any(row[2]=="completed" for row in statuses)


def test_official_json_exact_response_size_limit_remains_compatible():
    """A valid response at the declared cap remains readable, not truncated."""
    valid=json.dumps(response([], 0)).encode("utf-8")
    payload=valid+b" "*(MAX_OFFICIAL_RESPONSE_BYTES-len(valid))
    assert len(payload)==MAX_OFFICIAL_RESPONSE_BYTES
    result, statuses, inserted=run_month(payload)
    assert result["status"]=="completed"
    assert statuses and statuses[-1][2]=="completed"
    assert inserted==[]


def test_standard_json_metadata_remains_compatible_with_month_coverage():
    """Valid unused numeric metadata must not break existing official pages."""
    notice = {
        "prdctClsfcNo": "81111599",
        "bidNtceNo": "R24BK90000000",
        "bidNtceOrd": "000",
        "bidNtceDt": "20240312",
        "extra": 0.5,
    }
    raw = response([notice], 1)
    raw["response"]["body"]["extra"] = 1.25
    result, statuses, inserted = run_month(raw)
    assert result["status"] == "completed"
    assert statuses and statuses[-1][2] == "completed"
    assert len(inserted) == 1


@pytest.mark.parametrize("raw", [
    # Python json.loads normally uses the LAST repeated key. The second
    # occurrence could hide an error or replace an official totalCount=1
    # with 0 and falsely certify the month as empty/completed.
    b'{"response":{"header":{"resultCode":"00"},"body":{"totalCount":1,"totalCount":0,"items":[]}}}',
    b'{"response":{"header":{"resultCode":"99","resultCode":"00"},"body":{"totalCount":0,"items":[]}}}',
    b'{"response":{"header":{"resultCode":"00"},"body":{"totalCount":0,"items":{"item":[{"bidNtceNo":"R24BK00000001"}],"item":[]}}}}',
    b'{"response":{"header":{"resultCode":"00"},"body":{"totalCount":0,"items":[]}},"response":{"header":{"resultCode":"00"},"body":{"totalCount":0,"items":[]}}}',
    b'{"response":{"header":{"resultCode":"00"},"body":{"totalCount":1,"items":{"item":[{"bidNtceNo":"R24BK00000001","bidNtceNo":"R24BK00000002"}]}}}}',
])
def test_duplicate_official_json_keys_never_certify_month(raw):
    # FakeHTTP/FakeDB only. Even a syntactically valid outer JSON object
    # must fail before any history INSERT or completed-month cursor write.
    result, statuses, inserted = run_month(raw)
    assert result["status"] == "error"
    assert result["reason"] == "official_api_request_or_parse_failed:ValueError"
    assert statuses and statuses[0][2] == "error"
    assert inserted == []


def test_duplicate_key_parser_keeps_valid_unique_json_compatible():
    from g2b_case_10y_official import _reject_duplicate_json_keys
    raw = json.dumps(response([], 0)).encode()
    assert _parse(json.loads(raw, object_pairs_hook=_reject_duplicate_json_keys)) == ([], 0)


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


@pytest.mark.parametrize("invalid_wrapper", [
    {"error": "upstream unavailable"},
    {"unexpected": []},
    {"result": {"item": []}},
    {"count": 0},
])
@pytest.mark.parametrize("total_count", [0, 1])
def test_unknown_nonempty_official_items_wrapper_cannot_certify_month(invalid_wrapper, total_count):
    # A malformed response wrapper must not masquerade as an empty month.
    # Keep unknown API response schemas outside the official evidence cursor.
    payload = {"response": {"header": {"resultCode": "00"},
               "body": {"totalCount": total_count, "items": invalid_wrapper}}}
    with pytest.raises(ValueError, match="items_wrapper_missing_item"):
        _parse(payload)
    result, statuses, inserted = run_month(payload)
    assert result["status"] == "error"
    assert result["reason"] == "official_api_request_or_parse_failed:ValueError"
    assert statuses[0][2] == "error"
    assert not inserted



@pytest.mark.parametrize("unexpected", [
    {"error": "upstream unavailable"},
    {"fault": {"code": "G2B_TIMEOUT"}},
    {"resultCode": "99"},
    {"unexpected": []},
    {"message": "invalid service key"},
])
@pytest.mark.parametrize("total_count", [0, 1])
def test_official_items_with_item_and_extra_fields_never_certify_month(
        unexpected, total_count):
    # The known 'item' field must not mask an additional error/unknown
    # wrapper. These fixtures are isolated: no real G2B or Railway access.
    payload = {"response": {"header": {"resultCode": "00"},
               "body": {"totalCount": total_count,
                        "items": {"item": [], **unexpected}}}}
    with pytest.raises(ValueError, match="items_wrapper_extra_fields"):
        _parse(payload)
    result, statuses, inserted = run_month(payload)
    assert result["status"] == "error"
    assert result["reason"] == "official_api_request_or_parse_failed:ValueError"
    assert statuses[0][2] == "error"
    assert inserted == []


@pytest.mark.parametrize("marker", [
    "error", "errors", "fault", "errorCode", "errorMessage",
    "errorMsg", "error_message", "resultCode",
])
@pytest.mark.parametrize("marker_value", [
    "upstream unavailable", {"message": "failed"}, None,
])
@pytest.mark.parametrize("total_count", [0, 1])
def test_official_body_error_marker_cannot_certify_month(
        marker, marker_value, total_count):
    # The header may say success while the body reports an upstream failure.
    # Never promote an empty page (especially totalCount=0) to completed.
    payload = response([], total_count)
    payload["response"]["body"][marker] = marker_value
    with pytest.raises(ValueError, match="g2b_api_body_error_marker"):
        _parse(payload)
    result, statuses, inserted = run_month(payload)
    assert result["status"] == "error"
    assert result["reason"] == "official_api_request_or_parse_failed:ValueError"
    assert statuses[0][2] == "error"
    assert inserted == []


@pytest.mark.parametrize("body_value", [[], False, 1, "failed"])
def test_official_nonobject_body_never_certifies_zero_result_month(body_value):
    payload = response([], 0)
    payload["response"]["body"] = body_value
    result, statuses, inserted = run_month(payload)
    assert result["status"] == "error"
    assert result["reason"] == "official_api_request_or_parse_failed:ValueError"
    assert statuses[0][2] == "error"
    assert inserted == []


def test_official_body_standard_pagination_fields_still_accepted():
    payload = response([], 0)
    payload["response"]["body"].update(pageNo=1, numOfRows=500)
    items, total = _parse(payload, expected_page=1, expected_rows=500)
    assert items == [] and total == 0
    result, statuses, inserted = run_month(payload)
    assert result["status"] == "completed"
    assert statuses[0][2] == "completed"
    assert inserted == []


@pytest.mark.parametrize("items", [
    {"item": []}, {"item": None}, {"item": [
        {"prdctClsfcNo": "81111599", "bidNtceNo": "R24BK12345678",
         "bidNtceOrd": "000", "bidNtceDt": "2024-03-07"}
    ]}
])
def test_known_official_items_wrapper_still_parses_without_extra_fields(items):
    rows, count = _parse({"response": {
        "header": {"resultCode": "00"},
        "body": {"totalCount": 1 if isinstance(items["item"], list) and items["item"] else 0,
                 "items": items}}})
    assert len(rows) == count


@pytest.mark.parametrize("empty_items", [None, [], {}, {"item": None}, {"item": []}])
def test_official_null_or_empty_items_remain_valid_zero_result_response(empty_items):
    payload = {"response": {"header": {"resultCode": "00"},
               "body": {"totalCount": 0, "items": empty_items}}}
    items, total = _parse(payload)
    assert items == [] and total == 0


@pytest.mark.parametrize("echo_field,echo_value", [
    ("pageNo", 2), ("pageNo", 0), ("pageNo", True),
    ("pageNo", 1.5), ("pageNo", "1.0"), ("pageNo", []),
    ("numOfRows", 100), ("numOfRows", 0), ("numOfRows", False),
    ("numOfRows", 500.0), ("numOfRows", "500.0"), ("numOfRows", {}),
])
def test_official_page_echo_mismatch_never_certifies_month(echo_field, echo_value):
    # A cached page-2 response or server-imposed 100-row page size must not
    # be treated as the requested page 1 with 500 rows, even if totalCount=0.
    payload = response([], 0)
    payload["response"]["body"][echo_field] = echo_value
    result, statuses, inserted = run_month(payload)
    assert result["status"] == "error"
    assert result["reason"] == "official_api_request_or_parse_failed:ValueError"
    assert statuses[0][2] == "error"
    assert not inserted


@pytest.mark.parametrize("page_no,rows", [
    (1, 500), ("1", "500"), (" 1 ", " 500 "),
])
def test_official_matching_page_echo_is_accepted(page_no, rows):
    payload = response([], 0)
    payload["response"]["body"].update(pageNo=page_no, numOfRows=rows)
    result, statuses, inserted = run_month(payload)
    assert result["status"] == "completed"
    assert result["checked"] == 0
    assert statuses[0][2] == "completed"
    assert not inserted


def test_official_page_echo_missing_remains_compatible_with_legacy_response():
    payload = response([], 0)
    items, total = _parse(payload, expected_page=1, expected_rows=500)
    assert items == [] and total == 0



def test_first_zero_result_month_rejects_orphaned_official_history_before_completion():
    # The first API call must not certify a 0-result month when persisted
    # target-category rows contradict the official empty page.
    result, statuses, inserted = run_month(
        response([], 0), prior_keys=[("R24BK12345678", "000")])
    assert result["status"] == "blocked_unverified_persisted_history"
    assert result["reason"] == "zero_result_month_has_unverified_history"
    assert result["read_only"] is True
    assert statuses == []
    assert inserted == []


def test_first_zero_result_month_fails_closed_when_history_read_unavailable():
    # An inaccessible history table is not proof that the table is empty.
    with patch("g2b_case_10y_official._persisted_official_notice_keys",
               return_value=None) as history:
        result, statuses, inserted = run_month(response([], 0))
    assert result["status"] == "blocked_unverified_persisted_history"
    assert result["read_only"] is True
    history.assert_called_once()
    assert statuses == []
    assert inserted == []


def test_official_zero_result_month_persists_page_one_and_passes_read_only_audit():
    # A legitimate zero-result API response is completed with checked=0.
    # The saved cursor must remain page 1, matching the read-only 121-month
    # coverage audit. A page-2 cursor here falsely invalidates a real month.
    result, statuses, inserted = run_month(response([], 0))
    assert result["status"] == "completed"
    assert result["checked"] == 0 and result["matched"] == 0
    assert not inserted
    assert len(statuses) == 1
    assert statuses[0][2:6] == ("completed", 0, 0, 1)
    rows = _all_registered_months()
    rows[0].update(status=statuses[0][2], matched=statuses[0][3],
                   checked=statuses[0][4], page_cursor=statuses[0][5])
    audit = summarize_month_cursor(rows)
    assert audit["invalid_cursor_rows"] == 0
    assert audit["discovery_months_completed"] == 121
    assert audit["eight_digit_notice_discovery_complete"] is True
    assert audit["ten_year_exact_opening_and_award_complete"] is False
    assert not audit["bid_submitted"]


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



@pytest.mark.parametrize("extra_fields", [
    {"dtilPrdctClsfcNo": "9999999901"},  # matching parent first, conflicting detail later
    {"prdlstClsfcNo": "99999999"},       # contradictory second parent8
    {"dtilPrdctClsfcNo": "8111159901",
     "dtilPrdlstClsfcNo": "8111159902"}, # two incompatible exact 10-digit details
    {"dtilPrdctClsfcNo": "malformed"},   # malformed secondary official field
    {"prdctClsfcCd": False},            # falsey scalar must not be ignored
    {"prdctClsfcCd": 81111599.0},       # floats are not official category codes
])
def test_conflicting_official_category_fields_block_month_before_insert(extra_fields):
    candidate = {"prdctClsfcNo": "81111599", "bidNtceNo": "R24BK12345678",
                 "bidNtceOrd": "000", "bidNtceDt": "2024-03-07",
                 **extra_fields}
    result, statuses, inserted = run_month(response([candidate], 1))
    assert result["status"] == "blocked_unverified_response_scope"
    assert result["undetermined_rows"] == 1
    assert statuses[0][2] == "blocked_unverified_response_scope"
    assert not inserted


@pytest.mark.parametrize("extra_fields", [
    {"dtilPrdctClsfcNo": "8111159901"},
    {"prdlstClsfcNo": "81111599", "dtilPrdlstClsfcNo": "8111159901"},
])
def test_consistent_parent_and_detail_classification_can_finish_parent8_discovery(extra_fields):
    candidate = {"prdctClsfcNo": "81111599", "bidNtceNo": "R24BK12345678",
                 "bidNtceOrd": "000", "bidNtceDt": "2024-03-07",
                 **extra_fields}
    result, statuses, inserted = run_month(response([candidate], 1))
    assert result["status"] == "completed"
    assert result["checked"] == 1 and result["matched"] == 1
    assert statuses[0][2] == "completed"
    assert len(inserted) == 1



@pytest.mark.parametrize("second_override", [
    {},  # exact duplicate, same identity and data
    {"asignBdgtAmt": "200"},  # same identity, contradictory amount
    {"bidNtceDt": "2024-03-08"},  # same identity, contradictory official date
])
def test_duplicate_official_notice_identity_blocks_page_before_any_insert(second_override):
    first = {"prdctClsfcNo": "81111599", "bidNtceNo": "R24BK12345678",
             "bidNtceOrd": "000", "bidNtceDt": "2024-03-07",
             "asignBdgtAmt": "100"}
    second = {**first, **second_override}
    result, statuses, inserted = run_month(response([first, second], 2))
    assert result["status"] == "blocked_unverified_response_scope"
    assert result["invalid_scope_rows"] == 1
    assert statuses[0][2] == "blocked_unverified_response_scope"
    assert not inserted
    assert result.get("total_records") is None



def run_two_official_pages(second_item, second_total=501):
    """Two official pages, entirely in FakeHTTP/FakeDB, no real G2B/DB."""
    first_page = [
        {"prdctClsfcNo": "81111599",
         "bidNtceNo": f"R24BK{i:08d}",
         "bidNtceOrd": "000", "bidNtceDt": "2024-03-07"}
        for i in range(500)
    ]
    db = FakeMonthDB()
    statuses = []
    payloads = [FakeHTTP(response(first_page, 501)),
                FakeHTTP(response([second_item], second_total))]
    with patch("g2b_case_10y_official.ensure_schema"), \
         patch("g2b_case_10y_official.session", lambda: fake_month_session(db)), \
         patch("g2b_case_10y_official._service_key", return_value="SENSITIVE_API_KEY"), \
         patch("g2b_case_10y_official.urlopen", side_effect=payloads) as http, \
         patch("g2b_case_10y_official._write_month",
               side_effect=lambda *a: statuses.append(a)):
        result = scan_month("2024-03-01", pages_max=2)
    assert http.call_count == 2
    return result, statuses, db.inserted


@pytest.mark.parametrize("changed_total", [500, 502, 1000])
def test_official_total_count_drift_across_pages_never_completes_month(changed_total):
    # A growing/shrinking live result set cannot be certified by mixing
    # page 1 of snapshot A with page 2 of snapshot B.
    last = {"prdctClsfcNo": "81111599", "bidNtceNo": "R24BK00000500",
            "bidNtceOrd": "000", "bidNtceDt": "2024-03-07"}
    result, statuses, inserted = run_two_official_pages(last, changed_total)
    assert result["status"] == "blocked_unverified_response_scope"
    assert result["reason"] == "official_total_count_changed_between_pages"
    assert result["page"] == 2
    assert len(inserted) == 500  # only first verified page was stored
    assert [row[2] for row in statuses] == [
        "partial", "blocked_unverified_response_scope"]
    assert statuses[-1][3:6] == (500, 500, 2)
    assert result.get("total_records") is None


@pytest.mark.parametrize("second_override", [
    {}, {"asignBdgtAmt": "9999"}, {"bidNtceDt": "2024-03-08"},
])
def test_duplicate_notice_on_later_page_is_blocked_before_second_page_insert(second_override):
    first = {"prdctClsfcNo": "81111599", "bidNtceNo": "R24BK00000000",
             "bidNtceOrd": "000", "bidNtceDt": "2024-03-07"}
    result, statuses, inserted = run_two_official_pages(
        {**first, **second_override})
    assert result["status"] == "blocked_unverified_response_scope"
    assert result["invalid_scope_rows"] == 1
    assert result["page"] == 2
    assert len(inserted) == 500  # no ON CONFLICT rewrite of first page
    assert [row[2] for row in statuses] == [
        "partial", "blocked_unverified_response_scope"]
    assert result.get("total_records") is None


def test_distinct_notice_on_second_page_completes_stable_501_result_month():
    last = {"prdctClsfcNo": "81111599", "bidNtceNo": "R24BK00000500",
            "bidNtceOrd": "000", "bidNtceDt": "2024-03-07"}
    result, statuses, inserted = run_two_official_pages(last)
    assert result["status"] == "completed"
    assert result["checked"] == 501 and result["matched"] == 501
    assert len(inserted) == 501
    assert len({(r[1], r[2]) for r in inserted}) == 501
    assert [row[2] for row in statuses] == ["partial", "completed"]


def test_distinct_official_notice_rounds_do_not_trigger_duplicate_guard():
    first = {"prdctClsfcNo": "81111599", "bidNtceNo": "R24BK12345678",
             "bidNtceOrd": "000", "bidNtceDt": "2024-03-07"}
    second = {**first, "bidNtceOrd": "001"}
    result, statuses, inserted = run_month(response([first, second], 2))
    assert result["status"] == "completed"
    assert result["checked"] == 2 and result["matched"] == 2
    assert statuses[0][2] == "completed"
    assert len(inserted) == 2
    assert {row[2] for row in inserted} == {"000", "001"}

def test_other_consistent_parent8_is_skipped_without_fabricating_a_match():
    candidate = {"prdctClsfcNo": "99999999", "dtilPrdctClsfcNo": "9999999901",
                 "bidNtceNo": "R24BK12345678", "bidNtceOrd": "000",
                 "bidNtceDt": "2024-03-07"}
    result, statuses, inserted = run_month(response([candidate], 1))
    assert result["status"] == "completed"
    assert result["checked"] == 1 and result["matched"] == 0
    assert statuses[0][2] == "completed"
    assert not inserted


@pytest.mark.parametrize("corrupt_id", [
    None, "", "not-an-official-notice", False, [], {},
])
def test_out_of_scope_page_row_without_verifiable_notice_identity_cannot_certify_month(corrupt_id):
    # totalCount includes *all* rows, including other categories. An
    # unidentifiable row may be a repeated/shifted page result.
    outside = {"prdctClsfcNo": "99999999", "bidNtceNo": corrupt_id,
               "bidNtceOrd": "000"}
    result, statuses, inserted = run_month(response([outside], 1))
    assert result["status"] == "blocked_unverified_response_scope"
    assert result["invalid_scope_rows"] == 1
    assert statuses[0][2] == "blocked_unverified_response_scope"
    assert not inserted


@pytest.mark.parametrize("second_category", ["99999999", "81111599"])
def test_duplicate_notice_from_other_category_never_certifies_month(second_category):
    # A matching row and an out-of-scope row cannot share one official
    # (notice number, round) within the same totalCount result set.
    first = {"prdctClsfcNo": "81111599", "bidNtceNo": "R24BK12345678",
             "bidNtceOrd": "000", "bidNtceDt": "2024-03-07"}
    second = {"prdctClsfcNo": second_category, "bidNtceNo": "R24BK12345678",
              "bidNtceOrd": "000", "bidNtceDt": "2024-03-07"}
    result, statuses, inserted = run_month(response([first, second], 2))
    assert result["status"] == "blocked_unverified_response_scope"
    assert result["invalid_scope_rows"] == 1
    assert statuses[0][2] == "blocked_unverified_response_scope"
    assert not inserted


def test_duplicate_out_of_scope_notice_across_pages_blocks_second_page():
    # Even when page 2 has a non-target category, a repeated identity means
    # the 501-row totalCount did not represent 501 distinct official notices.
    duplicate = {"prdctClsfcNo": "99999999", "bidNtceNo": "R24BK00000000",
                 "bidNtceOrd": "000"}
    result, statuses, inserted = run_two_official_pages(duplicate)
    assert result["status"] == "blocked_unverified_response_scope"
    assert result["invalid_scope_rows"] == 1
    assert result["page"] == 2
    assert len(inserted) == 500
    assert [row[2] for row in statuses] == [
        "partial", "blocked_unverified_response_scope"]


def test_duplicate_two_out_of_scope_rows_does_not_fake_zero_matched_coverage():
    outside = {"prdctClsfcNo": "99999999", "bidNtceNo": "R24BK12345678",
               "bidNtceOrd": "000", "bidNtceDt": "2024-03-07"}
    result, statuses, inserted = run_month(response([outside, dict(outside)], 2))
    assert result["status"] == "blocked_unverified_response_scope"
    assert result["invalid_scope_rows"] == 1
    assert statuses[0][2] == "blocked_unverified_response_scope"
    assert not inserted


def test_distinct_out_of_scope_notice_is_counted_but_not_persisted():
    matching = {"prdctClsfcNo": "81111599", "bidNtceNo": "R24BK12345678",
                "bidNtceOrd": "000", "bidNtceDt": "2024-03-07"}
    outside = {"prdctClsfcNo": "99999999", "bidNtceNo": "R24BK12345679",
               "bidNtceOrd": "000", "bidNtceDt": "2024-03-07"}
    result, statuses, inserted = run_month(response([matching, outside], 2))
    assert result["status"] == "completed"
    assert result["checked"] == 2 and result["matched"] == 1
    assert statuses[0][2] == "completed"
    assert len(inserted) == 1


@pytest.mark.parametrize("invalid_date", [
    None, "", "2024-02-29", "2024-04-01", "2024-03-07BAD",
    "2024-03-07 24:00", "2024-03-07 12:60",
    True, 20240307, [], {},
])
def test_out_of_scope_notice_with_unverified_month_date_cannot_certify_total_count(invalid_date):
    # A valid non-target classification still contributes to official
    # totalCount. A wrong/missing month timestamp is not verified coverage.
    outside = {"prdctClsfcNo": "99999999", "bidNtceNo": "R24BK12345679",
               "bidNtceOrd": "000", "bidNtceDt": invalid_date}
    result, statuses, inserted = run_month(response([outside], 1))
    assert result["status"] == "blocked_unverified_response_scope"
    assert result["invalid_scope_rows"] == 1
    assert statuses[0][2] == "blocked_unverified_response_scope"
    assert not inserted


@pytest.mark.parametrize("valid_date", [
    "2024-03-07", "20240307", "2024/03/07 12:30:59",
])
def test_out_of_scope_notice_with_verified_month_date_counts_without_insert(valid_date):
    outside = {"prdctClsfcNo": "99999999", "bidNtceNo": "R24BK12345679",
               "bidNtceOrd": "000", "bidNtceDt": valid_date}
    result, statuses, inserted = run_month(response([outside], 1))
    assert result["status"] == "completed"
    assert result["checked"] == 1 and result["matched"] == 0
    assert statuses[0][2] == "completed"
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



@pytest.mark.parametrize("invalid_round", [
    False, True, 0.0, 1.5, [], {}, -1, "1.0", "1000", "not-a-round",
])
def test_official_notice_round_cannot_be_fabricated_by_falsey_coercion(invalid_round):
    # Previously False became "000" through "value or '000'". A corrupted
    # official notice round must never certify a completed discovery month.
    candidate = {"prdctClsfcNo": "81111599", "bidNtceNo": "R24BK12345678",
                 "bidNtceOrd": invalid_round, "bidNtceDt": "2024-03-07"}
    result, statuses, inserted = run_month(response([candidate], 1))
    assert result["status"] == "blocked_unverified_response_scope"
    assert result["invalid_scope_rows"] == 1
    assert statuses[0][2] == "blocked_unverified_response_scope"
    assert not inserted


@pytest.mark.parametrize("valid_round", [None, "", "0", "000", 0, 1, "001"])
def test_official_notice_round_accepts_documented_missing_or_integer_forms(valid_round):
    candidate = {"prdctClsfcNo": "81111599", "bidNtceNo": "R24BK12345678",
                 "bidNtceOrd": valid_round, "bidNtceDt": "2024-03-07"}
    result, statuses, inserted = run_month(response([candidate], 1))
    assert result["status"] == "completed"
    assert len(inserted) == 1
    assert inserted[0][2] == ("001" if valid_round in (1, "001") else "000")


@pytest.mark.parametrize("invalid_date", [
    "2024-03-07TRAILING", "20240307junk", "202403071230evil",
    "2024-03/07", "2024-03-07 25:61", "2024-03-07T12:60:00",
    "2024-03-07T12:30:60", "2024-03-07T12:30Z", "2024030712",
    "2024-02-30", True, False, 20240307, [], {},
])
def test_official_notice_date_requires_full_valid_timestamp(invalid_date):
    # Prefix-only re.match previously accepted junk after YYYY-MM-DD and
    # impossible clock values, leading to a false completed month.
    candidate = {"prdctClsfcNo": "81111599", "bidNtceNo": "R24BK12345678",
                 "bidNtceOrd": "000", "bidNtceDt": invalid_date}
    result, statuses, inserted = run_month(response([candidate], 1))
    assert result["status"] == "blocked_unverified_response_scope"
    assert result["invalid_scope_rows"] == 1
    assert statuses[0][2] == "blocked_unverified_response_scope"
    assert not inserted


@pytest.mark.parametrize("valid_date", [
    "2024-03-07", "20240307", "202403071230", "20240307123059",
    "2024-03-07 12:30", "2024-03-07T12:30:59",
    "2024.03.07", "2024/03/07",
])
def test_official_notice_date_accepts_bounded_supported_formats(valid_date):
    candidate = {"prdctClsfcNo": "81111599", "bidNtceNo": "R24BK12345678",
                 "bidNtceOrd": "000", "bidNtceDt": valid_date}
    result, statuses, inserted = run_month(response([candidate], 1))
    assert result["status"] == "completed"
    assert result["checked"] == 1 and result["matched"] == 1
    assert statuses[0][2] == "completed"
    assert len(inserted) == 1

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
    # All malformed cursor values, including integer-but-inconsistent ones,
    # are read-only failures. Preserve the DB row for independent inspection.
    assert statuses == []
    assert not inserted


@pytest.mark.parametrize("cursor_fields", [
    {"checked": True}, {"checked": 1.5}, {"checked": "1.5"},
    {"checked": None}, {"matched": False}, {"matched": 0.5},
    {"matched": None}, {"page_cursor": True}, {"page_cursor": 1.5},
    {"page_cursor": "1.5"}, {"page_cursor": None}, {"page_cursor": 0},
])
def test_malformed_persisted_cursor_never_coerces_into_coverage_or_calls_http(cursor_fields):
    db = FakeMonthDB()
    with patch.dict(MONTH, cursor_fields), \
         patch("g2b_case_10y_official.ensure_schema"), \
         patch("g2b_case_10y_official.session", lambda: fake_month_session(db)), \
         patch("g2b_case_10y_official._service_key", return_value="SENSITIVE_API_KEY"), \
         patch("g2b_case_10y_official.urlopen") as http, \
         patch("g2b_case_10y_official._write_month") as write:
        result = scan_month("2024-03-01", pages_max=1)
    assert result["status"] == "blocked_invalid_page_cursor"
    assert result["read_only"] is True
    assert result["reason"] == "invalid_persisted_cursor_values"
    http.assert_not_called()
    write.assert_not_called()
    assert not db.inserted


@pytest.mark.parametrize("cursor_fields,expected", [
    ({"checked": 0, "matched": 0, "page_cursor": 1, "expected_total": 0}, "already_completed"),
    ({"checked": 500, "matched": 30, "page_cursor": 2, "expected_total": 500}, "already_completed"),
    ({"checked": 500, "matched": 30, "page_cursor": 1}, "blocked_invalid_page_cursor"),
    ({"checked": 0, "matched": 0, "page_cursor": 2}, "blocked_invalid_page_cursor"),
    ({"checked": 0, "matched": 1, "page_cursor": 1}, "blocked_invalid_page_cursor"),
    ({"checked": True, "matched": 0, "page_cursor": 1}, "blocked_invalid_page_cursor"),
    ({"checked": 1.5, "matched": 0, "page_cursor": 2}, "blocked_invalid_page_cursor"),
])
def test_completed_month_shortcut_requires_valid_auditable_cursor(cursor_fields,expected):
    db = FakeMonthDB()
    with patch.dict(MONTH, {"status": "completed", **cursor_fields}), \
         patch("g2b_case_10y_official.ensure_schema"), \
         patch("g2b_case_10y_official.session", lambda: fake_month_session(db)), \
         patch("g2b_case_10y_official._service_key") as key, \
         patch("g2b_case_10y_official.urlopen") as http, \
         patch("g2b_case_10y_official._write_month") as write:
        result = scan_month("2024-03-01", pages_max=1)
    assert result["status"] == expected
    if expected == "blocked_invalid_page_cursor":
        assert result["read_only"] is True
    key.assert_not_called()
    http.assert_not_called()
    write.assert_not_called()
    assert not db.inserted



@pytest.mark.parametrize("prior_keys,expected", [
    ([], "already_completed"),
    ([("R24BK12345678", "000")], "blocked_unverified_persisted_history"),
])
def test_completed_zero_result_month_must_have_zero_persisted_official_rows(
        prior_keys, expected):
    # A 0/0 completed cursor must not certify an orphaned history row.
    # Previously the shortcut skipped the history query for inspected == 0.
    db = FakeMonthDB(prior_keys=prior_keys)
    with patch.dict(MONTH, {"status": "completed", "checked": 0,
                            "matched": 0, "page_cursor": 1,
                            "expected_total": 0}), \
         patch("g2b_case_10y_official.ensure_schema"), \
         patch("g2b_case_10y_official.session", lambda: fake_month_session(db)), \
         patch("g2b_case_10y_official._service_key") as key, \
         patch("g2b_case_10y_official.urlopen") as http, \
         patch("g2b_case_10y_official._write_month") as write:
        result = scan_month("2024-03-01", pages_max=1)
    assert result["status"] == expected
    if expected == "blocked_unverified_persisted_history":
        assert result["reason"] == "completed_history_count_or_identity_mismatch"
        assert result["read_only"] is True
    key.assert_not_called()
    http.assert_not_called()
    write.assert_not_called()
    assert not db.inserted


def test_completed_zero_result_month_blocks_history_read_failure_without_http():
    # A failed read cannot be interpreted as evidence of an empty month.
    db = FakeMonthDB(prior_keys=[])
    with patch.dict(MONTH, {"status": "completed", "checked": 0,
                            "matched": 0, "page_cursor": 1,
                            "expected_total": 0}), \
         patch("g2b_case_10y_official.ensure_schema"), \
         patch("g2b_case_10y_official.session", lambda: fake_month_session(db)), \
         patch("g2b_case_10y_official._persisted_official_notice_keys",
               return_value=None) as history, \
         patch("g2b_case_10y_official._service_key") as key, \
         patch("g2b_case_10y_official.urlopen") as http, \
         patch("g2b_case_10y_official._write_month") as write:
        result = scan_month("2024-03-01", pages_max=1)
    assert result["status"] == "blocked_unverified_persisted_history"
    assert result["read_only"] is True
    history.assert_called_once()
    key.assert_not_called()
    http.assert_not_called()
    write.assert_not_called()
    assert not db.inserted


def test_valid_resumed_full_page_cursor_can_finish_next_official_page():
    # A correctly persisted first 500-row page may resume at page 2.
    good = {"prdctClsfcNo": "81111599", "bidNtceNo": "R24BK12345678",
            "bidNtceOrd": "000", "bidNtceDt": "2024-03-07",
            "asignBdgtAmt": "120000"}
    with patch.dict(MONTH, {"status": "partial", "checked": 500,
                            "matched": 200, "page_cursor": 2,
                            "expected_total": 501}):
        result, statuses, inserted = run_month(response([good], 501))
    assert result["status"] == "completed"
    assert result["checked"] == 501 and result["matched"] == 201
    assert len(inserted) == 1 and inserted[0][7] == 120000
    assert statuses[0][2] == "completed"


def test_resumed_month_blocks_duplicate_target_notice_from_earlier_invocation():
    # Two separate scan_month invocations previously reset seen_notice_keys.
    # A repeated target row on page 2 could increment checked/matched and
    # falsely complete a 501-row month while ON CONFLICT overwrote page 1.
    duplicate = ("R24BK12345678", "000")
    prior = [duplicate] + [
        (f"R24BK{90000000+i:08d}", "000") for i in range(199)
    ]
    item = {"prdctClsfcNo": "81111599", "bidNtceNo": duplicate[0],
            "bidNtceOrd": duplicate[1], "bidNtceDt": "2024-03-07"}
    with patch.dict(MONTH, {"status": "partial", "checked": 500,
                            "matched": 200, "page_cursor": 2,
                            "expected_total": 501}):
        result, writes, inserted = run_month(
            response([item], 501), prior_keys=prior)
    assert result["status"] == "blocked_unverified_response_scope"
    assert result["invalid_scope_rows"] == 1
    assert writes[0][2] == "blocked_unverified_response_scope"
    assert inserted == []


@pytest.mark.parametrize("bad_prior", [
    [],  # 200 matches claimed but no official rows exist
    [("R24BK12345678", "000")] * 200,  # repeated persisted identity
])
def test_resumed_month_rejects_inconsistent_persisted_history_before_http(bad_prior):
    db = FakeMonthDB(prior_keys=bad_prior)
    with patch.dict(MONTH, {"status": "partial", "checked": 500,
                            "matched": 200, "page_cursor": 2,
                            "expected_total": 501}), \
         patch("g2b_case_10y_official.ensure_schema"), \
         patch("g2b_case_10y_official.session", lambda: fake_month_session(db)), \
         patch("g2b_case_10y_official._service_key") as key, \
         patch("g2b_case_10y_official.urlopen") as http, \
         patch("g2b_case_10y_official._write_month") as write:
        result = scan_month("2024-03-01", pages_max=1)
    assert result["status"] == "blocked_unverified_persisted_history"
    assert result["read_only"] is True
    assert result["reason"] == "partial_history_count_or_identity_mismatch"
    key.assert_not_called()
    http.assert_not_called()
    write.assert_not_called()
    assert db.inserted == []


def test_completed_month_refuses_history_mismatch_even_with_matching_cursor():
    db = FakeMonthDB(prior_keys=[])
    with patch.dict(MONTH, {"status": "completed", "checked": 500,
                            "matched": 200, "page_cursor": 2,
                            "expected_total": 500}), \
         patch("g2b_case_10y_official.ensure_schema"), \
         patch("g2b_case_10y_official.session", lambda: fake_month_session(db)), \
         patch("g2b_case_10y_official._service_key") as key, \
         patch("g2b_case_10y_official.urlopen") as http, \
         patch("g2b_case_10y_official._write_month") as write:
        result = scan_month("2024-03-01", pages_max=1)
    assert result["status"] == "blocked_unverified_persisted_history"
    assert result["reason"] == "completed_history_count_or_identity_mismatch"
    assert result["read_only"] is True
    key.assert_not_called()
    http.assert_not_called()
    write.assert_not_called()


@pytest.mark.parametrize("changed_total", [500, 502, 700])
def test_resumed_month_never_accepts_changed_official_total_count(changed_total):
    # Page 1 was persisted in an earlier scan_month invocation with 501
    # official results. A later API snapshot must not certify page 2.
    item = {"prdctClsfcNo": "81111599", "bidNtceNo": "R24BK12345678",
            "bidNtceOrd": "000", "bidNtceDt": "2024-03-07"}
    with patch.dict(MONTH, {"status": "partial", "checked": 500,
                            "matched": 200, "page_cursor": 2,
                            "expected_total": 501}):
        result, writes, inserted = run_month(response([item], changed_total))
    assert result["status"] == "blocked_unverified_response_scope"
    assert result["reason"] == "official_total_count_changed_between_pages"
    assert writes[0][2] == "blocked_unverified_response_scope"
    assert writes[0][4:6] == (500, 2)
    assert inserted == []  # Never insert the changed second page.
    assert result.get("total_records") is None


@pytest.mark.parametrize("snapshot", [None, -1, 0, 500, 1.5, True, "501.5"])
def test_resumed_month_requires_valid_persisted_snapshot_before_network(snapshot):
    db = FakeMonthDB()
    with patch.dict(MONTH, {"status": "partial", "checked": 500,
                            "matched": 200, "page_cursor": 2,
                            "expected_total": snapshot}), \
         patch("g2b_case_10y_official.ensure_schema"), \
         patch("g2b_case_10y_official.session", lambda: fake_month_session(db)), \
         patch("g2b_case_10y_official._service_key") as key, \
         patch("g2b_case_10y_official.urlopen") as http, \
         patch("g2b_case_10y_official._write_month") as write:
        result = scan_month("2024-03-01", pages_max=1)
    assert result["status"] == "blocked_unverified_snapshot"
    assert result["read_only"] is True
    key.assert_not_called()
    http.assert_not_called()
    write.assert_not_called()
    assert not db.inserted


@pytest.mark.parametrize("snapshot", [None, 499, 501, False, 1.5])
def test_completed_month_requires_exact_persisted_snapshot(snapshot):
    db = FakeMonthDB()
    with patch.dict(MONTH, {"status": "completed", "checked": 500,
                            "matched": 200, "page_cursor": 2,
                            "expected_total": snapshot}), \
         patch("g2b_case_10y_official.ensure_schema"), \
         patch("g2b_case_10y_official.session", lambda: fake_month_session(db)), \
         patch("g2b_case_10y_official._service_key") as key, \
         patch("g2b_case_10y_official.urlopen") as http, \
         patch("g2b_case_10y_official._write_month") as write:
        result = scan_month("2024-03-01", pages_max=1)
    assert result["status"] == "blocked_unverified_snapshot"
    key.assert_not_called()
    http.assert_not_called()
    write.assert_not_called()


def test_month_progress_does_not_certify_completed_without_snapshot():
    rows = _all_registered_months()
    rows[0]["expected_total"] = None
    result = summarize_month_cursor(rows)
    assert result["discovery_months_completed"] == 120
    assert result["invalid_cursor_rows"] == 1
    assert result["eight_digit_notice_discovery_complete"] is False
    rows[0]["expected_total"] = rows[0]["checked"]
    good = summarize_month_cursor(rows)
    assert good["discovery_months_completed"] == 121


@pytest.mark.parametrize("row_status,checked,matched,page,snapshot", [
    ("completed",0,0,1,"absent"),
    ("completed",0,0,1,None),
    ("completed",500,20,2,"absent"),
    ("completed",500,20,2,None),
    ("partial",500,20,2,"absent"),
    ("partial",500,20,2,None),
    ("partial",500,20,2,500),
])
def test_read_only_month_progress_requires_persisted_snapshot_for_coverage(
        row_status,checked,matched,page,snapshot):
    rows=_all_registered_months()
    rows[0].update(status=row_status,checked=checked,matched=matched,
                   page_cursor=page)
    if snapshot=="absent":
        rows[0].pop("expected_total")
    else:
        rows[0]["expected_total"]=snapshot
    result=summarize_month_cursor(rows)
    assert result["registry_complete"] is True
    assert result["invalid_cursor_rows"]==1
    assert result["discovery_months_completed"]==120
    assert result["eight_digit_notice_discovery_complete"] is False
    assert result["months"][0]["cursor_valid"] is False
    assert result["next_month"]["first_day"]==rows[0]["first_day"].isoformat()
    assert result["read_only"] is True
    assert result["job_enqueued"] is False
    assert result["bid_submitted"] is False


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
                             "matched":0,"page_cursor":1,"expected_total":0,
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


@pytest.mark.parametrize("inspected,total,entries,page_size", [
    (False, 0, 0, 500), (0, True, 0, 500),
    (0, 0, False, 500), (0, 0, 0, True),
    (0, 0, 0, 0), (0, 0, 0, -1),
])
def test_page_verdict_rejects_boolean_or_invalid_pagination(inspected,total,entries,page_size):
    assert _page_verdict(inspected,total,entries,page_size)=="inconsistent"


@pytest.mark.parametrize("bad_field,bad_value", [
    ("checked", -1), ("checked", 1.5), ("checked", True),
    ("checked", "1.5"), ("checked", None),
    ("matched", -1), ("matched", 1.5), ("matched", True),
    ("matched", "not-a-count"), ("matched", None),
    ("page_cursor", 0), ("page_cursor", -1),
    ("page_cursor", 1.5), ("page_cursor", True),
    ("page_cursor", None), ("page_cursor", "not-a-page"),
    ("page_cursor", 7),  # impossible for zero checked rows
    ("matched", 1),  # greater than checked=0
])
def test_corrupted_completed_month_never_certifies_eight_digit_coverage(bad_field,bad_value):
    rows=_all_registered_months()
    rows[0][bad_field]=bad_value
    result=summarize_month_cursor(rows)
    assert result["registry_complete"] is True
    assert result["invalid_cursor_rows"]==1
    assert result["discovery_months_completed"]==120
    assert result["discovery_months_remaining"]==1
    assert result["eight_digit_notice_discovery_complete"] is False
    assert result["ten_year_exact_opening_and_award_complete"] is False
    assert result["next_month"]["first_day"]==rows[0]["first_day"].isoformat()
    assert result["next_month"]["cursor_valid"] is False
    assert result["read_only"] is True
    assert result["job_enqueued"] is False
    assert result["bid_submitted"] is False


@pytest.mark.parametrize("checked,matched,page,expected_valid", [
    (0, 0, 1, True),       # official zero-result month
    (1, 1, 2, True),       # final partial page advances cursor
    (499, 100, 2, True),
    (500, 300, 2, True),   # exactly one full page
    (501, 301, 3, True),
    (501, 502, 3, False), # more matches than inspected
    (501, 301, 2, False), # final page not advanced
    (500, 300, 3, False), # skipped page
])
def test_completed_month_cursor_arithmetic_is_fail_closed(checked,matched,page,expected_valid):
    rows=_all_registered_months()
    rows[3].update(checked=checked,matched=matched,page_cursor=page,
                   expected_total=checked)
    result=summarize_month_cursor(rows)
    assert result["months"][3]["cursor_valid"] is expected_valid
    assert result["invalid_cursor_rows"]==(0 if expected_valid else 1)
    assert result["discovery_months_completed"]==(121 if expected_valid else 120)
    assert result["eight_digit_notice_discovery_complete"] is expected_valid


@pytest.mark.parametrize("checked,matched,page,expected_valid", [
    (0,0,1,True),
    (500,20,2,True),
    (1000,500,3,True),
    (0,0,7,False),
    (499,10,2,False),
    (500,501,2,False),
    (500,20,3,False),
])
def test_partial_month_cursor_does_not_hide_missing_pages(checked,matched,page,expected_valid):
    rows=_all_registered_months()
    rows[1].update(status="partial",checked=checked,matched=matched,page_cursor=page,
                   expected_total=(checked+500 if checked else None))
    result=summarize_month_cursor(rows)
    assert result["months"][1]["cursor_valid"] is expected_valid
    assert result["invalid_cursor_rows"]==(0 if expected_valid else 1)
    assert result["discovery_months_completed"]==120
    assert result["eight_digit_notice_discovery_complete"] is False
    assert result["next_month"]["first_day"]==rows[1]["first_day"].isoformat()


@pytest.mark.parametrize("cursor_fields", [
    {"page_cursor": 2}, {"checked": 501, "page_cursor": 2},
    {"checked": 500, "matched": 501, "page_cursor": 2},
])
@pytest.mark.parametrize("key_value", [None, "SENSITIVE_API_KEY"])
def test_inconsistent_partial_cursor_blocks_before_credentials_or_any_write(
        cursor_fields, key_value):
    db = FakeMonthDB()
    with patch.dict(MONTH, {"status": "partial", **cursor_fields}), \
         patch("g2b_case_10y_official.ensure_schema"), \
         patch("g2b_case_10y_official.session", lambda: fake_month_session(db)), \
         patch("g2b_case_10y_official._service_key") as key, \
         patch("g2b_case_10y_official.urlopen") as http, \
         patch("g2b_case_10y_official._write_month") as write:
        key.return_value = key_value
        result = scan_month("2024-03-01", pages_max=1)
    assert result["status"] == "blocked_invalid_page_cursor"
    assert result["reason"] == "partial_cursor_mismatch"
    assert result["read_only"] is True
    key.assert_not_called()
    http.assert_not_called()
    write.assert_not_called()
    assert db.inserted == []


@pytest.mark.parametrize("pages_max", [
    True, False, 0, -1, 1.5, 1.0, "1", None, [], {},
])
def test_invalid_page_limit_blocks_before_credentials_http_or_db(pages_max):
    db = FakeMonthDB()
    with patch("g2b_case_10y_official.ensure_schema"), \
         patch("g2b_case_10y_official.session", lambda: fake_month_session(db)), \
         patch("g2b_case_10y_official._service_key") as key, \
         patch("g2b_case_10y_official.urlopen") as http, \
         patch("g2b_case_10y_official._write_month") as write:
        result = scan_month("2024-03-01", pages_max=pages_max)
    assert result["status"] == "blocked_invalid_page_limit"
    assert result["reason"] == "pages_max_must_be_positive_integer"
    assert result["read_only"] is True
    key.assert_not_called()
    http.assert_not_called()
    write.assert_not_called()
    assert db.inserted == []


@pytest.mark.parametrize("corrupt_status", [
    "COMPLETE", "verified", "ready_for_bid", "hold_verified",
    "unsearched ", "partial ", "", None, True, 1,
])
def test_unknown_month_state_blocks_before_credentials_http_or_any_write(corrupt_status):
    db = FakeMonthDB()
    with patch.dict(MONTH, {"status": corrupt_status}), \
         patch("g2b_case_10y_official.ensure_schema"), \
         patch("g2b_case_10y_official.session", lambda: fake_month_session(db)), \
         patch("g2b_case_10y_official._service_key") as key, \
         patch("g2b_case_10y_official.urlopen") as http, \
         patch("g2b_case_10y_official._write_month") as write:
        result = scan_month("2024-03-01", pages_max=1)
    assert result["status"] == "blocked_invalid_month_state"
    assert result["reason"] == "unknown_persisted_month_status"
    assert result["read_only"] is True
    key.assert_not_called()
    http.assert_not_called()
    write.assert_not_called()
    assert db.inserted == []


@pytest.mark.parametrize("dirty_fields", [
    {"checked": 1}, {"checked": 500, "page_cursor": 2},
    {"matched": 1}, {"page_cursor": 2}, {"expected_total": 0},
    {"expected_total": 100}, {"checked": True}, {"page_cursor": 1.0},
])
def test_unsearched_month_must_be_clean_before_any_external_access(dirty_fields):
    db = FakeMonthDB()
    with patch.dict(MONTH, {"status": "unsearched", **dirty_fields}), \
         patch("g2b_case_10y_official.ensure_schema"), \
         patch("g2b_case_10y_official.session", lambda: fake_month_session(db)), \
         patch("g2b_case_10y_official._service_key") as key, \
         patch("g2b_case_10y_official.urlopen") as http, \
         patch("g2b_case_10y_official._write_month") as write:
        result = scan_month("2024-03-01", pages_max=1)
    assert result["status"] == "blocked_invalid_page_cursor"
    assert result["reason"] in ("unsearched_month_has_progress", "invalid_persisted_cursor_values")
    assert result["read_only"] is True
    key.assert_not_called()
    http.assert_not_called()
    write.assert_not_called()
    assert db.inserted == []


@pytest.mark.parametrize("state", [
    "verified", "ready_for_bid", "COMPLETE", "", None, True,
])
def test_readonly_month_audit_rejects_unknown_state_as_coverage_evidence(state):
    rows = _all_registered_months()
    rows[0]["status"] = state
    result = summarize_month_cursor(rows)
    assert result["invalid_cursor_rows"] == 1
    assert result["discovery_months_completed"] == 120
    assert result["eight_digit_notice_discovery_complete"] is False
    assert result["ten_year_exact_opening_and_award_complete"] is False


@pytest.mark.parametrize("dirty_fields", [
    {"checked": 1}, {"matched": 1}, {"page_cursor": 2},
    {"expected_total": 0}, {"expected_total": 42},
])
def test_readonly_unsearched_month_requires_zero_cursor_without_snapshot(dirty_fields):
    rows = _all_registered_months()
    rows[0].update(status="unsearched", checked=0, matched=0,
                   page_cursor=1, expected_total=None)
    rows[0].update(dirty_fields)
    result = summarize_month_cursor(rows)
    assert result["invalid_cursor_rows"] == 1
    assert result["eight_digit_notice_discovery_complete"] is False
    assert result["months"][0]["cursor_valid"] is False


@pytest.mark.parametrize("invalid_state", [None, "", False, 0, "UNSEARCHED"])
def test_readonly_audit_never_coerces_invalid_state_to_clean_unsearched(invalid_state):
    rows = _all_registered_months()
    rows[0].update(status=invalid_state, checked=0, matched=0,
                   page_cursor=1, expected_total=None)
    result = summarize_month_cursor(rows)
    assert result["invalid_cursor_rows"] == 1
    assert result["months"][0]["cursor_valid"] is False
    assert result["eight_digit_notice_discovery_complete"] is False

@pytest.mark.parametrize("corrupt", [
    {"dtilPrdctClsfcNo": "81111599０１", "prdctClsfcNo": ""},
    {"bidNtceNo": "R24BK9000000０"},
    {"bidNtceOrd": "00٠"},
    {"bidNtceDt": "2024031２"},
    {"bidNtceDt": "20240312 12:3٠"},
])
def test_official_month_rejects_unicode_digits_before_history_insert(corrupt):
    """Unicode decimal digits cannot certify an official notice or date."""
    notice = {
        "prdctClsfcNo": "81111599",
        "bidNtceNo": "R24BK90000000",
        "bidNtceOrd": "000",
        "bidNtceDt": "20240312",
        "asignBdgtAmt": "1000",
    }
    notice.update(corrupt)
    result, updates, inserted = run_month(response([notice], 1))
    assert result["status"] == "blocked_unverified_response_scope"
    assert inserted == []
    assert updates and updates[-1][2] == "blocked_unverified_response_scope"


def test_official_month_ascii_notice_identity_remains_valid():
    notice = {
        "prdctClsfcNo": "81111599",
        "bidNtceNo": "R24BK90000000",
        "bidNtceOrd": "000",
        "bidNtceDt": "20240312",
        "asignBdgtAmt": "1000",
    }
    result, updates, inserted = run_month(response([notice], 1))
    assert result["status"] == "completed"
    assert len(inserted) == 1
    assert updates and updates[-1][2] == "completed"


@pytest.mark.parametrize("field", ["bidNtceNm", "dminsttNm", "ntceInsttNm"])
@pytest.mark.parametrize("invalid_value", [
    {"forged": "official notice"}, ["official notice"], True, False, 0, 1.5,
])
def test_malformed_official_notice_text_never_certifies_month(field, invalid_value):
    """An upstream JSON object/list/bool/number is not official text evidence.

    Test uses only FakeHTTP and FakeDB; it must never persist a fabricated
    title/agency or mark the monthly discovery cursor completed.
    """
    notice = {
        "prdctClsfcNo": "81111599",
        "bidNtceNo": "R24BK90000000",
        "bidNtceOrd": "000",
        "bidNtceDt": "20240312",
        "bidNtceNm": "Official notice",
        "dminsttNm": "Official agency",
        "ntceInsttNm": "Alternate official agency",
    }
    notice[field] = invalid_value
    result, statuses, inserted = run_month(response([notice], 1))
    assert result["status"] == "blocked_unverified_response_scope"
    assert result["invalid_scope_rows"] == 1
    assert statuses and statuses[-1][2] == "blocked_unverified_response_scope"
    assert inserted == []


def test_missing_official_notice_text_remains_unknown_not_fabricated():
    """Missing/null/empty text is unknown; valid strings remain compatible."""
    notice = {
        "prdctClsfcNo": "81111599",
        "bidNtceNo": "R24BK90000000",
        "bidNtceOrd": "000",
        "bidNtceDt": "20240312",
        "bidNtceNm": None,
        "dminsttNm": "",
        "ntceInsttNm": "Official alternate agency",
    }
    result, statuses, inserted = run_month(response([notice], 1))
    assert result["status"] == "completed"
    assert statuses and statuses[-1][2] == "completed"
    assert len(inserted) == 1
    assert inserted[0][5] == ""
    assert inserted[0][6] == "Official alternate agency"


@pytest.mark.parametrize("field", ["bidNtceNm", "dminsttNm", "ntceInsttNm"])
@pytest.mark.parametrize("malformed", [
    "\ud800", "\udfff", "title\x00hidden", "title\x01hidden", "title\x1fhidden",
])
def test_official_month_rejects_malformed_unicode_and_control_text(field, malformed):
    """Invalid Unicode scalar values and embedded controls never certify a month.

    JSON escape sequences can pass json.loads yet fail UTF-8 database encoding
    or carry hidden control characters. All calls use FakeHTTP and FakeDB.
    """
    notice = {
        "prdctClsfcNo": "81111599",
        "bidNtceNo": "R24BK90000000",
        "bidNtceOrd": "000",
        "bidNtceDt": "20240312",
        "bidNtceNm": "정상 공고명",
        "dminsttNm": "정상 기관",
        "ntceInsttNm": "정상 대체기관",
    }
    notice[field] = malformed
    result, statuses, inserted = run_month(response([notice], 1))
    assert result["status"] == "blocked_unverified_response_scope"
    assert result["invalid_scope_rows"] == 1
    assert statuses and statuses[-1][2] == "blocked_unverified_response_scope"
    assert inserted == []


def test_official_month_accepts_valid_korean_and_text_whitespace():
    """Ordinary Korean/emoji and CR/LF/tab are valid official text evidence."""
    notice = {
        "prdctClsfcNo": "81111599",
        "bidNtceNo": "R24BK90000000",
        "bidNtceOrd": "000",
        "bidNtceDt": "20240312",
        "bidNtceNm": "정보시스템 구축\n2차 공고\t😀",
        "dminsttNm": "서울특별시\r\n기관",
        "ntceInsttNm": "정상 기관",
    }
    result, statuses, inserted = run_month(response([notice], 1))
    assert result["status"] == "completed"
    assert statuses and statuses[-1][2] == "completed"
    assert len(inserted) == 1
    assert inserted[0][5] == notice["bidNtceNm"]
    assert inserted[0][6] == notice["dminsttNm"]


@pytest.mark.parametrize("field", ["bidNtceNm", "dminsttNm", "ntceInsttNm"])
@pytest.mark.parametrize("control", ["\u007f", "\u0080", "\u0085", "\u009f"])
def test_official_month_rejects_del_and_c1_controls_before_history_insert(field, control):
    """DEL/C1 controls can hide evidence content while looking like normal text.

    Verify all three official notice/agency fields with FakeHTTP/FakeDB only.
    The page must not be certified or insert any history row.
    """
    notice = {
        "prdctClsfcNo": "81111599",
        "bidNtceNo": "R24BK90000000",
        "bidNtceOrd": "000",
        "bidNtceDt": "20240312",
        "bidNtceNm": "정상 공고명",
        "dminsttNm": "정상 기관",
        "ntceInsttNm": "정상 대체기관",
    }
    notice[field] = "공식" + control + "증빙"
    result, statuses, inserted = run_month(response([notice], 1))
    assert result["status"] == "blocked_unverified_response_scope"
    assert result["invalid_scope_rows"] == 1
    assert statuses and statuses[-1][2] == "blocked_unverified_response_scope"
    assert inserted == []


def test_official_month_still_accepts_normal_unicode_after_del_c1_guard():
    """Ordinary Korean, emoji, tabs/newlines and non-ASCII letters remain valid."""
    notice = {
        "prdctClsfcNo": "81111599",
        "bidNtceNo": "R24BK90000000",
        "bidNtceOrd": "000",
        "bidNtceDt": "20240312",
        "bidNtceNm": "사업 구축\t2차\n공고 😀",
        "dminsttNm": "서울기관\r\nÉcole",
        "ntceInsttNm": "정상 대체기관",
    }
    result, statuses, inserted = run_month(response([notice], 1))
    assert result["status"] == "completed"
    assert statuses and statuses[-1][2] == "completed"
    assert len(inserted) == 1
    assert inserted[0][5] == notice["bidNtceNm"]
    assert inserted[0][6] == notice["dminsttNm"]


@pytest.mark.parametrize("field", ["bidNtceNm", "dminsttNm", "ntceInsttNm"])
@pytest.mark.parametrize("mark", [
    "\u061c",  # Arabic letter mark
    "\u200e", "\u200f",  # left/right-to-left marks
    "\u202a", "\u202b", "\u202c", "\u202d", "\u202e",  # embeddings/overrides
    "\u2066", "\u2067", "\u2068", "\u2069",  # isolates
])
def test_official_notice_bidi_format_controls_cannot_certify_month(field, mark):
    """Fake G2B/Fake DB: invisible bidi marks can spoof title/agency display.

    Any such mark in the three evidence text fields must reject the whole
    official page, write zero notice history rows and never mark it completed.
    """
    notice = {
        "prdctClsfcNo": "81111599",
        "bidNtceNo": "R24BK90000000",
        "bidNtceOrd": "000",
        "bidNtceDt": "20240312",
        "bidNtceNm": "공식 공고명",
        "dminsttNm": "서울 발주기관",
        "ntceInsttNm": "서울 공고기관",
    }
    notice[field] = "확인" + mark + "필요"
    result, statuses, inserted = run_month(response([notice], 1))
    assert result["status"] == "blocked_unverified_response_scope"
    assert result["invalid_scope_rows"] == 1
    assert statuses and statuses[-1][2] == "blocked_unverified_response_scope"
    assert all(s[2] != "completed" for s in statuses)
    assert inserted == []


def test_official_notice_real_rtl_letters_remain_accepted_without_bidi_controls():
    """Do not reject valid Arabic/Hebrew letters or Korean/emoji text."""
    notice = {
        "prdctClsfcNo": "81111599",
        "bidNtceNo": "R24BK90000000",
        "bidNtceOrd": "000",
        "bidNtceDt": "20240312",
        "bidNtceNm": "서울 입찰 إعلان 😀",
        "dminsttNm": "기관 משרד",
        "ntceInsttNm": "جهة إعلان",
    }
    result, statuses, inserted = run_month(response([notice], 1))
    assert result["status"] == "completed"
    assert statuses and statuses[-1][2] == "completed"
    assert len(inserted) == 1
    assert inserted[0][5] == notice["bidNtceNm"]
    assert inserted[0][6] == notice["dminsttNm"]


@pytest.mark.parametrize("http_status", [202, 204, 206])
def test_official_http_non_200_cannot_certify_valid_zero_count_json(http_status):
    """Even parseable 2xx JSON cannot certify a month without HTTP 200."""
    fake = FakeHTTP(response([], 0), status=http_status)
    result, statuses, inserted = run_month(response([], 0), http_response=fake)
    assert result["status"] == "error"
    assert result["reason"] == "official_api_request_or_parse_failed:ValueError"
    assert statuses and statuses[-1][2] == "error"
    assert all(row[2] != "completed" for row in statuses)
    assert inserted == []
    assert fake.read_calls == 0  # reject before consuming a partial body
    assert "SENSITIVE_API_KEY" not in json.dumps(result)


def test_official_http_200_with_content_range_cannot_certify_month():
    """A proxy's Content-Range signals partial representation even with 200."""
    fake = FakeHTTP(response([], 0), status=200,
                    headers={"Content-Range": "bytes 0-99/1000"})
    result, statuses, inserted = run_month(response([], 0), http_response=fake)
    assert result["status"] == "error"
    assert statuses and statuses[-1][2] == "error"
    assert all(row[2] != "completed" for row in statuses)
    assert inserted == []
    assert fake.read_calls == 0


def test_official_http_200_full_json_still_certifies_empty_month():
    """Normal full HTTP 200 remains backward-compatible."""
    fake = FakeHTTP(response([], 0), status=200)
    result, statuses, inserted = run_month(response([], 0), http_response=fake)
    assert result["status"] == "completed"
    assert result["checked"] == 0
    assert statuses and statuses[-1][2] == "completed"
    assert inserted == []
    assert fake.read_calls == 1



@pytest.mark.parametrize("amount", [
    "9" * 39,
    "9" * 4301,
    "  " + "9" * 4301 + "  ",
])
def test_official_oversized_decimal_amount_fails_closed_without_unhandled_conversion(amount):
    """Reject overlong provider amount strings before Python's int() digit cap.

    A 4301-digit decimal raises ValueError on Python 3.11+ when converted by
    int(); this parsing happens outside the HTTP exception handler. The
    collector must instead report a blocked month, write no official history,
    and never leak a raw provider amount into progress or audit output.
    All dependencies are fake HTTP/DB, with no G2B/Railway contact.
    """
    notice = {
        "prdctClsfcNo": "81111599",
        "bidNtceNo": "R24BK12345678",
        "bidNtceOrd": "000",
        "bidNtceDt": "2024-03-07",
        "asignBdgtAmt": amount,
    }
    result, statuses, inserted = run_month(response([notice], 1))
    assert result["status"] == "blocked_unverified_response_scope"
    assert result["invalid_scope_rows"] == 1
    assert statuses and statuses[-1][2] == "blocked_unverified_response_scope"
    assert inserted == []
    assert amount.strip() not in str(result)
    assert amount.strip() not in str(statuses)


@pytest.mark.parametrize("amount", ["0", "1234567890123456789"])
def test_official_regular_decimal_amount_remains_compatible(amount):
    """Normal official decimal strings continue through the existing path."""
    notice = {
        "prdctClsfcNo": "81111599",
        "bidNtceNo": "R24BK12345678",
        "bidNtceOrd": "000",
        "bidNtceDt": "2024-03-07",
        "asignBdgtAmt": amount,
    }
    result, statuses, inserted = run_month(response([notice], 1))
    assert result["status"] == "completed"
    assert statuses and statuses[-1][2] == "completed"
    assert len(inserted) == 1


@pytest.mark.parametrize("field", ["totalCount", "pageNo", "numOfRows"])
@pytest.mark.parametrize("oversized", ["9" * 39, "9" * 4301])
def test_official_oversized_page_count_strings_rejected_before_int(oversized, field):
    """Provider-controlled decimal counts must fail with our validation code.

    Python 3.11+ raises ValueError for int() on 4,301 decimal digits.
    Reject oversized values before that conversion; no official network/DB.
    """
    payload = response([], 0)
    payload["response"]["body"][field] = oversized
    expected = ("g2b_api_total_count_not_nonnegative_integer" if field == "totalCount"
                else "g2b_api_" + field + "_not_positive_integer")
    with pytest.raises(ValueError, match=expected):
        _parse(payload, expected_page=1, expected_rows=500)


def test_official_normal_page_count_strings_still_parse():
    """Normal official string count and pagination echoes remain compatible."""
    payload = response([], "0")
    payload["response"]["body"].update(pageNo="1", numOfRows="500")
    assert _parse(payload, expected_page=1, expected_rows=500) == ([], 0)


@pytest.mark.parametrize("field", ["checked", "matched", "page_cursor", "expected_total"])
def test_oversized_persisted_cursor_is_read_only_and_never_crashes(field):
    """A corrupt persisted month cursor must block before credentials or writes."""
    with patch.dict(MONTH, {field: "9" * 4301}):
        result, statuses, inserted = run_month(response([], 0))
    assert result["status"] == "blocked_invalid_page_cursor"
    assert result["read_only"] is True
    assert statuses == []
    assert inserted == []


@pytest.mark.parametrize("field", ["checked", "matched", "page_cursor", "expected_total"])
def test_oversized_cursor_read_only_summary_never_certifies_completion(field):
    """An untrusted DB row must not crash the 121-month diagnostic."""
    row = {**MONTH, "status": "completed", "checked": 0, "matched": 0,
           "page_cursor": 1, "expected_total": 0}
    row[field] = "9" * 4301
    result = summarize_month_cursor([row])
    assert result["invalid_cursor_rows"] == 1
    assert result["discovery_months_completed"] == 0
    assert result["eight_digit_notice_discovery_complete"] is False
    assert result["months"][0]["cursor_valid"] is False
    assert result["read_only"] is True
    assert result["bid_submitted"] is False


@pytest.mark.parametrize("field", ["totalCount", "pageNo", "numOfRows"])
@pytest.mark.parametrize("oversized", [10**38, 10**100])
def test_official_oversized_integer_page_counts_are_rejected(field, oversized):
    """A JSON numeric token must obey the same bound as a decimal string."""
    payload = response([], 0)
    payload["response"]["body"][field] = oversized
    expected = ("g2b_api_total_count_not_nonnegative_integer" if field == "totalCount"
                else "g2b_api_" + field + "_not_positive_integer")
    with pytest.raises(ValueError, match=expected):
        _parse(payload, expected_page=1, expected_rows=500)
