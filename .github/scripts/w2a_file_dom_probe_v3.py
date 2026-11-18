#!/usr/bin/env python3
"""Quick synthetic file-card/composer DOM probe; prints only non-sensitive UI metadata."""
import os
from pathlib import Path
import re
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright
from w2a_file_scenarios import select_uploader, composer, visible_filename
root=Path(os.environ["RUNNER_TEMP"])/"hitel-dom-probe"
root.mkdir(parents=True,exist_ok=True,mode=0o700)
name="hitel_dom_probe_generated.txt"
file=root/name
file.write_text("Synthetic file only.\nVALUE=HITEL_594\n",encoding="utf-8")
net={}
def log(k,v):
    print("DOM_FILE_"+k+"="+str(v).replace("\n","_")[:130],flush=True)
def on_response(r):
    try:
        p=urlparse(r.url)
        if p.hostname not in ("chatgpt.com","www.chatgpt.com"):return
        if any(x in p.path.lower() for x in ("file","upload","attachment")):
            category="PROCESS" if "process" in p.path.lower() else "UPLOAD" if "upload" in p.path.lower() else "FILE"
            key=category+"_"+str(r.status)
            net[key]=net.get(key,0)+1
    except Exception:pass
def stat_button(b,prefix,index):
    try:
        if not b.is_visible():return
        t=b.get_attribute("data-testid") or ""
        if not re.fullmatch("[A-Za-z0-9_-]{1,65}",t):t="none"
        a=(b.get_attribute("aria-label") or "").lower()
        label="send" if "send" in a or "보내" in a else "remove" if any(x in a for x in ("remove","delete","close","제거","삭제","닫기")) else "other" if a else "none"
        x=b.locator("svg path").first
        vector=(x.get_attribute("d") or "")[:100] if x.count() else "none"
        log(prefix+"_"+str(index), "testid:"+t+";label:"+label+";type:"+str(b.get_attribute("type"))+";enabled:"+str(int(b.is_enabled()))+";svg:"+vector)
    except Exception as e:
        log(prefix+"_"+str(index),"ERROR_"+type(e).__name__)
with sync_playwright() as p:
    browser=p.chromium.connect_over_cdp("http://127.0.0.1:9222")
    ctx=browser.contexts[0]
    page=ctx.new_page()
    page.on("response",on_response)
    try:
        page.goto("https://chatgpt.com/",wait_until="domcontentloaded",timeout=55000)
        upload=select_uploader(page)
        log("INPUT_FOUND",int(upload is not None))
        if upload is not None:
            upload.set_input_files(str(file),timeout=15000)
            for _ in range(20):
                if visible_filename(page,name):break
                page.wait_for_timeout(1000)
            log("FILENAME_VISIBLE",int(visible_filename(page,name)))
            txt=page.get_by_text(name,exact=False)
            if txt.count():
                node=txt.first.locator("xpath=../../..")
                bs=node.locator("button")
                log("CHIP_BUTTONS",bs.count())
                for i in range(min(bs.count(),4)):stat_button(bs.nth(i),"CHIP",i)
            field=composer(page)
            log("COMPOSER_FOUND",int(field is not None))
            if field is not None:
                field.fill("Read the attached TXT and reply with VALUE.")
                page.wait_for_timeout(1500)
                for level in (3,4,5,6,7,8):
                    container=field.locator("xpath="+"/".join([".."]*level))
                    bs=container.locator("button")
                    log("COMPOSER_LEVEL_"+str(level)+"_BUTTONS",min(bs.count(),100))
                    if 0<bs.count()<18:
                        for i in range(bs.count()):
                            stat_button(bs.nth(i),"PARENT_"+str(level),i)
                        break
                q=page.locator('button[type="submit"]')
                log("SUBMIT_BUTTONS",q.count())
                q=page.locator('button[data-testid*="send"],button[data-testid*="submit"]')
                log("SEND_TESTID_BUTTONS",q.count())
                q=page.get_by_role("button",name=re.compile("send|submit|보내기|전송",re.I))
                log("SEND_ROLE_BUTTONS",q.count())
                page.wait_for_timeout(5000)
        for k in sorted(net):log("NETWORK_"+k,net[k])
    finally:page.close()
