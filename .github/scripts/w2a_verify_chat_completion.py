#!/usr/bin/env python3
"""Single harmless end-to-end Web2API question/answer verification.

This intentionally sends exactly one test turn to the user's authenticated
ChatGPT browser and validates the expected fixed response. No credentials,
cookies, account identity or actual conversations are logged.
"""
import json
import sys
import urllib.error
import urllib.request

url = "http://127.0.0.1:18080/v1/chat/completions"
marker = "WEB2API_OK_7419"
payload = {
    "model": "auto",
    "stream": False,
    "messages": [{"role": "user",
                  "content": f"Connection test: reply with exactly {marker} and no other text."}],
}
req = urllib.request.Request(
    url, data=json.dumps(payload).encode("utf-8"), method="POST",
    headers={"Content-Type": "application/json"},
)
try:
    with urllib.request.urlopen(req, timeout=155) as response:
        raw = response.read(262144)
        status = response.status
except urllib.error.HTTPError as e:
    print("WEB2API_CHAT_HTTP_STATUS=" + str(e.code), flush=True)
    try:
        error=json.loads(e.read(8192))
        entry=error.get("error", {})
        if isinstance(entry, dict):
            for key in ("code","type"):
                value=str(entry.get(key,""))
                if value and len(value)<=64 and all(ch.isascii() and (ch.isalnum() or ch in "_-") for ch in value):
                    print("WEB2API_CHAT_ERROR_"+key.upper()+"="+value, flush=True)
            msg=str(entry.get("message", "")).lower()
            classes={
                "timeout":("timeout","timed out"),
                "generation_stuck":("generation stuck","generation_stuck","stalled"),
                "composer":("composer","input box"),
                "auth":("auth","login","session expired"),
                "cdp":("cdp","websocket","browser"),
                "rate_limit":("rate limit","too many requests"),
            }
            matches=[name for name,terms in classes.items() if any(term in msg for term in terms)]
            print("WEB2API_CHAT_SAFE_ERROR_CLASSES="+",".join(matches or ["unknown"]),flush=True)
    except Exception:
        print("WEB2API_CHAT_ERROR_UNREADABLE",flush=True)
    print("FAIL_WEB2API_CHAT_HTTP", flush=True)
    sys.exit(1)
except Exception as e:
    print("FAIL_WEB2API_CHAT_REQUEST_" + type(e).__name__, flush=True)
    sys.exit(1)

print("WEB2API_CHAT_HTTP_STATUS=" + str(status), flush=True)
try:
    result = json.loads(raw)
    choices = result.get("choices", [])
    content = choices[0]["message"]["content"] if choices else None
    if isinstance(content, list):
        content = " ".join(str(item.get("text", "")) for item in content if isinstance(item, dict))
    valid = isinstance(content, str) and marker in content
    print("WEB2API_CHAT_RESPONSE_RECEIVED=" + str(bool(content)).lower(), flush=True)
    print("WEB2API_CHAT_MARKER_MATCH=" + str(valid).lower(), flush=True)
    if not valid:
        print("FAIL_WEB2API_CHAT_REPLY_NOT_VERIFIED", flush=True)
        sys.exit(2)
    print("PASS_WEB2API_CHAT_SEND_AND_RECEIVE", flush=True)
except Exception as e:
    print("FAIL_WEB2API_CHAT_RESULT_" + type(e).__name__, flush=True)
    sys.exit(2)
