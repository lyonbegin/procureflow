"""Fail-closed official G2B envelope tests. Pure in-memory; no live API/DB."""
import json
from datetime import date

import pytest

import g2b_case_10y_official as official


ERROR_MARKERS = (
    "error", "errors", "fault", "errorCode", "errorMessage",
    "errorMsg", "error_message", "resultCode",
)
VALUES = (None, "", {"message": "upstream unavailable"})


def good_response():
    return {
        "response": {
            "header": {"resultCode": "00", "resultMsg": "NORMAL SERVICE."},
            "body": {"totalCount": 0, "items": {"item": []}},
        }
    }


@pytest.mark.parametrize("level", ("root", "envelope", "header"))
@pytest.mark.parametrize("marker", ERROR_MARKERS)
@pytest.mark.parametrize("value", VALUES)
def test_success_header_cannot_override_outer_provider_error(level, marker, value):
    # The documented header resultCode is required and must not be
    # interpreted as a header error. It is forbidden outside that header.
    if level == "header" and marker == "resultCode":
        return
    response = good_response()
    location = {
        "root": response,
        "envelope": response["response"],
        "header": response["response"]["header"],
    }[level]
    location[marker] = value
    expected = "g2b_api_" + level + "_error_marker"
    with pytest.raises(ValueError, match=expected):
        official._parse(response, expected_page=1, expected_rows=500)


@pytest.mark.parametrize("level", ("envelope", "header", "body"))
@pytest.mark.parametrize("invalid", ([], False, "", 0))
def test_falsey_non_object_envelopes_fail_closed(level, invalid):
    response = good_response()
    if level == "envelope":
        response["response"] = invalid
    else:
        response["response"][level] = invalid
    with pytest.raises(ValueError, match="g2b_api_.*not_object"):
        official._parse(response, expected_page=1, expected_rows=500)


def test_valid_empty_official_page_remains_supported():
    assert official._parse(good_response(), expected_page=1, expected_rows=500) == ([], 0)


class FakeResponse:
    def __init__(self, data):
        self.data = data

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self, *_):
        return json.dumps(self.data).encode("utf-8")


class FakeSession:
    def __init__(self, statements, row):
        self.statements = statements
        self.row = row

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, sql, params=None):
        self.statements.append((sql, params))
        return self

    def fetchone(self):
        return self.row


@pytest.mark.parametrize("level", ("root", "envelope", "header"))
def test_outer_error_marks_month_error_without_inserting_history(monkeypatch, level):
    first = date(2026, 10, 1)
    row = {
        "first_day": first,
        "last_day": date(2026, 10, 31),
        "status": "unsearched",
        "page_cursor": 1,
        "checked": 0,
        "matched": 0,
        "expected_total": None,
    }
    statements = []
    response = good_response()
    target = {
        "root": response,
        "envelope": response["response"],
        "header": response["response"]["header"],
    }[level]
    target["errorMessage"] = "upstream unavailable"
    monkeypatch.setattr(official, "ensure_schema", lambda: None)
    monkeypatch.setattr(official, "_service_key", lambda: "test-only-key")
    monkeypatch.setattr(official, "session", lambda: FakeSession(statements, row))
    monkeypatch.setattr(official, "urlopen", lambda *_args, **_kwargs: FakeResponse(response))
    result = official.scan_month(first)
    assert result["status"] == "error"
    assert result["reason"] == "official_api_request_or_parse_failed:ValueError"
    assert not any("INSERT INTO" in sql.upper() for sql, _ in statements)
    updates = [(sql, params) for sql, params in statements if "UPDATE" in sql.upper()]
    assert len(updates) == 1
    assert updates[0][1][0] == "error"
