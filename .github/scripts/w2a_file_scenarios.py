#!/usr/bin/env python3
"""Isolated Chrome UI file tests on only generated, non-sensitive files.

No user's pre-existing files are read, modified, downloaded or deleted.
Only synthetic text and CSV are used. Real dialog uploads remain in test chats.
No passwords, cookies, identities, prompts, filenames from the user's own
content, or private chat responses are emitted in Actions logs.
"""
import json
import os
from pathlib import Path
import re
import secrets
import sys
import time

from playwright.sync_api import sync_playwright

ROOT=Path(os.environ["RUNNER_TEMP"])/"w2a-file-cases"
ROOT.mkdir(parents=True,exist_ok=True,mode=0o700)
RESULTS=[]
NONCE=secrets.token_hex(4).upper()
TXTNAME="hitel_trial_generated.txt"
CSVNAME="hitel_trial_generated.csv"
KEY="HITEL_FILE_"+NONCE+"_795"


def report(case,name,status,detail):
    assert status in {"PASS","FAIL","BLOCKED","UNSUPPORTED"}
    assert re.fullmatch(r"[A-Z0-9_]{3,110}",detail),detail
    RESULTS.append({"id":case,"name":name,"status":status,"detail":detail})
    print("FILE_SCENARIO_"+case+"_"+status+"="+detail,flush=True)


def select_uploader(page):
    """Find real file input, clicking the ChatGPT composer plus if necessary."""
    def suitable():
        result=page.locator("input[type=file]")
        best=[]
        for i in range(min(result.count(),8)):
            field=result.nth(i)
            accept=(field.get_attribute("accept") or "").lower()
            # Avoid a hidden avatar-only image uploader for TXT/CSV.
            score=0 if (not accept or "text" in accept or ".txt" in accept
                        or ".csv" in accept or "*" in accept) else 1
            best.append((score,i))
        return result.nth(sorted(best)[0][1]) if best else None
    item=suitable()
    if item is not None:
        return item
    actions=[
        page.locator('[data-testid="composer-plus-btn"]'),
        page.locator('button[aria-label*="Add photos"]'),
        page.locator('button[aria-label*="Attach"]'),
        page.get_by_role("button",name=re.compile(
            r"Add photos|Add files|Add attachment|Attach|Upload|파일|첨부|사진|Plus",re.I)),
    ]
    for action in actions:
        try:
            if action.count() and action.first.is_visible():
                action.first.click(timeout=3000)
                page.wait_for_timeout(650)
                field=suitable()
                if field is not None:
                    return field
        except Exception:
            pass
    for role in ("menuitem","button"):
        item=page.get_by_role(role,name=re.compile(
            r"Add photos|Add files|Upload file|파일 업로드|파일 추가",re.I))
        try:
            if item.count() and item.first.is_visible():
                item.first.click(timeout=3000)
                field=suitable()
                if field is not None:
                    return field
        except Exception:
            pass
    return None


def composer(page):
    for loc in (page.locator("#prompt-textarea"),
                page.locator('[data-testid="composer-input"]'),
                page.locator('[contenteditable="true"]')):
        try:
            if loc.count() and loc.first.is_visible():
                return loc.first
        except Exception:
            pass
    return None


def open_new(ctx):
    page=ctx.new_page()
    page.goto("https://chatgpt.com/",wait_until="domcontentloaded",timeout=55000)
    page.wait_for_timeout(1300)
    return page


def visible_filename(page,name):
    try:
        return name in page.locator("body").inner_text(timeout=8000)
    except Exception:
        return False


def upload(page,path):
    field=select_uploader(page)
    if field is None:return "NO_FILE_INPUT"
    try:
        field.set_input_files(str(path),timeout=15000)
    except Exception:
        return "FILE_INPUT_REJECTED"
    # Upload and processing are asynchronous in the ChatGPT UI.
    for i in range(20):
        if visible_filename(page,path.name):
            return "VISIBLE"
        page.wait_for_timeout(1000)
    try:
        n=field.evaluate("(e)=>e.files?.length || 0")
    except Exception:
        n=0
    return "INPUT_SELECTED_BUT_NO_CHIP" if n else "UPLOAD_NOT_REFLECTED"


def remove_attachment(page,name):
    # Only click controls associated with the test file chip or explicit
    # remove/delete labels, never general chat trash or delete-chat controls.
    candidates=[
        page.locator('[data-testid*="remove-attachment"]'),
        page.locator('[aria-label*="Remove attachment"]'),
        page.locator('button[aria-label*="Remove file"]'),
        page.locator('[title*="Remove attachment"]'),
    ]
    for c in candidates:
        try:
            if c.count() and c.first.is_visible():
                c.first.click(timeout=4000)
                page.wait_for_timeout(1200)
                if not visible_filename(page,name):return "REMOVED"
        except Exception:
            pass
    # Scoped only to the synthetic file chip, not unrelated sidebar buttons.
    synthetic=page.get_by_text(name,exact=False)
    if synthetic.count():
        for levels in (1,2,3):
            try:
                parent=synthetic.first.locator("xpath="+"/".join([".."]*levels))
                buttons=parent.locator("button")
                for i in range(min(buttons.count(),4)):
                    button=buttons.nth(i)
                    hint=((button.get_attribute("aria-label") or "")+" "+
                          (button.get_attribute("title") or "")).lower()
                    if re.search(r"remove|close|delete|취소|제거|닫기|삭제",hint):
                        button.click(timeout=2000)
                        page.wait_for_timeout(1000)
                        if not visible_filename(page,name):return "REMOVED"
            except Exception:
                pass
    return "REMOVE_CONTROL_NOT_FOUND"


def assistant_contains(page,key):
    try:
        loc=page.locator(
            '[data-message-author-role="assistant"],[data-testid="assistant-message"],div[class*="DilResponseRoot-"]')
        return any(key in text for text in loc.all_inner_texts())
    except Exception:
        return False


def ask(page,text):
    input= composer(page)
    if input is None:return False
    input.fill(text)
    input.press("Enter")
    return True


def run():
    txt=ROOT/TXTNAME
    txt.write_text("HITEL_TEST_KEY="+KEY+"\nThis note contains synthetic test data only.\n",encoding="utf-8")
    csv=ROOT/CSVNAME
    csv.write_text("item,count\napple,3\npear,5\n",encoding="utf-8")
    with sync_playwright() as pw:
        browser=pw.chromium.connect_over_cdp("http://127.0.0.1:9222",timeout=20000)
        ctx=browser.contexts[0]
        page=open_new(ctx)
        try:
            code=upload(page,txt)
            if code!="VISIBLE":
                report("S08","Upload synthetic TXT in ChatGPT UI","FAIL",code)
                report("S09","Remove unsent file","BLOCKED","FILE_CARD_UNAVAILABLE")
            else:
                report("S08","Upload synthetic TXT in ChatGPT UI","PASS","TXT_ATTACHMENT_VISIBLE")
                removed=remove_attachment(page,txt.name)
                report("S09","Remove unsent file","PASS" if removed=="REMOVED" else "BLOCKED",removed)
        finally:page.close()

        page=open_new(ctx)
        try:
            code=upload(page,txt)
            if code!="VISIBLE":
                report("S10","Ask about TXT contents","BLOCKED",code)
            elif not ask(page,"Read the attached TXT and reply with ONLY its HITEL_TEST_KEY value."):
                report("S10","Ask about TXT contents","BLOCKED","CHAT_COMPOSER_MISSING")
            else:
                present=False
                for _ in range(45):
                    page.wait_for_timeout(2500)
                    if assistant_contains(page,KEY):
                        present=True
                        break
                report("S10","Ask about TXT contents","PASS" if present else "FAIL",
                       "FILE_VALUE_IN_ASSISTANT_ANSWER" if present else "FILE_VALUE_NOT_VERIFIED")
        finally:page.close()

        page=open_new(ctx)
        try:
            code=upload(page,csv)
            if code!="VISIBLE":
                report("S15","Upload and query synthetic CSV","BLOCKED",code)
            elif not ask(page,
                         "Read the attached CSV. Add the count values and reply ONLY with the number."):
                report("S15","Upload and query synthetic CSV","BLOCKED","CHAT_COMPOSER_MISSING")
            else:
                answered=False
                for _ in range(40):
                    page.wait_for_timeout(2500)
                    if assistant_contains(page,"8"):
                        answered=True
                        break
                report("S15","Upload and query synthetic CSV",
                       "PASS" if answered else "FAIL",
                       "SYNTHETIC_CSV_TOTAL_8_ANSWERED" if answered else "CSV_TOTAL_NOT_VERIFIED")
        finally:page.close()

        page=open_new(ctx)
        try:
            if not ask(page,
                       "Create a REAL downloadable CSV file, not a markdown code block. "
                       "Name it hitel_scenario_output.csv and include header item,count "
                       "and rows apple,3 and pear,5. Provide the file for download."):
                report("S11","Download generated CSV file","BLOCKED","CHAT_COMPOSER_MISSING")
            else:
                candidate=None
                for _ in range(38):
                    page.wait_for_timeout(2500)
                    for q in [
                        page.get_by_role("link",name=re.compile(
                            r"hitel_scenario_output[.]csv|[.]csv$|Download|다운로드",re.I)),
                        page.locator('a[download]'),
                        page.locator('a[href*=".csv"]'),
                    ]:
                        try:
                            if q.count() and q.first.is_visible():
                                candidate=q.first
                                break
                        except Exception:pass
                    if candidate is not None:break
                if candidate is None:
                    report("S11","Download generated CSV file","BLOCKED","NO_DOWNLOADABLE_CSV_LINK")
                else:
                    try:
                        with page.expect_download(timeout=12000) as dl:
                            candidate.click(timeout=5000)
                        target=ROOT/"received-file"
                        dl.value.save_as(str(target))
                        okay=target.is_file() and target.stat().st_size>0
                        report("S11","Download generated CSV file",
                               "PASS" if okay else "FAIL",
                               "NONEMPTY_CSV_FILE_RECEIVED" if okay else "DOWNLOADED_FILE_EMPTY")
                    except Exception:
                        report("S11","Download generated CSV file","BLOCKED","BROWSER_DOWNLOAD_NOT_STARTED")
        finally:page.close()


def main():
    try:run()
    except Exception as e:
        print("FILE_PROBE_SAFE_EXCEPTION_CLASS="+type(e).__name__,flush=True)
    seen={x["id"] for x in RESULTS}
    for case,name in [
        ("S08","Upload synthetic TXT in ChatGPT UI"),
        ("S09","Remove unsent file"),
        ("S10","Ask about TXT contents"),
        ("S15","Upload and query synthetic CSV"),
        ("S11","Download generated CSV file")
    ]:
        if case not in seen:
            report(case,name,"BLOCKED","UPSTREAM_BROWSER_TEST_INTERRUPTED")
    out=Path(os.environ["RUNNER_TEMP"])/"hitel_file_scenario_results.json"
    out.write_text(json.dumps({"results":RESULTS,
        "summary":{s:sum(item["status"]==s for item in RESULTS)
                   for s in ("PASS","FAIL","BLOCKED","UNSUPPORTED")}},
        ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("PASS_FILE_CASE_REPORT_SAVED",flush=True)


if __name__=="__main__":
    main()
