"""Loopback-only regression: official G2B serviceKey must never follow 3xx.

The HTTP server is an in-process fixture, not G2B or Railway. Its only
purpose is to prove that a redirect cannot receive the request/query token.
"""
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from urllib.parse import urlsplit

import pytest

import g2b_case_10y_official as official


class FakeSession:
    def __init__(self, row, statements):
        self.row, self.statements = row, statements

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


@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
def test_official_api_redirect_never_follows_or_leaks_key(monkeypatch, status):
    seen = {"source": 0, "target": 0}
    secret = "fake-credential-do-not-send-to-redirect"

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            # Never log even the fake serviceKey query string.
            pass

        def do_GET(self):
            path = urlsplit(self.path).path
            if path == "/target":
                seen["target"] += 1
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'{"response":{"header":{"resultCode":"00"},"body":{"totalCount":0}}}')
                return
            seen["source"] += 1
            self.send_response(status)
            self.send_header("Location", "http://127.0.0.1:%d/target?serviceKey=%s" %
                             (self.server.server_port, secret))
            self.send_header("Content-Length", "0")
            self.end_headers()

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        first = date(2026, 10, 1)
        row = {
            "first_day": first, "last_day": date(2026, 10, 24),
            "status": "unsearched", "page_cursor": 1,
            "checked": 0, "matched": 0, "expected_total": None,
        }
        statements = []
        monkeypatch.setattr(official, "API",
                            "http://127.0.0.1:%d/source" % server.server_port)
        monkeypatch.setattr(official, "ensure_schema", lambda: None)
        monkeypatch.setattr(official, "_service_key", lambda: secret)
        monkeypatch.setattr(official, "session",
                            lambda: FakeSession(row, statements))
        # Intentionally DO NOT mock official.urlopen: exercise real urllib
        # redirect handling against a loopback-only test HTTP server.
        result = official.scan_month(first, pages_max=1)
        assert result == {
            "status": "error", "first_day": "2026-10-01",
            "reason": "official_api_request_or_parse_failed:HTTPError",
        }
        assert seen == {"source": 1, "target": 0}
        assert not any("INSERT INTO" in sql.upper() for sql, _ in statements)
        updates = [(sql, params) for sql, params in statements
                   if "UPDATE" in sql.upper()]
        assert len(updates) == 1
        assert updates[0][1][0] == "error"
        assert updates[0][1][4] == 1  # page cursor remains unchanged
        assert secret not in str(result)
        assert secret not in repr(statements)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
