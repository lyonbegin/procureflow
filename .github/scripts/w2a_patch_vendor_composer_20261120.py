#!/usr/bin/env python3
"""Pin-verified correction of existing-room ChatGPT composer interaction.

Never patch an unreviewed upstream revision. No browser request is generated here.
Apply after w2a_patch_vendor_dom.py, before pip installing the pinned vendor.
"""
from pathlib import Path
import subprocess
import sys

PIN = "497527dceabfa3f95961e23c291e618c5570f1ac"
root = Path(sys.argv[1]).resolve()
if subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip() != PIN:
    raise SystemExit("REFUSE_UNPINNED_WEB2API")
dom = root / "src/chatgpt_web2api/chatgpt_dom.py"
api = root / "src/chatgpt_web2api/api_server.py"

def replace_once(source, old, new, label):
    number = source.count(old)
    if number != 1:
        raise SystemExit("REFUSE_COMPOSER_PATCH_" + label + "_COUNT_" + str(number))
    return source.replace(old, new, 1)

source = api.read_text("utf-8")
# The HITEL worker always supplies exactly ONE current user message to a
# conversation_id-bound request. Inserting "[User]\\n" into the visual composer
# is not user content and unnecessarily forces multiline DOM input and parsing.
# Preserve original role-labeled behavior for actual multi-message SDK callers.
source = replace_once(
    source,
    '        full_text = prefix + "\\n".join(conversation_lines)',
    '        full_text = prefix + "\\n".join(conversation_lines)' + chr(10) +
    '        if len(messages) == 1 and user_msg_count == 1 and not system_parts:' + chr(10) +
    '            full_text = conversation_lines[0][len("[User]\\n"):]',
    "SINGLE_USER_TEXT_EXACT",
)
# Connection and login are not sufficient for a healthy chat editor.
# The health probe must report whether the exact owned tab has an actual
# visible editable composer. The room pool refuses send when it is absent.
source = replace_once(
    source,
    '                "driver_connected": driver_connected,',
    '                "driver_connected": driver_connected,' + chr(10) +
    '                "composer_ready": bool(driver_connected and await self._driver._has_composer()),',
    "HEALTH_REAL_COMPOSER_READINESS",
)
api.write_text(source, encoding="utf-8")

source = dom.read_text("utf-8")
# A hidden/disabled stale ProseMirror node is not a usable editor. A health
# signal must reflect the live editor, not merely a CSS selector match.
source = replace_once(
    source,
    '''                f"    ready: !!document.querySelector('{COMPOSER_SELECTOR}')"
                f"         || !!document.querySelector('{COMPOSER_FALLBACK_SELECTOR}')"
''',
    '''                f"    ready: Array.from(document.querySelectorAll('{COMPOSER_SELECTOR}, {COMPOSER_FALLBACK_SELECTOR}')).some(e=>e.isConnected && e.getClientRects().length>0 && !e.disabled && !e.closest('[aria-hidden=true],[inert]') && (e.isContentEditable || e.tagName==='TEXTAREA'))"
''',
    "READINESS_REQUIRES_VISIBLE_EDITABLE",
)
# The old querySelector picked the FIRST matching editor, which may be a hidden
# or stale ProseMirror node after the first ChatGPT turn. Always select a live,
# visible, editable composer and prefer its focused instance on verification.
source = replace_once(
    source,
    '''            f"  var el = document.querySelector('{COMPOSER_SELECTOR}');"
            "  if (el) { el.focus(); return 'composer'; }"
            f"  var fb = document.querySelector('{COMPOSER_FALLBACK_SELECTOR}');"
            "  if (fb) { fb.focus(); return 'fallback'; }"
            "  return 'no composer';"
''',
    '''            f"  var candidates = Array.from(document.querySelectorAll('{COMPOSER_SELECTOR}, {COMPOSER_FALLBACK_SELECTOR}'));"
            "  function usable(e){"
            "    if (!e || !e.isConnected || !e.getClientRects().length || e.closest('[aria-hidden=true],[inert]')) return false;"
            "    var st=getComputedStyle(e);"
            "    return st.display!=='none' && st.visibility!=='hidden' && !e.disabled && (e.isContentEditable || e.tagName==='TEXTAREA');"
            "  }"
            "  var options=candidates.filter(usable);"
            "  var el=options.filter(e=>e.isContentEditable).pop() || options.pop();"
            "  if (!el) return 'no composer';"
            "  el.focus();"
            "  return el.tagName==='TEXTAREA' ? 'fallback' : 'composer';"
''',
    "FOCUS_VISIBLE_EDITABLE_COMPOSER",
)
source = replace_once(
    source,
    '''                f"  var el = document.querySelector('{selector}');"
                "  if (!el) return '';"
                "  if (el.tagName === 'TEXTAREA') return el.value;"
''',
    '''                f"  var matches=Array.from(document.querySelectorAll('{selector}'));"
                "  function usable(e){"
                "    if (!e || !e.isConnected || !e.getClientRects().length || e.closest('[aria-hidden=true],[inert]')) return false;"
                "    var st=getComputedStyle(e);"
                "    return st.display!=='none' && st.visibility!=='hidden' && !e.disabled && (e.isContentEditable || e.tagName==='TEXTAREA');"
                "  }"
                "  var focused=document.activeElement;"
                "  var el=matches.includes(focused) && usable(focused) ? focused : matches.filter(usable).pop();"
                "  if (!el) return JSON.stringify({parts:'',visible:'',raw:''});"
                "  if (el.tagName === 'TEXTAREA') return JSON.stringify({parts:el.value,visible:el.value,raw:el.value});"
''',
    "VERIFY_SAME_VISIBLE_COMPOSER",
)
source = replace_once(
    source,
    '''                "  return parts.join('\\\\n');"
''',
    '''                "  return JSON.stringify({parts:parts.join('\\\\n'),visible:el.innerText||'',raw:el.textContent||''});"
''',
    "VERIFY_MULTIPLE_EXACT_DOM_REPRESENTATIONS",
)
source = replace_once(
    source,
    '''        if not actual and expected:
            return False
        # NFC normalization: handles composed/decomposed Unicode sequences
''',
    '''        try:
            representations = json.loads(actual)
            if not isinstance(representations, dict):
                return False
            values = [representations.get(k) for k in ("parts","visible")]
            values = [v for v in values if isinstance(v,str)]
        except (json.JSONDecodeError,TypeError):
            return False
        if not values:
            return False
        # NFC normalization: handles composed/decomposed Unicode sequences
''',
    "VERIFY_PARSE_REPRESENTATIONS",
)
source = replace_once(
    source,
    '''        canon_actual = unicodedata.normalize("NFC", actual.replace("\\r\\n", "\\n").replace("\\r", "\\n").replace("\\u00a0", " "))
        canon_expected = unicodedata.normalize("NFC", expected.replace("\\r\\n", "\\n").replace("\\r", "\\n").replace("\\u00a0", " "))
''',
    '''        canon_expected = unicodedata.normalize("NFC", expected.replace("\\r\\n", "\\n").replace("\\r", "\\n").replace("\\u00a0", " "))
''',
    "VERIFY_EXPECTED_CANONICAL",
)
source = replace_once(
    source,
    '''        return canon_actual == canon_expected or canon_actual == canon_expected + "\\n"
''',
    '''        for value in values:
            canon_actual = unicodedata.normalize("NFC", value.replace("\\r\\n", "\\n").replace("\\r", "\\n").replace("\\u00a0", " "))
            if canon_actual == canon_expected or canon_actual == canon_expected + "\\n":
                return True
        return False
''',
    "VERIFY_STRICT_EXACT_MATCH_ONLY",
)
# The retry clear MUST use the same focused editor; otherwise it can delete a
# hidden sibling's text, reinsert into the active editor, then verify the wrong
# sibling. We never remove user text from a different tab or another composer.
source = replace_once(
    source,
    '''                f"  var el = document.querySelector('{verify_selector}');"
                "  if (el) {"
''',
    '''                f"  var matches=Array.from(document.querySelectorAll('{verify_selector}'));"
                "  var focused=document.activeElement;"
                "  var el=matches.includes(focused) && focused.getClientRects().length ? focused : matches.filter(e=>e.getClientRects().length && !e.closest('[aria-hidden=true],[inert]')).pop();"
                "  if (el) {"
''',
    "RETRY_CLEAR_FOCUSED_EDITOR",
)
# Do not place raw user question text into vendor diagnostic logs.
source = replace_once(
    source,
    '''                    f"Composer text verification failed after retry; expected {text[:60]!r}"
''',
    '''                    "Composer text verification failed after retry"
''',
    "NO_PROMPT_IN_COMPOSER_EXCEPTION",
)
source = replace_once(
    source,
    '''        logger.info("Typed: %s", text[:80])
''',
    '''        logger.info("Composer typed, characters=%d", len(text))
''',
    "NO_PROMPT_IN_TYPED_LOG",
)
dom.write_text(source, encoding="utf-8")
print("PASS_PINNED_VENDOR_SINGLE_USER_EXACT_TEXT", flush=True)
print("PASS_PINNED_VENDOR_FOCUSED_VISIBLE_EDITABLE_COMPOSER", flush=True)
print("PASS_PINNED_VENDOR_MULTILINE_EXACT_VERIFY", flush=True)
print("PASS_PINNED_VENDOR_RETRY_SAME_EDITOR", flush=True)
