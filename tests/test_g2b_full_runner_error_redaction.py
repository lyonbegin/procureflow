"""Fail-closed, isolated tests for credential-safe G2B execution diagnostics.

Never call a real G2B endpoint, Railway service, Worker or bid API.
The fake exception contains the secret on purpose; neither JSON nor the
database SQL parameters may retain any part of that message.
"""
from contextlib import contextmanager
from unittest.mock import patch

from g2b_full_runner import official_selected_notice, documents_batch, execute


SECRET = "SECRET_DO_NOT_STORE_OR_LOG"
PROVIDER_EXCEPTION = RuntimeError(
    "HTTP 503 https://apis.data.go.kr/1230000/service?serviceKey="
    + SECRET + "&authorization=Bearer+" + SECRET
)


def test_official_notice_error_never_returns_upstream_secret_or_url():
    with patch("g2b_full_runner.api_key", return_value="configured"), \
         patch("g2b_full_runner._get", side_effect=PROVIDER_EXCEPTION):
        result = official_selected_notice()
    assert result == {"status": "error", "reason": "RuntimeError"}
    assert SECRET not in repr(result)
    assert "serviceKey" not in repr(result)
    assert "Bearer" not in repr(result)


def test_document_acquisition_error_does_not_return_upstream_secret():
    initial = {"files_listed": 1, "original_index": [
        {"state": "listed", "file_id": "test-document"}
    ]}
    after = {"files_listed": 1, "files_downloaded": 0,
             "all_documents_text_extracted": False}
    with patch("g2b_full_runner.list_documents", side_effect=[initial, after]), \
         patch("g2b_full_runner.acquire_one", side_effect=PROVIDER_EXCEPTION), \
         patch("g2b_original_reparse.run", return_value={"status": "partial"}):
        result = documents_batch()
    assert result["results"] == [
        {"file_id": "test-document", "status": "error", "reason": "RuntimeError"}
    ]
    assert SECRET not in repr(result)
    assert "serviceKey" not in repr(result)


class FakeResult:
    def fetchone(self):
        return {"id": 7001}


class FakeDB:
    def __init__(self):
        self.calls = []

    def execute(self, sql, params=()):
        self.calls.append((sql, params))
        return FakeResult()


def test_failed_phase_persists_only_exception_type_not_secret():
    db = FakeDB()

    @contextmanager
    def fake_session():
        yield db

    with patch("g2b_full_runner.session", fake_session), \
         patch("g2b_full_runner.one_phase", side_effect=PROVIDER_EXCEPTION), \
         patch("g2b_full_runner.readiness_check", return_value={"status": "blocked"}):
        result = execute("notice")

    assert result["status"] == "incomplete"
    assert result["results"]["notice"] == {
        "state": "error",
        "result": {"status": "error", "reason": "RuntimeError"}
    }
    assert len(db.calls) == 3  # run insert, result update, audit event insert
    assert SECRET not in repr(result)
    assert SECRET not in repr(db.calls)
    assert "serviceKey" not in repr(db.calls)
    assert "Bearer" not in repr(db.calls)
    update_params = next(params for sql, params in db.calls
                         if "UPDATE procureflow.g2b_case_runs" in sql)
    assert update_params[0] == "error"
    assert update_params[2] == "RuntimeError"
