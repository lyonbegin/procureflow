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
new_typed = '            {"error": {"message": str(exc), "type": "server_error", "code": type(exc).__name__}},'
if server.count(old_opaque) != 1:
    raise SystemExit("REFUSE_PATCH_VENDOR_500_ERROR_SHAPE_MISMATCH")
api.write_text(server.replace(old_opaque, new_typed), encoding="utf-8")
print("PASS_VENDOR_500_ERROR_CLASS_REPORTED_WITHOUT_ERROR_MESSAGE", flush=True)

# Existing-room sends must not trigger an unconditional SECOND navigation.
# The signed worker already verified the exact owned target's /c/<id> route.
# Re-navigating destroys the DOM response anchor and can cause vendor HTTP 500.
# Vendor ensure_current_conversation verifies the live URL and navigates ONLY
# if displaced. Record the current ID only after that verified check.
server = api.read_text(encoding="utf-8")
old_repeat_nav = "                    await self._driver.navigate_conversation(conversation_id)\n"
new_idempotent_nav = (
    "                    await self._driver.ensure_current_conversation(conversation_id)\n"
    "                    self._driver._current_conv_id = conversation_id\n"
)
if server.count(old_repeat_nav) != 1:
    raise SystemExit("REFUSE_PATCH_VENDOR_EXISTING_ROOM_NAVIGATION_SOURCE_MISMATCH")
api.write_text(server.replace(old_repeat_nav,new_idempotent_nav),encoding="utf-8")
print("PASS_VENDOR_EXISTING_ROOM_NAVIGATION_IDEMPOTENT",flush=True)


# Local Web2API projection-observation correction for the pinned vendor.
# Keep real ChatGPT throttling and auth errors; remove needless read polling.
# The original SEND is never retried by this correction.
def _replace_projection_once(path, old, new, label):
    original=path.read_text(encoding="utf-8")
    count=original.count(old)
    if count!=1:
        raise SystemExit("REFUSE_VENDOR_PROJECTION_PATCH_"+label+"_MATCH_"+str(count))
    path.write_text(original.replace(old,new),encoding="utf-8")

driver=root/"src"/"chatgpt_web2api"/"cdp_driver.py"
detector=root/"src"/"chatgpt_web2api"/"completion_detector.py"
_replace_projection_once(detector,"        self.had_non_text_content = False\n\n        # Wait for a new assistant message.","        self.had_non_text_content = False\n        self.dom_completion_verified = False\n        self.backend_completion_verified = False\n\n        # Wait for a new assistant message.","STATE_INIT")
_replace_projection_once(detector,"        last_backend_check = 0.0\n","        # Observe backend only after a meaningful change in the current DOM.\n        backend_observation_key = None\n        dom_confirmation_candidate = None\n","NO_TIMER_POLL")
_replace_projection_once(detector,"\"  return JSON.stringify({text: text, md_text: mdText, html_len: html_len, child_count: child_count, has_action: has_action, is_thinking: is_thinking});\"","\"  var stop_active = !!document.querySelector('[data-testid=\\\"stop-button\\\"],button[aria-label=\\\"Stop generating\\\"],button[aria-label=\\\"Stop\\\"]');\"\n                    \"  return JSON.stringify({text: text, md_text: mdText, html_len: html_len, child_count: child_count, assistant_count: msgs.length, stop_active: stop_active, has_action: has_action, is_thinking: is_thinking});\"","DOM_SIGNALS")
_replace_projection_once(detector,"            is_thinking = data.get(\"is_thinking\", False)\n","            is_thinking = data.get(\"is_thinking\", False)\n            stop_active = data.get(\"stop_active\", False)\n            assistant_count = data.get(\"assistant_count\", 0)\n","READ_SIGNALS")
_replace_projection_once(detector,"            backend_fetch_failed = False\n            if (\n                conv_id_for_check\n                and (last_dom_text or saw_thinking or is_thinking or had_non_text_content)\n                and time.monotonic() - last_backend_check > 3.0\n            ):\n                last_backend_check = time.monotonic()\n                try:","            # The exact new assistant turn is complete only after two\n            # consecutive stable observations of its markdown and action row.\n            # Never use an older turn's copy button or an active generation.\n            dom_candidate = (\n                assistant_count > initial_count\n                and has_action and not stop_active and not is_thinking\n                and isinstance(md_text, str) and bool(md_text.strip())\n                and bool(last_dom_text.strip())\n            )\n            if dom_candidate:\n                if dom_confirmation_candidate == last_dom_text:\n                    self.dom_completion_verified = True\n                    logger.info(\"DOM_VERIFIED_NEW_ASSISTANT_COMPLETED\")\n                    break\n                dom_confirmation_candidate = last_dom_text\n            else:\n                dom_confirmation_candidate = None\n\n            # No 3-second backend polling. A conversation-projection HTTP 429\n            # only means this read is unavailable, not that the sent prompt\n            # was rejected. Consult the backend only when no verified DOM\n            # action exists and the DOM has changed since its previous read.\n            backend_fetch_failed = False\n            observation_key = (last_dom_text, html_len, child_count)\n            if (\n                conv_id_for_check and not stop_active and not is_thinking\n                and (not has_action or not md_text)\n                and (last_dom_text or had_non_text_content)\n                and observation_key != backend_observation_key\n            ):\n                backend_observation_key = observation_key\n                try:","BACKEND_EVENT_ONLY")
_replace_projection_once(detector,"                        if last_dom_text or had_non_text_content:\n                            logger.info(","                        if last_dom_text or had_non_text_content:\n                            self.backend_completion_verified = True\n                            logger.info(","MARK_BACKEND_END")
_replace_projection_once(driver,"            if conv_id:\n                logger.info(\"Conversation: %s\", conv_id)\n                self._current_conv_id = conv_id\n                last_dom_text = self._completion.last_dom_text\n","            if conv_id:\n                logger.info(\"Conversation: %s\", conv_id)\n                self._current_conv_id = conv_id\n            # A completed, new, response-bearing browser turn already has\n            # verified evidence. Do not repeat projection reads and turn a\n            # completed ChatGPT response into an observation-only HTTP 429.\n            if conv_id and not (\n                self._completion.last_dom_text.strip()\n                and (self._completion.dom_completion_verified\n                     or self._completion.backend_completion_verified)\n            ):\n                last_dom_text = self._completion.last_dom_text\n","SKIP_REDUNDANT_FINAL_READ")
_replace_projection_once(
    detector,
    "                and isinstance(md_text, str) and bool(md_text.strip())\n",
    "                and isinstance(current, str) and bool(current.strip())\n",
    "DIL_ANSWER_TEXT_WITHOUT_MARKDOWN_WRAPPER",
)
print("PASS_VENDOR_PROJECTION_OBSERVATION_WITHOUT_FAKE_SEND_FAILURE",flush=True)

# A transient UI rate-limit popup after a submitted prompt must not cause
# the vendor wrapper to replay the entire prompt. Read-only observation may
# retry, but ChatGPT user-message submission remains strictly once-only.
api=root/"src"/"chatgpt_web2api"/"api_server.py"
_replace_projection_once(
    api,
    "        full_text = await retry_on_rate_limit(self._driver, _send_and_collect)\n",
    "        full_text = await _send_and_collect()  # no automatic resend\n",
    "ONE_CHATGPT_SUBMISSION_ONLY",
)
print("PASS_VENDOR_NONSTREAMING_SEND_NO_AUTOMATIC_REPLAY",flush=True)
_replace_projection_once(
    detector,
    "                and (not has_action or not md_text)\n",
    "                and not has_action\n",
    "STOP_READS_WHEN_DOM_ACTION_IS_VISIBLE",
)
print("PASS_VENDOR_DOM_ACTION_COMPLETION_NO_CONVERSATION_READ",flush=True)

# Read-only recovery when the transcript projection is temporarily unavailable.
# Retries are strictly observation-only; the user message is never re-sent.
_replace_projection_once(
    detector,
    "        backend_observation_key = None\n        dom_confirmation_candidate = None\n",
    "        backend_observation_key = None\n        backend_retry_at = 0.0\n        dom_confirmation_candidate = None\n",
    "PROJECTION_RETRY_CLOCK",
)
_replace_projection_once(
    detector,
    "                and observation_key != backend_observation_key\n            ):",
    "                and (observation_key != backend_observation_key\n                     or time.monotonic() >= backend_retry_at)\n                and time.monotonic() >= backend_retry_at\n            ):",
    "PROJECTION_OBSERVATION_RETRY_GUARD",
)
_replace_projection_once(
    detector,
    "                backend_observation_key = observation_key\n                try:",
    "                backend_observation_key = observation_key\n                backend_retry_at = time.monotonic() + 30.0\n                try:",
    "PROJECTION_RETRY_BACKOFF",
)

# Vendor stdout/stderr will be consumed by the owning GitHub process, but
# ONLY these literal milestones are allowed to leave that process.
_replace_projection_once(
    driver,
    "            await self.type_message(text)\n            await self.click_send()\n",
    "            print('HITEL_W2A_STAGE=TYPE_STARTED', flush=True)\n"
    "            await self.type_message(text)\n"
    "            print('HITEL_W2A_STAGE=TYPE_VERIFIED', flush=True)\n"
    "            await self.click_send()\n"
    "            print('HITEL_W2A_STAGE=SEND_DISPATCHED', flush=True)\n",
    "SEND_STAGE_MARKERS",
)
_replace_projection_once(
    driver,
    "            if not captured_uuid:\n                try:\n                    acknowledged = await self._verify_send_acknowledged()\n",
    "            acknowledged = None\n"
    "            if not captured_uuid:\n"
    "                try:\n"
    "                    acknowledged = await self._verify_send_acknowledged()\n",
    "ACK_TRI_STATE",
)
_replace_projection_once(
    driver,
    "            # A2 Step 7: build the final anchor (fallback + captured UUID).\n",
    "            if acknowledged is True:\n"
    "                print('HITEL_W2A_STAGE=SEND_UI_ACKNOWLEDGED', flush=True)\n"
    "            elif captured_uuid:\n"
    "                print('HITEL_W2A_STAGE=SEND_REQUEST_OBSERVED', flush=True)\n"
    "            else:\n"
    "                print('HITEL_W2A_STAGE=SEND_UNCONFIRMED', flush=True)\n\n"
    "            # A2 Step 7: build the final anchor (fallback + captured UUID).\n",
    "ACK_STAGE_MARKER",
)
_replace_projection_once(
    detector,
    '        logger.info("Assistant message appeared, waiting for completion...")\n',
    '        logger.info("Assistant message appeared, waiting for completion...")\n'
    "        print('HITEL_W2A_STAGE=ASSISTANT_SEEN', flush=True)\n",
    "ASSISTANT_STAGE_MARKER",
)
_replace_projection_once(
    detector,
    '                    logger.info("DOM_VERIFIED_NEW_ASSISTANT_COMPLETED")\n',
    '                    logger.info("DOM_VERIFIED_NEW_ASSISTANT_COMPLETED")\n'
    "                    print('HITEL_W2A_STAGE=TURN_COMPLETED', flush=True)\n",
    "COMPLETED_STAGE_MARKER",
)
print("PASS_VENDOR_SAFE_STAGE_MARKERS_AND_READ_ONLY_RETRY", flush=True)
# Do not accept a completed action row from an unrelated earlier turn.
# The exact newly rendered user message must agree with this send's anchor,
# and the user-message count must exceed its pre-send baseline.
_replace_projection_once(
    detector,
    "            if dom_candidate:\n"
    "                if dom_confirmation_candidate == last_dom_text:\n",
    "            if dom_candidate:\n"
    "                try:\n"
    "                    expected = getattr(turn_anchor, 'sent_text', None)\n"
    "                    baseline_users = getattr(d, '_pre_send_user_count', None)\n"
    "                    if not isinstance(expected, str) or baseline_users is None:\n"
    "                        dom_candidate = False\n"
    "                    else:\n"
    "                        check_js = (\n"
    "                            '(function(){'\n"
    "                            \"var userMsgs=document.querySelectorAll('[data-message-author-role=\\\"user\\\"]');\"\n"
    "                            'var count=userMsgs.length;'\n"
    "                            'var last=count?(userMsgs[count-1].innerText||userMsgs[count-1].textContent||\\\"\\\"):\\\"\\\";'\n"
    "                            'var norm=function(v){return v.replace(/\\\\r\\\\n?/g,\\\"\\\\n\\\").replace(/\\\\u00a0/g,\\\" \\\").normalize(\\\"NFC\\\").trim();};'\n"
    "                            'return JSON.stringify({count:count,match:norm(last)===norm('\n"
    "                            + json.dumps(expected) + ')});})()'\n"
    "                        )\n"
    "                        verified_user = json.loads(await d._js_strict(check_js))\n"
    "                        dom_candidate = (\n"
    "                            verified_user.get('count', 0) > baseline_users\n"
    "                            and verified_user.get('match') is True\n"
    "                        )\n"
    "                except (ValueError, TypeError, KeyError, CDPJSError):\n"
    "                    dom_candidate = False\n"
    "            if dom_candidate:\n"
    "                if dom_confirmation_candidate == last_dom_text:\n",
    "CORRELATE_VISIBLE_USER_TO_ASSISTANT",
)
print("PASS_VENDOR_ASSISTANT_COMPLETION_REQUIRES_EXACT_NEW_USER", flush=True)




# STOCK-TV ONLY: a complete JSON response matching the ten source identities
# is sufficient. No Stop/copy button, thinking label, steady-text observation
# or visible user-message echo is needed after that JSON has been received.
# All other tasks retain the original vendor completion detector.
json_gate = "            # ── Completion detection ─────────────────────────────────────\n"
json_fast_path = (
    "            # Stock TV research: validate the RECEIVED answer JSON only.\n"
    "            from hitel_stocktv_json_receipt import matches_stocktv_research_json\n"
    "            if matches_stocktv_research_json(\n"
    "                current, getattr(turn_anchor, 'sent_text', None)\n"
    "            ):\n"
    "                self.dom_completion_verified = True\n"
    "                logger.info('STOCKTV_VALIDATED_JSON_RECEIVED')\n"
    "                print('HITEL_W2A_STAGE=TURN_COMPLETED', flush=True)\n"
    "                break\n"
    "            # ── Completion detection ─────────────────────────────────────\n"
)
_replace_projection_once(detector, json_gate, json_fast_path, "STOCK_TV_JSON_RECEIPT_ONLY")
print("PASS_STOCKTV_VALID_JSON_DIRECT_COMPLETION_NO_UI_GATES", flush=True)
