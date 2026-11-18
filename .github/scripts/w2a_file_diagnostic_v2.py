#!/usr/bin/env python3
"""Live, synthetic-only ChatGPT file diagnostic. No session content leaves runner."""
from __future__ import annotations
import json
import os
from pathlib import Path
import re
import secrets
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright
from w2a_file_scenarios import select_uploader, composer, visible_filename

ROOT=Path(os.environ["RUNNER_TEMP"])/"w2a-file-diagnostic-v2"
ROOT.mkdir(mode=0o700,parents=True,exist_ok=True)
name="hitel_diag_v2_generated.txt"
key="HITEL_DIAG_"+secrets.token_hex(6).upper()+"_683"
path=ROOT/name
path.write_text("HITEL_DIAGNOSTIC_VALUE="+key+"\nOnly synthetic data.\n",encoding="utf-8")
report={}
def mark(label,value):
    if isinstance(value,bool): value=int(value)
    report[label]=value
    print("FILE_DIAG_"+label+"="+str(value),flush=True)
def response_probe(resp):
    try:
        parsed=urlparse(resp.url)
        if parsed.hostname not in {"chatgpt.com","www.chatgpt.com"}: return
        p=parsed.path.lower()
        if not ("upload" in p or "/files" in p or "attachment" in p): return
        kind="PROCESS" if "process" in p else "UPLOAD" if "upload" in p else "FILES"
        status="OK" if 200<=resp.status<300 else "CLIENT_ERR" if 400<=resp.status<500 else "SERVER_ERR" if resp.status>=500 else "OTHER"
        k=kind+"_"+status
        report[k]=report.get(k,0)+1
    except Exception: pass

with sync_playwright() as pw:
    browser=pw.chromium.connect_over_cdp("http://127.0.0.1:9222")
    ctx=browser.contexts[0]
    page=ctx.new_page()
    page.on("response",response_probe)
    try:
        page.goto("https://chatgpt.com/",wait_until="domcontentloaded",timeout=55000)
        page.wait_for_timeout(1500)
        upload=select_uploader(page)
        mark("UPLOAD_INPUT_FOUND",upload is not None)
        if upload is not None:
            try:
                upload.set_input_files(str(path),timeout=15000)
                mark("INPUT_SET_SUCCESS",True)
            except Exception:mark("INPUT_SET_SUCCESS",False)
            for i in range(30):
                if visible_filename(page,name):break
                page.wait_for_timeout(1000)
            mark("CHIP_FILENAME_VISIBLE",visible_filename(page,name))
            chip=page.get_by_text(name,exact=False)
            mark("CHIP_TEXT_COUNT",min(chip.count(),20))
            if chip.count():
                for level in (1,2,3,4,5):
                    root=chip.first.locator("xpath=" + "/".join([".."]*level))
                    buttons=root.locator("button")
                    mark("CHIP_ANCESTOR_"+str(level)+"_BUTTONS",min(buttons.count(),30))
                    mark("CHIP_ANCESTOR_"+str(level)+"_NAMED_BUTTONS",
                         min(buttons.locator("[aria-label],[title],[data-testid]").count(),30))
                    mark("CHIP_ANCESTOR_"+str(level)+"_SVG_BUTTONS",
                         min(buttons.locator("svg").count(),30))
            field=composer(page)
            mark("COMPOSER_FOUND",field is not None)
            if field is not None and visible_filename(page,name):
                field.fill("Read the attached TXT. Reply ONLY with the HITEL_DIAGNOSTIC_VALUE in it.")
                page.wait_for_timeout(1500)
                tests=['[data-testid="send-button"]','button[aria-label="Send prompt"]',
                       'button[aria-label="Send message"]','[data-testid="composer-submit-button"]']
                sent=False
                for item in tests:
                    c=page.locator(item)
                    if c.count() and c.last.is_visible() and c.last.is_enabled():
                        c.last.click(timeout=4000)
                        sent=True
                        break
                if not sent:
                    field.press("Enter")
                mark("SEND_BUTTON_USED",sent)
                mark("COMPOSER_EMPTY_AFTER_SEND",len((field.inner_text(timeout=5000) or "").strip())==0)
                for _ in range(55):
                    page.wait_for_timeout(2500)
                    assistant=page.locator('[data-message-author-role="assistant"],[data-testid="assistant-message"],div[class*="DilResponseRoot-"]')
                    if assistant.count():
                        texts=assistant.all_inner_texts()
                        if any(key in text for text in texts):break
                assistant=page.locator('[data-message-author-role="assistant"],[data-testid="assistant-message"],div[class*="DilResponseRoot-"]')
                mark("ASSISTANT_SELECTOR_N",min(assistant.count(),50))
                mark("ASSISTANT_MARKER_FOUND",any(key in text for text in assistant.all_inner_texts()))
                mark("USER_TURN_SELECTOR_N",min(page.locator('[data-message-author-role="user"]').count(),50))
                mark("CONVERSATION_URL_AFTER_SEND",bool(re.search(r"/c/[a-z0-9-]+",page.url,re.I)))
    finally:
        page.close()
for k in ("UPLOAD_OK","UPLOAD_CLIENT_ERR","UPLOAD_SERVER_ERR","PROCESS_OK","PROCESS_CLIENT_ERR","PROCESS_SERVER_ERR","FILES_OK","FILES_CLIENT_ERR","FILES_SERVER_ERR"):
    report.setdefault(k,0)
mark("NETWORK_OBSERVATIONS",sum(report.get(k,0) for k in ("UPLOAD_OK","UPLOAD_CLIENT_ERR","UPLOAD_SERVER_ERR","PROCESS_OK","PROCESS_CLIENT_ERR","PROCESS_SERVER_ERR","FILES_OK","FILES_CLIENT_ERR","FILES_SERVER_ERR")))
(ROOT/"safe_report.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
