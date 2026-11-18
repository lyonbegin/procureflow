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
    # Avoid racing React hydration on recently opened ChatGPT tabs.
    for _ in range(50):
        if composer(page) is not None:
            break
        page.wait_for_timeout(400)
    return page


def visible_filename(page,name):
    try:
        return name in page.locator("body").inner_text(timeout=8000)
    except Exception:
        return False


def upload(page,path):
    # A newly opened ChatGPT page hydrates its composer and plus menu
    # asynchronously; a single missing input is not a failed upload.
    field=None
    for _ in range(40):
        field=select_uploader(page)
        if field is not None:
            break
        page.wait_for_timeout(450)
    if field is None:return "NO_FILE_INPUT_AFTER_RETRY"
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
    """Remove only the test file, never an existing chat or sidebar entry."""
    clicked=False
    was_visible=visible_filename(page,name)
    for _ in range(45):
        synthetic=page.get_by_text(name,exact=False)
        buttons=[]
        if synthetic.count():
            try:
                card=synthetic.first.locator("xpath=../../..")
                buttons.append(card.get_by_role("button",name=re.compile(
                    r"remove|delete|close|제거|삭제|닫기",re.I)))
            except Exception:
                pass
        # The React file card can re-mount between the filename becoming
        # visible and the following click. Allow one unique explicitly
        # file-removal-labelled control in this synthetic-only new chat.
        buttons.append(page.get_by_role("button",name=re.compile(
            r"remove.*(file|upload|attachment)|delete.*file|파일.*(제거|삭제)|(첨부|업로드).*제거",
            re.I)))
        for loc in buttons:
            try:
                if loc.count()!=1:
                    continue
                button=loc.first
                if button.is_visible() and button.is_enabled() and not clicked:
                    button.click(timeout=5000)
                    clicked=True
                    print("FILE_REMOVE_EXPLICIT_CONTROL_CLICKED=1",flush=True)
            except Exception:
                continue
        if clicked and not visible_filename(page,name):
            return "REMOVED"
        page.wait_for_timeout(300)
    print("FILE_REMOVE_FILENAME_INITIAL="+str(int(was_visible)),flush=True)
    print("FILE_REMOVE_FILENAME_FINAL="+str(int(visible_filename(page,name))),flush=True)
    print("FILE_REMOVE_CLICKED="+str(int(clicked)),flush=True)
    return "REMOVE_CLICKED_FILE_REMAINED" if clicked else "REMOVE_CONTROL_NOT_FOUND"

def assistant_contains(page,key,strict=False):
    try:
        loc=page.locator(
            '[data-message-author-role="assistant"],[data-testid="assistant-message"],div[class*="DilResponseRoot-"]')
        texts=loc.all_inner_texts()
        return any((value.strip()==key if strict else key in value) for value in texts)
    except Exception:
        return False


ASK_LAST_ERROR="NOT_ATTEMPTED"
def ask(page,text):
    """Submit only through the live composer submit button, when enabled."""
    global ASK_LAST_ERROR
    ASK_LAST_ERROR="COMPOSER_NOT_READY"
    field=None
    for _ in range(50):
        field=composer(page)
        if field is not None:
            break
        page.wait_for_timeout(400)
    if field is None:return False
    try:
        field.fill(text)
    except Exception:
        ASK_LAST_ERROR="COMPOSER_FILL_FAILED"
        return False
    ASK_LAST_ERROR="SUBMIT_NOT_READY"
    # A visible attachment filename is not evidence of finished processing.
    # Wait until the actual submit control becomes enabled.
    for _ in range(70):
        try:
            choices=[
                page.locator('button[type="submit"]'),
                page.get_by_role("button",name=re.compile(
                    r"send|submit|보내기|전송",re.I))
            ]
            for loc in choices:
                for i in range(min(loc.count(),5)):
                    button=loc.nth(i)
                    if not (button.is_visible() and button.is_enabled()):
                        continue
                    button.click(timeout=5000)
                    for _ in range(30):
                        try:
                            if not field.inner_text(timeout=1000).strip():
                                ASK_LAST_ERROR="SENT_CONFIRMED"
                                return True
                        except Exception:
                            if (page.locator('[data-message-author-role="user"]').count()
                                or re.search(r"/c/[a-z0-9-]+",page.url,re.I)):
                                ASK_LAST_ERROR="SENT_CONFIRMED"
                                return True
                        page.wait_for_timeout(250)
                    ASK_LAST_ERROR="SUBMIT_CLICKED_NOT_CONFIRMED"
                    return False
        except Exception:
            pass
        page.wait_for_timeout(450)
    return False

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
                report("S10","Ask about TXT contents","BLOCKED",ASK_LAST_ERROR)
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
                report("S15","Upload and query synthetic CSV","BLOCKED",ASK_LAST_ERROR)
            else:
                answered=False
                for _ in range(40):
                    page.wait_for_timeout(2500)
                    if assistant_contains(page,"8",strict=True):
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
                report("S11","Download generated CSV file","BLOCKED",ASK_LAST_ERROR)
            else:
                candidate=None
                for _ in range(38):
                    page.wait_for_timeout(2500)
                    # Never click a generic sidebar "Download" app link.
                    assistant=page.locator(
                        '[data-message-author-role="assistant"],[data-testid="assistant-message"],div[class*="DilResponseRoot-"]')
                    within=assistant.last if assistant.count() else page
                    for q in [
                        within.get_by_role("link",name=re.compile(
                            r"hitel_scenario_output[.]csv|[.]csv$",re.I)),
                        within.locator('a[download]'),
                        within.locator('a[href*=".csv"]'),
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
                    # Report only the scheme and link semantics, never
                    # signed URLs or ChatGPT response contents.
                    from urllib.parse import urlsplit
                    href=candidate.get_attribute("href") or ""
                    parsed=urlsplit(href)
                    safe_scheme=parsed.scheme.lower() if re.fullmatch(r"[a-z]{1,12}",parsed.scheme.lower()) else "relative"
                    print("FILE_DOWNLOAD_CANDIDATE_SCHEME="+safe_scheme,flush=True)
                    print("FILE_DOWNLOAD_CANDIDATE_HAS_DOWNLOAD_ATTR="+str(int(candidate.get_attribute("download") is not None)),flush=True)
                    print("FILE_DOWNLOAD_CANDIDATE_CSV_PATH="+str(int(parsed.path.lower().endswith(".csv"))),flush=True)
                    try:
                        before_pages=len(ctx.pages)
                        with page.expect_download(timeout=12000) as dl:
                            candidate.click(timeout=5000)
                        target=ROOT/"received-file"
                        dl.value.save_as(str(target))
                        okay=target.is_file() and target.stat().st_size>0
                        report("S11","Download generated CSV file",
                               "PASS" if okay else "FAIL",
                               "NONEMPTY_CSV_FILE_RECEIVED" if okay else "DOWNLOADED_FILE_EMPTY")
                    except Exception:
                        print("FILE_DOWNLOAD_NEW_TAB_OPENED="+str(int(len(ctx.pages)>before_pages)),flush=True)
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
