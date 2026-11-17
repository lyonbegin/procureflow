"""Official G2B echoed query scope must match the requested 8-digit month.

Pure in-memory FakeHTTP/FakeDB; no real G2B requests, Railway or bids.
"""
import json
from datetime import date

import pytest
import g2b_case_10y_official as official

EXPECTED = {
    "inqryBgnDt": "202610010000",
    "inqryEndDt": "202610242359",
    "prdctClsfcNo": "81111599",
}


def valid_empty_page():
    return {
        "response": {
            "header": {"resultCode": "00", "resultMsg": "NORMAL SERVICE."},
            "body": {"totalCount": 0, "items": {"item": []}},
        }
    }


@pytest.mark.parametrize("field,invalid", [
    ("inqryBgnDt", "202609010000"),
    ("inqryEndDt", "202610312359"),
    ("prdctClsfcNo", "81111598"),
    ("inqryBgnDt", None),
    ("inqryEndDt", False),
    ("prdctClsfcNo", ["81111599"]),
])
def test_echoed_wrong_month_or_category_fails_closed(field, invalid):
    data = valid_empty_page()
    data["response"]["body"].update(EXPECTED)
    data["response"]["body"][field] = invalid
    with pytest.raises(ValueError, match="g2b_api_"+field+"_request_mismatch"):
        official._parse(data, expected_page=1, expected_rows=500,
                        expected_query=EXPECTED)


def test_correct_echo_and_absent_echo_both_supported():
    data = valid_empty_page()
    assert official._parse(data, expected_page=1, expected_rows=500,
                           expected_query=EXPECTED) == ([], 0)
    data["response"]["body"].update(EXPECTED)
    assert official._parse(data, expected_page=1, expected_rows=500,
                           expected_query=EXPECTED) == ([], 0)


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self, *_):
        return json.dumps(self.payload).encode("utf-8")


class FakeSession:
    def __init__(self, row, statements):
        self.row = row
        self.statements = statements

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, sql, params=None):
        self.statements.append((sql, params))
        return self

    def fetchone(self):
        return self.row

    def fetchall(self):
        return []


@pytest.mark.parametrize("field,invalid", [
    ("inqryBgnDt", "202609010000"),
    ("inqryEndDt", "202610312359"),
    ("prdctClsfcNo", "81111598"),
])
def test_scan_month_rejects_stale_echo_before_history_insert(monkeypatch, field, invalid):
    first = date(2026, 10, 1)
    row = {
        "first_day": first, "last_day": date(2026, 10, 24),
        "status": "unsearched", "page_cursor": 1, "checked": 0,
        "matched": 0, "expected_total": None,
    }
    statements = []
    payload = valid_empty_page()
    payload["response"]["body"].update(EXPECTED)
    payload["response"]["body"][field] = invalid
    monkeypatch.setattr(official, "ensure_schema", lambda: None)
    monkeypatch.setattr(official, "_service_key", lambda: "fake-test-key")
    monkeypatch.setattr(official, "session", lambda: FakeSession(row, statements))
    monkeypatch.setattr(official, "urlopen", lambda *_args, **_kw: FakeResponse(payload))
    result = official.scan_month(first)
    assert result["status"] == "error"
    assert result["reason"] == "official_api_request_or_parse_failed:ValueError"
    assert not any("INSERT INTO" in sql.upper() for sql, _ in statements)
    updates = [(sql, params) for sql, params in statements if "UPDATE" in sql.upper()]
    assert len(updates) == 1
    assert updates[0][1][0] == "error"
    assert updates[0][1][4] == 1  # cursor remains page one
