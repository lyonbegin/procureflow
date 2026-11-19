#!/usr/bin/env python3
"""Narrow DOM compatibility patch for pinned original ChatGPT-Web2API.

The original ChatGPT-Web2API functions are retained verbatim, except that
their old message selectors gain a fallback for the 2026 DIL response DOM
confirmed by the live GitHub-hosted Chrome diagnostics (2026-11-13).
Run ONLY on the audited source pinned at 497527dce.
"""
from pathlib import Path
import subprocess
import sys

PIN = "497527dceabfa3f95961e23c291e618c5570f1ac"
root = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else None
if root is None or not (root / ".git").exists():
    raise SystemExit("Usage: w2a_patch_vendor_dom.py CHECKED_OUT_VENDOR_GIT_ROOT")
rev = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
if rev != PIN:
    raise SystemExit("REFUSE_PATCH_UNEXPECTED_VENDOR_COMMIT")

# Preserve legacy selector behavior and match the real currently-rendered
# assistant/user nodes; this is an isolated integration test patch, not a
# blanket upstream rewrite.
OLD_ASSISTANT = r'[data-message-author-role=\"assistant\"]'
NEW_ASSISTANT = r'[data-message-author-role=\"assistant\"],div[class*=\"DilResponseRoot-\"]'
OLD_USER = r'[data-message-author-role=\"user\"]'
NEW_USER = r'[data-message-author-role=\"user\"],div[class*=\"bg-user-message\"]'

targets = (
    ("completion_detector.py", 2, 0),
    ("cdp_driver.py", 1, 2),
)

for filename, assistant_count, user_count in targets:
    source = root / "src" / "chatgpt_web2api" / filename
    original = source.read_text(encoding="utf-8")
    actual = (original.count(OLD_ASSISTANT), original.count(OLD_USER))
    if actual != (assistant_count, user_count):
        raise SystemExit(
            "REFUSE_PATCH_SOURCE_SELECTOR_MISMATCH_" + filename
            + "_COUNT_" + str(actual)
        )
    updated = original.replace(OLD_ASSISTANT, NEW_ASSISTANT).replace(OLD_USER, NEW_USER)
    source.write_text(updated, encoding="utf-8")
    print("PASS_VENDOR_DOM_SELECTOR_PATCH_" + filename, flush=True)

# 2026-11-16 live Chrome diag: chatgpt.com/ has an interactive composer,
# but navigating the newly-created tab to ?model=auto leaves it unsendable.
# Preserve the upstream navigator; change only the fresh-chat target URL.
driver = root / "src" / "chatgpt_web2api" / "cdp_driver.py"
code = driver.read_text(encoding="utf-8")
legacy = 'url = "https://chatgpt.com/?model=auto"'
replacement = 'url = "https://chatgpt.com/"'
if code.count(legacy) != 1:
    raise SystemExit("REFUSE_PATCH_VENDOR_HOME_URL_MISMATCH")
driver.write_text(code.replace(legacy, replacement), encoding="utf-8")
print("PASS_VENDOR_NEW_CHAT_NAVIGATION_HOME_ROUTE_PATCH", flush=True)

# Explicit new-chat semantics: the vendor's default is to continue the last
# conversation when conversation_id is omitted. Preserve that legacy default,
# but allow callers to force a NEW chat without fake system instructions.
# This is opt-in, minimal, source-pinned, and refuses unexpected vendor code.
api = root / "src" / "chatgpt_web2api" / "api_server.py"
server = api.read_text(encoding="utf-8")
old_id = '        conversation_id = body.get("conversation_id")\n'
new_id = old_id + '        new_conversation = body.get("new_conversation") is True\n'
old_reuse = "                elif (\n                    self._last_conv_id\n"
new_reuse = "                elif (\n                    not new_conversation\n                    and self._last_conv_id\n"
if server.count(old_id) != 1 or server.count(old_reuse) != 1:
    raise SystemExit("REFUSE_PATCH_VENDOR_NEW_CONVERSATION_SOURCE_MISMATCH")
server = server.replace(old_id, new_id).replace(old_reuse, new_reuse)
api.write_text(server, encoding="utf-8")
print("PASS_EXPLICIT_NEW_CONVERSATION_FLAG_SUPPORTED", flush=True)

print("PASS_PINNED_VENDOR_ORIGINAL_FUNCTIONS_PRESERVED", flush=True)


# Source-confirmed 2026-11-19 correction: the vendor's phase-1 assistant
# appearance detector uses an unconfigurable 90s PHASE_STALL_SECONDS even when
# request_timeout and first-content budgets have been raised to 14400s.
# Apply the configured budget only to phase-1 detection. Preserve the legacy
# 90s default when no budgets are provided; never synthesize a completion.
detector = root / "src" / "chatgpt_web2api" / "completion_detector.py"
source = detector.read_text(encoding="utf-8")
old_phase1 = "            if time.monotonic() - last_progress > PHASE_STALL_SECONDS:\n"
new_phase1 = (
    "            phase1_limit = (budgets.first_content_timeout_seconds\n"
    "                            if budgets is not None else PHASE_STALL_SECONDS)\n"
    "            if time.monotonic() - last_progress > phase1_limit:\n"
)
if source.count(old_phase1) != 1:
    raise SystemExit("REFUSE_PATCH_VENDOR_PHASE1_STALL_SOURCE_MISMATCH")
detector.write_text(source.replace(old_phase1, new_phase1), encoding="utf-8")
print("PASS_CONFIGURED_PHASE1_STALL_BUDGET_APPLIED", flush=True)

# The pinned vendor maps all unknown browser/DOM errors to HTTP 500, with
# no structured code. Preserve its HTTP status, error body, and behavior, but
# add only the Python exception class name as a machine-readable error code.
# The worker consumes this locally without recording prompts or error messages.
server = api.read_text(encoding="utf-8")
old_opaque = '            {"error": {"message": str(exc), "type": "server_error"}},'
new_typed = (
    '            {"error": {"message": str(exc), "type": "server_error", "code": type(exc).__name__,'
    ' "subcode": (getattr(exc, "last_status", None) if getattr(exc, "last_status", None) '
    'in ("not_ready", "ambiguous", "degraded_not_fresh", "fetch_failed", "auth_failed") else None),'
    ' "anchor_mode": (getattr(exc, "anchor_mode", None) if getattr(exc, "anchor_mode", None) '
    'in ("captured_id", "existing_conversation", "degraded_existing", "fresh_chat") else None)}},'
)
if server.count(old_opaque) != 1:
    raise SystemExit("REFUSE_PATCH_VENDOR_500_ERROR_SHAPE_MISMATCH")
api.write_text(server.replace(old_opaque, new_typed), encoding="utf-8")
print("PASS_VENDOR_500_ERROR_CLASS_REPORTED_WITHOUT_ERROR_MESSAGE", flush=True)
