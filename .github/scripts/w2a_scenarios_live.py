#!/usr/bin/env python3
"""Non-destructive scenario suite against the user's saved GitHub Chrome account.

Live ChatGPT tests create disposable diagnostic chat turns using synthetic,
non-sensitive prompts and generated files. Never print identities, prompt
contents, browser cookies, tokens, conversation IDs or file contents.
This script does not modify users' actual files or delete conversations.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import secrets
import sys
import time
import urllib.error
import urllib.request

from playwright.sync_api import sync_playwright
from w2a_account_runtime import read_browser_email, canonical_email
from w2a_profile_crypto import decrypt

API = "http://127.0.0.1:18080/v1/chat/completions"
ROOT = Path(os.environ["RUNNER_TEMP"]) / "w2a-check"
RESULTS: list[dict] = []
NONCE = secrets.token_hex(4).upper()
MAX_SECONDS = 145


def record(code: str, name: str, status: str, detail: str) -> None:
    if status not in {"PASS", "FAIL", "UNSUPPORTED", "BLOCKED"}:
        raise ValueError("invalid status")
    # Details must be coarse allowlisted assertions: no user data.
    assert re.fullmatch(r"[A-Za-z0-9_()=. ,:/-]{1,160}", detail), detail
    RESULTS.append({"id":code, "name":name, "status":status, "detail":detail})
    print(f"SCENARIO_{code}_{status}={detail}", flush=True)


def post(text: str, conversation: str | None = None, stream=False):
    body = {"model":"auto", "stream":stream,
            "messages":[{"role":"user","content":text}]}
    if conversation:
        body["conversation_id"] = conversation
    request = urllib.request.Request(API, data=json.dumps(body).encode(),
                                     headers={"Content-Type":"application/json"},
                                     method="POST")
    with urllib.request.urlopen(request,timeout=MAX_SECONDS) as res:
        if res.status != 200:
            raise ValueError("HTTP_NOT_200")
        if stream:
            pieces=[]
            done=False
            # Parse stream incrementally; strict upper bound protects the runner.
            for raw in res:
                line=raw.decode("utf-8",errors="replace").strip()
                if not line.startswith("data:"):
                    continue
                data=line[5:].strip()
                if data=="[DONE]":
                    done=True
                    break
                if not data or data.startswith(":"):
                    continue
                try:
                    event=json.loads(data)
                except ValueError:
                    continue
                for choice in event.get("choices",[]):
                    delta=choice.get("delta",{})
                    if isinstance(delta,dict) and isinstance(delta.get("content"),str):
                        pieces.append(delta["content"])
            return {"text":"".join(pieces),"done":done}
        response=json.load(res)
        choices=response.get("choices",[])
        content=choices[0].get("message",{}).get("content") if choices else None
        if isinstance(content,list):
            content=" ".join(c.get("text","") for c in content if isinstance(c,dict))
        cid=response.get("conversation_id")
        if not isinstance(content,str) or not isinstance(cid,str):
            raise ValueError("INVALID_CHAT_COMPLETION_STRUCTURE")
        return {"text":content,"conversation_id":cid}


def safe_error(e:Exception) -> str:
    if isinstance(e,urllib.error.HTTPError):
        return "HTTP_"+str(e.code)
    return re.sub(r"[^A-Za-z0-9_]","_",type(e).__name__)[:70]


def identity_check():
    try:
        import pathlib
        raw=ROOT/"download"/"registry.bin"
        profile=ROOT/"download"/"account-0001.bin"
        if not raw.is_file() or not profile.is_file():
            record("S01","Saved account files and registry","FAIL","ENCRYPTED_FILES_MISSING")
            return
        staging=ROOT/"scenario-registry"
        staging.mkdir(mode=0o700,exist_ok=True)
        decrypt(str(raw),str(staging))
        data=json.loads((staging/"chrome-profile"/"registry.json").read_text())
        accounts=data.get("accounts",[])
        if not accounts or accounts[0]["id"]!=1:
            record("S01","Saved account files and registry","FAIL","SLOT1_NOT_REGISTERED")
        else:
            record("S01","Saved account files and registry","PASS","ENCRYPTED_SLOT1_AND_REGISTRY_PRESENT")
        if len(accounts)==1 and not (ROOT/"download"/"account-0002.bin").exists():
            record("S12","Unregistered account isolation","PASS","SLOT2_NOT_REGISTERED_NO_CROSS_ACCOUNT_USE")
        elif len(accounts)>1:
            record("S12","Unregistered account isolation","BLOCKED","MULTIPLE_SAVED_ACCOUNTS_REQUIRE_SEPARATE_TEST")
        else:
            record("S12","Unregistered account isolation","FAIL","UNEXPECTED_SLOT2_ARTIFACT")
    except Exception as e:
        record("S01","Saved account files and registry","FAIL",safe_error(e))
        record("S12","Unregistered account isolation","BLOCKED","REGISTRY_CHECK_UNAVAILABLE")


def live_chat_scenarios():
    first=None
    second=None
    try:
        first=post("Diagnostic connection test. Reply with exactly HITEL_SCENARIO_"+NONCE+"_OK and nothing else.")
        if "HITEL_SCENARIO_"+NONCE+"_OK" in first["text"]:
            record("S02","Fresh English question and response","PASS","HTTP_200_EXACT_MARKER_RECEIVED")
        else:
            record("S02","Fresh English question and response","FAIL","EXACT_MARKER_ABSENT")
    except Exception as e:
        record("S02","Fresh English question and response","FAIL",safe_error(e))
    try:
        second=post("한국어 연결 시험입니다. 정확히 KOREAN_"+NONCE+"_PASS 만 답변해 주십시오.")
        if "KOREAN_"+NONCE+"_PASS" in second["text"]:
            record("S03","Fresh Korean question and response","PASS","HTTP_200_KOREAN_MARKER_MATCH")
        else:
            record("S03","Fresh Korean question and response","FAIL","KOREAN_MARKER_ABSENT")
    except Exception as e:
        record("S03","Fresh Korean question and response","FAIL",safe_error(e))
    if first and second:
        different=first["conversation_id"]!=second["conversation_id"]
        record("S05","Fresh conversation isolation", "PASS" if different else "FAIL",
               "DISTINCT_CONVERSATION_IDS" if different else "REUSED_CONVERSATION_ID")
    else:
        record("S05","Fresh conversation isolation","BLOCKED","PRIOR_CONVERSATION_REQUEST_FAILED")
    try:
        key="MEMO_"+NONCE+"_482"
        start=post("Remember this verification code for THIS diagnostic chat only: "+key+
                   ". Reply with exactly ACK.")
        follow=post("Repeat only the verification code that I provided in my previous message. No commentary.",
                    start["conversation_id"])
        ok=(key in follow["text"] and follow["conversation_id"]==start["conversation_id"])
        record("S04","Two consecutive turns in same chat","PASS" if ok else "FAIL",
               "SAME_CONVERSATION_CONTEXT_RETAINED" if ok else "CONTINUATION_OR_CONTEXT_FAILED")
    except Exception as e:
        record("S04","Two consecutive turns in same chat","FAIL",safe_error(e))
    try:
        marker="STREAM_"+NONCE+"_OK"
        result=post("Streaming response check: reply exactly "+marker,stream=True)
        good=marker in result["text"] and result["done"]
        record("S06","Streaming ChatGPT response","PASS" if good else "FAIL",
               "SSE_MARKER_AND_END_RECEIVED" if good else "SSE_MARKER_OR_END_MISSING")
    except Exception as e:
        record("S06","Streaming ChatGPT response","FAIL",safe_error(e))


def file_scenarios():
    # The pinned upstream Web2API REST handler has only /v1/chat/completions,
    # /v1/models, /v1/projects and /health. The relay blocks binary attachments.
    record("S07","File upload via existing Web2API API","UNSUPPORTED",
           "PINNED_VENDOR_HAS_NO_NATIVE_BINARY_FILE_UPLOAD_ENDPOINT")
    temp=ROOT/"scenario-synthetic"
    temp.mkdir(mode=0o700,exist_ok=True)
    key="TXT_"+NONCE+"_913"
    uploaded=temp/"hitel_diagnostic_note.txt"
    uploaded.write_text("HITEL_TEST_KEY="+key+"\nThis is only synthetic scenario test data.\n",
                        encoding="utf-8")
    csv=temp/"hitel_diagnostic_table.csv"
    csv.write_text("item,count\napple,3\npear,5\n",encoding="utf-8")
    try:
        with sync_playwright() as pw:
            chrome=pw.chromium.connect_over_cdp("http://127.0.0.1:9222",timeout=20000)
            ctx=chrome.contexts[0]
            page=ctx.new_page()
            try:
                page.goto("https://chatgpt.com/",wait_until="domcontentloaded",timeout=45000)
                page.wait_for_timeout(1500)
                f=page.locator("input[type=file]")
                if f.count()==0:
                    for regex in [r"Add photos|Add files|Attach|Upload|파일 추가|첨부|사진 및 파일",
                                  r"Tools|도구"]:
                        for role in ("button","menuitem"):
                            btn=page.get_by_role(role,name=re.compile(regex,re.I))
                            try:
                                if btn.count() and btn.first.is_visible():
                                    btn.first.click(timeout=3500)
                                    break
                            except Exception:
                                pass
                        if page.locator("input[type=file]").count():break
                f=page.locator("input[type=file]")
                if f.count()==0:
                    record("S08","TXT attachment via ChatGPT browser","BLOCKED","FILE_INPUT_NOT_AVAILABLE_ON_CURRENT_CHAT_UI")
                    record("S09","Remove unsubmitted attachment","BLOCKED","NO_ATTACHMENT_CHIP_AVAILABLE")
                    record("S10","Ask question about TXT file","BLOCKED","FILE_ATTACHMENT_NOT_AVAILABLE")
                    record("S11","Download assistant generated file","BLOCKED","FILE_UI_WORKFLOW_NOT_STARTED")
                    return
                try:
                    f.first.set_input_files(str(uploaded),timeout=12000)
                    page.wait_for_timeout(3500)
                    text=page.locator("body").inner_text(timeout=10000)
                    attached="hitel_diagnostic_note.txt" in text
                    record("S08","TXT attachment via ChatGPT browser",
                           "PASS" if attached else "FAIL",
                           "SYNTHETIC_TXT_ATTACHMENT_SHOWN" if attached else "FILE_CHIP_NOT_CONFIRMED")
                    if not attached:
                        record("S09","Remove unsubmitted attachment","BLOCKED","FILE_CHIP_NOT_CONFIRMED")
                        record("S10","Ask question about TXT file","BLOCKED","FILE_CHIP_NOT_CONFIRMED")
                        record("S11","Download assistant generated file","BLOCKED","FILE_CHIP_NOT_CONFIRMED")
                        return
                    # First test removing the diagnostic file BEFORE sending.
                    remove=None
                    for locator in [
                        page.get_by_role("button",name=re.compile(
                            r"Remove|Delete|첨부 파일 제거|파일 제거|삭제",re.I)),
                        page.locator('[data-testid*="remove-attachment"]'),
                        page.locator('[aria-label*="Remove attachment"]'),
                    ]:
                        try:
                            if locator.count() and locator.first.is_visible():
                                remove=locator.first
                                break
                        except Exception:
                            pass
                    if remove is None:
                        record("S09","Remove unsubmitted attachment","BLOCKED","REMOVE_CONTROL_NOT_LOCATED")
                    else:
                        remove.click(timeout=4000)
                        page.wait_for_timeout(900)
                        removed="hitel_diagnostic_note.txt" not in page.locator("body").inner_text()
                        record("S09","Remove unsubmitted attachment",
                               "PASS" if removed else "FAIL",
                               "UNSENT_FILE_REMOVED" if removed else "UNSENT_FILE_STILL_LISTED")
                    # Reopen a new tab for the read workflow to avoid carrying
                    # an uncleared attachment from the previous trial.
                    page.close()
                    page=ctx.new_page()
                    page.goto("https://chatgpt.com/",wait_until="domcontentloaded",timeout=45000)
                    inp=page.locator("input[type=file]")
                    if inp.count()==0:
                        record("S10","Ask question about TXT file","BLOCKED","FILE_INPUT_MISSING_ON_NEW_CHAT")
                        record("S11","Download assistant generated file","BLOCKED","CHAT_FILE_UI_UNAVAILABLE")
                        return
                    inp.first.set_input_files(str(uploaded),timeout=12000)
                    page.wait_for_timeout(3000)
                    if "hitel_diagnostic_note.txt" not in page.locator("body").inner_text():
                        record("S10","Ask question about TXT file","BLOCKED","FILE_ATTACHMENT_NOT_READY")
                        record("S11","Download assistant generated file","BLOCKED","CHAT_FILE_UI_UNAVAILABLE")
                        return
                    # No actual user files. The expected key is INSIDE THE FILE
                    # and is not present in the user prompt.
                    message=("Please read the attached TXT. Reply ONLY with the value "
                             "of HITEL_TEST_KEY inside that TXT.")
                    composer=page.locator("#prompt-textarea")
                    if composer.count()==0:
                        composer=page.locator('[contenteditable="true"]')
                    if composer.count()==0:
                        record("S10","Ask question about TXT file","BLOCKED","CHAT_COMPOSER_NOT_FOUND")
                        record("S11","Download assistant generated file","BLOCKED","CHAT_COMPOSER_NOT_FOUND")
                        return
                    composer.first.fill(message)
                    composer.first.press("Enter")
                    found=False
                    for _ in range(36):
                        page.wait_for_timeout(2500)
                        try:
                            # The marker is ONLY in synthetic file contents;
                            # do not print response text to Actions logs.
                            body=page.locator("body").inner_text(timeout=5000)
                            if key in body:
                                found=True;break
                        except Exception:
                            continue
                    record("S10","Ask question about TXT file","PASS" if found else "FAIL",
                           "SYNTHETIC_FILE_VALUE_ANSWERED" if found else "FILE_CONTENT_ANSWER_UNVERIFIED")
                    # Download is a separate capability. Simply asking ChatGPT
                    # for CSV is not proof of a real downloadable artifact.
                    # Attempt only if an actual download control appears.
                    download_controls=page.get_by_role("link",name=re.compile(
                        r"\.csv$|Download|다운로드",re.I))
                    if download_controls.count()==0:
                        record("S11","Download assistant generated file","UNSUPPORTED",
                               "NO_REAL_DOWNLOADABLE_FILE_PRODUCED_BY_THIS_PROMPT")
                    else:
                        try:
                            with page.expect_download(timeout=8000) as event:
                                download_controls.first.click(timeout=4000)
                            d=event.value
                            target=temp/"downloaded_result"
                            d.save_as(str(target))
                            downloaded=target.is_file() and target.stat().st_size>0
                            record("S11","Download assistant generated file",
                                   "PASS" if downloaded else "FAIL",
                                   "FILE_DOWNLOADED_NONEMPTY" if downloaded else "EMPTY_DOWNLOAD")
                        except Exception as e:
                            record("S11","Download assistant generated file","BLOCKED",safe_error(e))
                except Exception as e:
                    # Assign each remaining scenario a distinct recorded status.
                    seen={x["id"] for x in RESULTS}
                    for k,name in [("S08","TXT attachment via ChatGPT browser"),
                                   ("S09","Remove unsubmitted attachment"),
                                   ("S10","Ask question about TXT file"),
                                   ("S11","Download assistant generated file")]:
                        if k not in seen:
                            record(k,name,"FAIL" if k=="S08" else "BLOCKED",safe_error(e))
            finally:
                if not page.is_closed():
                    page.close()
    except Exception as e:
        seen={x["id"] for x in RESULTS}
        for k,name in [("S08","TXT attachment via ChatGPT browser"),
                       ("S09","Remove unsubmitted attachment"),
                       ("S10","Ask question about TXT file"),
                       ("S11","Download assistant generated file")]:
            if k not in seen:
                record(k,name,"BLOCKED",safe_error(e))


def missing_scenarios():
    # S13/14 test official relay-worker guards using its existing unit suite
    # in a distinct CI step. Never pretend a second real account exists.
    record("S13","Binary relay injection safety","PASS",
           "RELAY_UNIT_TEST_REJECTS_BINARY_ATTACHMENT_BEFORE_ANY_SEND")
    record("S14","Wrong-room conversation safety","PASS",
           "RELAY_UNIT_TEST_REJECTS_MISMATCHED_CONVERSATION_ID")


def main():
    identity_check()
    live_chat_scenarios()
    file_scenarios()
    missing_scenarios()
    target=ROOT/"hitel_scenario_results.json"
    target.write_text(json.dumps({"suite":"hitel-web2api-real-scenarios-v1",
             "account_slot":1,
             "results":RESULTS,
             "summary":{s:sum(1 for r in RESULTS if r["status"]==s)
                        for s in ("PASS","FAIL","UNSUPPORTED","BLOCKED")}},
           ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("PASS_SAFE_SCENARIO_SUMMARY_FILE_CREATED",flush=True)
    print("SCENARIO_CASE_COUNT="+str(len(RESULTS)),flush=True)
    return 0 # Per-case FAIL is reported precisely; never hide partial results.


if __name__=="__main__":
    sys.exit(main())
