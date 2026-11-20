#!/usr/bin/env python3
"""QA-only candidate patch: wait for a visible editable DOM node before every Web2API send.
Only modifies disposable checked-out pinned vendor source inside isolated GitHub Actions.
Never touches production worker, Railway, or existing A/Scribd conversation tabs.
"""
from pathlib import Path
import subprocess
import sys

root=Path(sys.argv[1]).resolve()
actual=subprocess.check_output(["git","-C",str(root),"rev-parse","HEAD"],text=True).strip()
assert actual=="497527dceabfa3f95961e23c291e618c5570f1ac", "REFUSE_OTHER_VENDOR_SOURCE"
path=root/"src/chatgpt_web2api/chatgpt_dom.py"
s=path.read_text("utf-8")
changes=[
 (
 '                f"    ready: !!document.querySelector(\'{COMPOSER_SELECTOR}\')"',
 '                f"    ready: !!Array.from(document.querySelectorAll(\'{COMPOSER_SELECTOR}\')).find(e=>e.getClientRects().length>0 && e.isContentEditable && e.getAttribute(\'aria-hidden\')!==\'true\')"'
 ),
 (
 '                f"         || !!document.querySelector(\'{COMPOSER_FALLBACK_SELECTOR}\')"',
 '                f"         || !!Array.from(document.querySelectorAll(\'{COMPOSER_FALLBACK_SELECTOR}\')).find(e=>e.getClientRects().length>0 && !e.disabled && e.getAttribute(\'aria-hidden\')!==\'true\')"'
 ),
 (
 '            f"  var el = document.querySelector(\'{COMPOSER_SELECTOR}\');"',
 '            f"  var el = Array.from(document.querySelectorAll(\'{COMPOSER_SELECTOR}\')).find(e=>e.getClientRects().length>0 && e.isContentEditable && e.getAttribute(\'aria-hidden\')!==\'true\');"'
 ),
 (
 '            f"  var fb = document.querySelector(\'{COMPOSER_FALLBACK_SELECTOR}\');"',
 '            f"  var fb = Array.from(document.querySelectorAll(\'{COMPOSER_FALLBACK_SELECTOR}\')).find(e=>e.getClientRects().length>0 && !e.disabled && e.getAttribute(\'aria-hidden\')!==\'true\');"'
 ),
 (
 '        focus_result = await d._js(\n',
 '        if not await d._wait_for_composer(timeout=45):\n'
 '            await d._capture_selector_diagnostic("composer still absent after visible-editor wait")\n'
 '            from .cdp_driver import SendReadinessError\n'
 '            raise SendReadinessError("No visible, editable composer after 45 seconds")\n'
 '        focus_result = await d._js(\n'
 )
]
for original,replacement in changes:
    n=s.count(original)
    if n!=1:raise SystemExit(f"REFUSE_QA_PATCH_UNEXPECTED_INPUT_COUNT_{n}:{original[:50]}")
    s=s.replace(original,replacement,1)
path.write_text(s,encoding="utf-8")
print("PASS_QA_VENDOR_COMPOSER_VISIBLE_ONLY_AND_45S_WAIT_PATCH",flush=True)
