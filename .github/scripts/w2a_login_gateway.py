#!/usr/bin/env python3
"""Local gate for a temporary, protected GitHub Actions Chrome desktop.

Only the SHA-256 of a high-entropy access code is committed. The code itself
must never appear in GitHub Actions logs, source, artifacts, or commit statuses.
"""
import hashlib
import hmac
import http.server
import os
import secrets
import subprocess
import sys
import urllib.parse
from http.cookies import SimpleCookie
from pathlib import Path

EXPECTED = os.environ["W2A_ACCESS_SHA256"]
SESSION = secrets.token_urlsafe(40)
READY_TO_SAVE = Path(os.environ["RUNNER_TEMP"]) / "w2a-save-requested"


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def reply(self, code, body=b"", headers=()):
        self.send_response(code)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in headers:
            self.send_header(k, v)
        self.end_headers()
        if body:
            self.wfile.write(body)

    def valid_code(self, query):
        proposed = urllib.parse.parse_qs(query).get("code", [""])[0]
        if len(proposed) > 200:
            return False
        digest = hashlib.sha256(proposed.encode("utf-8")).hexdigest()
        return hmac.compare_digest(digest, EXPECTED)

    def valid_cookie(self):
        try:
            cookie = SimpleCookie()
            cookie.load(self.headers.get("Cookie", ""))
            supplied = cookie.get("w2a_session")
            return bool(supplied and hmac.compare_digest(supplied.value, SESSION))
        except Exception:
            return False

    def do_GET(self):
        parts = urllib.parse.urlsplit(self.path)
        if parts.path == "/health":
            self.reply(200, b"ok")
            return
        if parts.path == "/verify":
            self.reply(200 if self.valid_cookie() else 401)
            return
        if parts.path == "/grant":
            if not self.valid_code(parts.query):
                self.reply(403, b"Invalid or expired session link.")
                return
            self.reply(302, headers=[
                ("Set-Cookie", "w2a_session=" + SESSION
                 + "; Secure; HttpOnly; SameSite=Lax; Path=/; Max-Age=2400"),
                ("Location", "/vnc.html?autoconnect=true&resize=remote"),
            ])
            return
        if parts.path == "/finish":
            if not self.valid_code(parts.query):
                self.reply(403, b"Invalid or expired session link.")
                return
            # Do not declare success merely because the user clicked Finish.
            # Prove authenticated session in the SAME live Chrome using CDP.
            try:
                check = subprocess.run(
                    [sys.executable, ".github/scripts/w2a_verify_session.py"],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    timeout=85, check=False,
                )
            except subprocess.TimeoutExpired:
                self.reply(503, b"ChatGPT login check timed out. Please retry.")
                return
            if check.returncode != 0:
                self.reply(409, b"ChatGPT login is NOT verified. Return to the Chrome screen, finish Google sign-in, and click Save again.")
                return
            READY_TO_SAVE.touch(mode=0o600)
            self.reply(200, b"PASS: ChatGPT login verified. Encrypted session save requested.",
                       headers=[("Content-Type", "text/plain; charset=utf-8")])
            return
        self.reply(404)


if __name__ == "__main__":
    http.server.ThreadingHTTPServer(("127.0.0.1", 8899), Handler).serve_forever()
