"""Privacy-safe, deterministic diagnostics for Web2API worker failures.
Never emit exception messages, HTTP body, credentials, URLs, or chat content.
"""
import json
import re
import urllib.error

EXACT_SAFE = frozenset({
    "UNSUPPORTED_WEB_WORKER_ACTION", "WEB2API_BINARY_ATTACHMENT_NOT_VERIFIED",
    "INVALID_CHAT_TEXT", "UNVERIFIED_TARGET_CONVERSATION", "UNVERIFIED_TARGET_URL",
    "WEB2API_RESPONSE_INVALID", "WEB2API_CHOICES_MISSING",
    "WEB2API_ASSISTANT_REPLY_MISSING", "WEB2API_CONVERSATION_ID_MISSING",
    "ROOM_CONVERSATION_ID_MISMATCH", "MALFORMED_RELAY_JOB",
    "ACCOUNT_EXECUTION_NOT_VERIFIED", "ACCOUNT_ID_INVALID",
    "ACCOUNT_EMAIL_INVALID", "ACCOUNT_LOGOUT_UI_UNAVAILABLE",
    "ACCOUNT_LOGOUT_NOT_VERIFIED", "ACCOUNT_LOGIN_WRONG_IDENTITY",
    "ACCOUNT_INTERACTIVE_LOGIN_REQUIRED", "ACCOUNT_CHANGED_DURING_SEND",
    "CHROME_CONTEXT_MISSING", "ACCOUNT_PREFLIGHT_UNAVAILABLE",
    "ACCOUNT_PREFLIGHT_DENIED", "WEB2API_HTTP_NOT_200",
})
SAFE_VENDOR = re.compile(r"^WEB2API_(?:ADAPTER_HTTP_[45][0-9][0-9]|ADAPTER_TRANSPORT|RESPONSE_JSON_INVALID)$")

def classify_web2api_failure(exc: Exception) -> str:
    """Return only a fixed code or a standard Python exception class name."""
    message = str(exc)
    if message in EXACT_SAFE or SAFE_VENDOR.fullmatch(message):
        return message
    if isinstance(exc, urllib.error.HTTPError):
        code = int(getattr(exc, "code", 0) or 0)
        if code == 500:
            # The pinned localhost vendor is patched to supply a Python
            # exception CLASS in error.code. Never forward error.message,
            # request data, response body, credentials or browser URL.
            try:
                payload = json.loads(exc.read(4096).decode("utf-8"))
                kind = payload.get("error", {}).get("code")
                known = {
                    "SendReadinessError", "CDPJSError", "CDPReconnectError",
                    "TurnReconciliationError", "RuntimeError", "TypeError",
                    "ValueError", "TimeoutError", "KeyError", "AssertionError",
                    "ConnectionError", "IndexError", "AuthExpiredError",
                    "LockAcquisitionError", "GenerationStuckError",
                    "CircuitOpenError", "OwnedTabRequiredError",
                }
                if isinstance(kind, str) and kind in known:
                    if kind == "TurnReconciliationError":
                        subcode = payload.get("error", {}).get("subcode")
                        anchor = payload.get("error", {}).get("anchor_mode")
                        statuses = {
                            "not_ready", "ambiguous", "degraded_not_fresh",
                            "fetch_failed", "auth_failed",
                        }
                        anchors = {
                            "captured_id", "existing_conversation",
                            "degraded_existing", "fresh_chat",
                        }
                        if subcode in statuses and anchor in anchors:
                            return "WEB2API_VENDOR_TURNRECONCILIATIONERROR_" + subcode.upper() + "_" + anchor.upper()
                    return "WEB2API_VENDOR_" + kind.upper()
            except (ValueError, UnicodeDecodeError, TypeError, AttributeError):
                pass
        return "WEB2API_ADAPTER_HTTP_" + str(code if 400 <= code <= 599 else "OTHER")
    if isinstance(exc, urllib.error.URLError):
        return "WEB2API_ADAPTER_TRANSPORT"
    if isinstance(exc, json.JSONDecodeError):
        return "WEB2API_RESPONSE_JSON_INVALID"
    if isinstance(exc, TimeoutError):
        return "WEB2API_ADAPTER_TIMEOUT"
    typ = type(exc).__name__
    # A class name is diagnostic metadata; message text can contain sensitive data.
    typ = typ if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,55}", typ) else "Exception"
    return "WEB2API_UNCLASSIFIED_" + typ.upper()
