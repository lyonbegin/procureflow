#!/usr/bin/env python3
"""HITEL browserless ChatGPT Web2API transport.

No Chrome, CDP, Playwright, DOM, direct UI clicks, or OpenAI metered API.
This module communicates ONLY with a loopback-pinned gptweb2api HTTP gateway
and reads conversation state via authenticated HTTPS GET to chatgpt.com.

Safety contract: a POST is attempted once per job; an uncertain outcome is
NEVER resent. The caller must establish current conversation parent before
sending. The existing A/Scribd research rooms are read-only until promoted.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import ssl
import threading
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOM_RE = re.compile(r"^room_[a-f0-9]{32}$")
CID_RE = re.compile(r"^[a-zA-Z0-9_-]{8,128}$")
MESSAGE_RE = re.compile(r"^[a-zA-Z0-9_-]{8,128}$")
BASE = "http://127.0.0.1:8787"
WEB_HOST = "https://chatgpt.com"
MAX_ANSWER_BYTES = 2_000_000
MAX_PROMPT_LENGTH = 24000


class DirectError(RuntimeError):
    """Stable, sanitized failure category without user text or tokens."""

    def __init__(self, code: str, *, after_post: bool = False):
        super().__init__(code)
        self.code = code
        self.after_post = after_post


@dataclass(frozen=True)
class Binding:
    room_id: str
    conversation_id: str
    parent_message_id: str


def validate_gateway_url(url: str) -> str:
    split = urllib.parse.urlsplit(url)
    if (split.scheme != "http" or split.hostname != "127.0.0.1"
            or split.port != 8787 or split.path not in ("", "/")
            or split.username is not None or split.password is not None
            or split.query or split.fragment):
        raise DirectError("DIRECT_GATEWAY_MUST_BE_EXACT_LOOPBACK")
    return BASE


def conversation_from_url(url: str) -> str:
    if not isinstance(url, str):
        raise DirectError("DIRECT_CONVERSATION_URL_INVALID")
    u = urllib.parse.urlsplit(url)
    if (u.scheme != "https" or u.hostname != "chatgpt.com"
            or u.port not in (None, 443) or u.username or u.password
            or u.query or u.fragment or not u.path.startswith("/c/")):
        raise DirectError("DIRECT_CONVERSATION_URL_UNTRUSTED")
    cid = u.path.removeprefix("/c/")
    if not CID_RE.fullmatch(cid):
        raise DirectError("DIRECT_CONVERSATION_ID_INVALID")
    return cid


def _load_credential(path: str) -> tuple[str, str | None]:
    p = Path(path)
    if not p.is_file():
        raise DirectError("DIRECT_OAUTH_FILE_MISSING")
    try:
        payload = json.loads(p.read_text("utf-8"))
        tokens = payload.get("tokens")
        if not isinstance(tokens, dict):
            tokens = payload
        token = tokens.get("access_token") or payload.get("access_token")
        account = tokens.get("account_id") or payload.get("account_id")
    except (OSError, UnicodeError, ValueError, AttributeError):
        raise DirectError("DIRECT_OAUTH_FILE_INVALID") from None
    if not isinstance(token, str) or not token or len(token) > 8000:
        raise DirectError("DIRECT_OAUTH_TOKEN_UNAVAILABLE")
    if account is not None and (not isinstance(account, str) or len(account) > 250):
        raise DirectError("DIRECT_ACCOUNT_ID_INVALID")
    return token, account


def _http_json(url: str, *, method: str, headers: dict[str, str],
               body: dict[str, Any] | None = None,
               timeout: int = 45, send: bool = False) -> tuple[dict[str, Any], Any]:
    data = None
    if body is not None:
        data = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            if response.status != 200:
                raise DirectError("DIRECT_HTTP_UNEXPECTED_STATUS", after_post=send)
            # Explicit response body ceiling, not an unbounded json.load.
            raw = response.read(MAX_ANSWER_BYTES + 1)
            if len(raw) > MAX_ANSWER_BYTES:
                raise DirectError("DIRECT_RESPONSE_TOO_LARGE", after_post=send)
            content = json.loads(raw)
            if not isinstance(content, dict):
                raise DirectError("DIRECT_RESPONSE_NOT_OBJECT", after_post=send)
            return content, response.headers
    except urllib.error.HTTPError as exc:
        # Never expose upstream error bodies, cookies, prompts, or credentials.
        code = exc.code
        label = ("AUTH" if code in (401, 403) else
                 "RATE_LIMIT" if code == 429 else
                 "BAD_REQUEST" if code in (400, 404, 422) else
                 "SERVER_ERROR" if code >= 500 else "OTHER")
        raise DirectError(f"DIRECT_{'SEND' if send else 'READ'}_HTTP_{code}_{label}",
                          after_post=send) from None
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        raise DirectError("DIRECT_SEND_TRANSPORT_UNCERTAIN" if send else
                          "DIRECT_READ_TRANSPORT_UNAVAILABLE", after_post=send) from None
    except (UnicodeError, ValueError):
        raise DirectError("DIRECT_RESPONSE_INVALID_JSON", after_post=send) from None


def _current_parent(mapping: dict, current: str) -> str:
    """Use the exact current leaf, never guess the newest message by timestamp."""
    if not isinstance(mapping, dict) or not isinstance(current, str):
        raise DirectError("DIRECT_REMOTE_CURRENT_NODE_MISSING")
    node = mapping.get(current)
    if not isinstance(node, dict):
        raise DirectError("DIRECT_REMOTE_CURRENT_NODE_NOT_FOUND")
    message = node.get("message")
    if not isinstance(message, dict):
        raise DirectError("DIRECT_REMOTE_CURRENT_MESSAGE_MISSING")
    author = message.get("author", {})
    if not isinstance(author, dict) or author.get("role") != "assistant":
        raise DirectError("DIRECT_REMOTE_CURRENT_NOT_ASSISTANT")
    parent = message.get("id")
    if parent != current or not MESSAGE_RE.fullmatch(str(parent)):
        raise DirectError("DIRECT_REMOTE_PARENT_ID_UNVERIFIED")
    return parent


class DirectWeb2API:
    def __init__(self, *, oauth_file: str, api_key: str,
                 gateway_url: str = BASE, timeout: int = 1500):
        self._base = validate_gateway_url(gateway_url)
        self._oauth_file = oauth_file
        if not isinstance(api_key, str) or len(api_key) < 16:
            raise DirectError("DIRECT_LOCAL_GATEWAY_KEY_MISSING")
        self._api_key = api_key
        self._timeout = max(30, min(3600, int(timeout)))
        self._lock = threading.RLock()
        self._rooms: dict[str, Binding] = {}
        self._uncertain: set[str] = set()

    def _gateway_headers(self) -> dict[str, str]:
        return {"Authorization": "Bearer " + self._api_key,
                "Content-Type": "application/json", "Accept": "application/json"}

    def ready(self) -> None:
        # This is *not* just process liveness. The gateway's authenticated
        # readyz verifies its configured credential and direct-mode provider.
        document, _ = _http_json(self._base + "/readyz", method="GET",
                                 headers=self._gateway_headers(), timeout=20)
        if document.get("ready") is not True:
            raise DirectError("DIRECT_GATEWAY_NOT_AUTHENTICATED_READY")

    def account_id(self) -> str | None:
        return _load_credential(self._oauth_file)[1]

    def fetch_remote_parent(self, cid: str) -> str:
        if not CID_RE.fullmatch(cid):
            raise DirectError("DIRECT_CONVERSATION_ID_INVALID")
        token, account = _load_credential(self._oauth_file)
        headers = {"Authorization": "Bearer " + token,
                   "Accept": "application/json"}
        if account:
            headers["ChatGPT-Account-ID"] = account
        url = WEB_HOST + "/backend-api/conversation/" + urllib.parse.quote(cid, safe="")
        document, _ = _http_json(url, method="GET", headers=headers, timeout=40)
        if document.get("conversation_id") not in (None, cid):
            raise DirectError("DIRECT_REMOTE_CONVERSATION_ID_MISMATCH")
        return _current_parent(document.get("mapping"), document.get("current_node"))

    def bootstrap(self, room_id: str, conversation_url: str) -> str:
        if not ROOM_RE.fullmatch(room_id):
            raise DirectError("DIRECT_ROOM_ID_INVALID")
        cid = conversation_from_url(conversation_url)
        self.ready()
        parent = self.fetch_remote_parent(cid)
        with self._lock:
            old = self._rooms.get(room_id)
            if old and old.conversation_id != cid:
                raise DirectError("DIRECT_ROOM_REBIND_FORBIDDEN")
            self._rooms[room_id] = Binding(room_id, cid, parent)
        # Opaque protocol-v4 transport handle, emphatically NOT a Chrome tab ID.
        return "direct-http-" + hashlib.sha256(room_id.encode()).hexdigest()[:28]

    def binding(self, room_id: str, target_url: str | None) -> Binding | None:
        with self._lock:
            if room_id in self._uncertain:
                raise DirectError("DIRECT_ROOM_DELIVERY_UNCERTAIN")
            existing = self._rooms.get(room_id)
        if target_url is None:
            if existing:
                raise DirectError("DIRECT_EXISTING_ROOM_REQUIRES_URL")
            return None
        cid = conversation_from_url(target_url)
        if existing is not None and existing.conversation_id != cid:
            raise DirectError("DIRECT_ROOM_CONVERSATION_CHANGED")
        if existing is not None:
            return existing
        # New worker after restart: recover the *actual remote parent*
        # read-only before allowing any subsequent SEND.
        self.bootstrap(room_id, target_url)
        with self._lock:
            return self._rooms[room_id]

    def send(self, room_id: str, prompt: str, target_url: str | None) -> tuple[str, str]:
        if not ROOM_RE.fullmatch(room_id):
            raise DirectError("DIRECT_ROOM_ID_INVALID")
        if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > MAX_PROMPT_LENGTH:
            raise DirectError("DIRECT_PROMPT_INVALID")
        state = self.binding(room_id, target_url)
        headers = self._gateway_headers()
        if state:
            headers["X-GPTWeb-Conversation-ID"] = state.conversation_id
            headers["X-GPTWeb-Parent-Message-ID"] = state.parent_message_id
        try:
            obj, returned = _http_json(
                self._base + "/v1/chat/completions", method="POST",
                headers=headers, body={
                    "model": "auto", "stream": False,
                    "messages": [{"role": "user", "content": prompt}],
                }, timeout=self._timeout, send=True)
            choices = obj.get("choices")
            if not isinstance(choices, list) or len(choices) != 1:
                raise DirectError("DIRECT_CHOICES_UNVERIFIED", after_post=True)
            message = choices[0].get("message") if isinstance(choices[0], dict) else None
            answer = message.get("content") if isinstance(message, dict) else None
            if not isinstance(answer, str) or not answer.strip():
                raise DirectError("DIRECT_ANSWER_MISSING", after_post=True)
            cid = returned.get("X-GPTWeb-Conversation-ID", "")
            parent = returned.get("X-GPTWeb-Assistant-Message-ID", "")
            if not CID_RE.fullmatch(cid) or not MESSAGE_RE.fullmatch(parent):
                raise DirectError("DIRECT_RETURNED_TURN_IDS_MISSING", after_post=True)
            if state and state.conversation_id != cid:
                raise DirectError("DIRECT_CONVERSATION_CHANGED_AFTER_POST", after_post=True)
            with self._lock:
                self._rooms[room_id] = Binding(room_id, cid, parent)
            return answer, cid
        except DirectError as exc:
            if exc.after_post:
                with self._lock:
                    self._uncertain.add(room_id)
            raise

    def quarantine(self, room_id: str):
        with self._lock:
            self._uncertain.add(room_id)
