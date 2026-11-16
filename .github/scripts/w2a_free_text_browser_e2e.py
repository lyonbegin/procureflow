#!/usr/bin/env python3
"""Real external-browser typed-prompt -> Railway room -> signed Chrome worker -> answer.

Does not read any user's account data or log private browser cookies.
This test creates its own anonymous room, submits exactly one harmless
freely typed input, and checks a newly generated assistant message.
"""
import os
import time
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

BASE="https://chatgpt-relay-web-production.up.railway.app"
MARKER="HITEL_EXTERNAL_FREE_TEXT_OK_20261116"
OUT=Path(os.environ.get("RUNNER_TEMP","/tmp"))/"hitel-free-text-e2e"
OUT.mkdir(parents=True,exist_ok=True)

def main():
    with sync_playwright() as pw:
        browser=pw.chromium.launch(
            headless=True,executable_path=os.environ["CHROME_BINARY"],
            args=["--no-sandbox","--disable-dev-shm-usage"])
        ctx=browser.new_context(viewport={"width":1280,"height":850})
        page=ctx.new_page()
        errs=[]
        page.on("pageerror",lambda e:errs.append("SCRIPT_EXCEPTION"))
        try:
            page.goto(BASE+"/?external-free-text-e2e=20261116",
                      wait_until="domcontentloaded",timeout=60000)
            expect(page.locator("#new-room")).to_be_visible(timeout=15000)
            expect(page.locator("#draft")).to_have_attribute("maxlength","2000")
            expect(page.locator("#send")).to_have_text("질문 보내기")
            assert page.locator('input[type="password"]').count()==0
            print("PASS_REAL_PUBLIC_FREE_TEXT_COMPOSER_VISIBLE_NO_TOKENS",flush=True)

            page.locator("#new-room").click()
            page.locator("#room-name").fill("외부 자유질문 실제 응답 시험")
            page.locator("#room-form button[type=submit]").click()
            expect(page.locator("#room-title")).to_have_text("외부 자유질문 실제 응답 시험",timeout=15000)
            print("PASS_REAL_BROWSER_EXTERNAL_ROOM_CREATED",flush=True)

            question=("이 문장은 사용자가 채팅창에 직접 입력한 자유 질문입니다. "
                      "실제 답변에 "+MARKER+"를 정확히 포함하여 짧게 인사해 주세요.")
            page.locator("#draft").fill(question)
            expect(page.locator("#send")).to_be_enabled(timeout=5000)
            with page.expect_response(lambda r: "/web/api/rooms/" in r.url
                    and r.url.split("?")[0].endswith("/message"), timeout=30000) as accepted:
                page.locator("#send").click()
            reply=accepted.value
            print("ACTUAL_BROWSER_FREE_TEXT_POST_STATUS="+str(reply.status),flush=True)
            assert reply.status==200,"FREE_TEXT_BROWSER_HTTP_NOT_200"
            j=reply.json()
            assert j.get("queued") is True and j.get("jobId","").startswith("job_")
            assert j.get("sentToChatGPT") is False
            print("PASS_BROWSER_CUSTOM_TEXT_HTTP_200_AND_REAL_QUEUE",flush=True)
            expect(page.locator("#messages")).to_contain_text(question,timeout=12000)
            print("PASS_BROWSER_TYPED_QUESTION_PERSISTED_IN_OWN_ROOM",flush=True)

            # The signed GitHub Chrome worker may need to start separately.
            # This is not a false success when the worker is disconnected.
            done=False
            last_state="unknown"
            last_assistant=""
            for _ in range(180):
                state=page.evaluate("""async()=> {
                   const r=await fetch('/web/api/rooms',{credentials:'same-origin',cache:'no-store'});
                   const all=await r.json();
                   const room=all.rooms.find(x=>x.title==='외부 자유질문 실제 응답 시험');
                   if(!room) return {state:'room_missing'};
                   const rd=await fetch('/web/api/rooms/'+room.id,{credentials:'same-origin',cache:'no-store'});
                   const d=await rd.json();
                   const job=d.jobs.find(x=>x.id===window.__trialJob);
                   return {state:(job&&job.status)||'unknown',
                     answer:(d.messages.filter(x=>x.role==='assistant').map(x=>x.text).slice(-1)[0]||'')};
                }""") if False else None
                # Resolve test room id once per poll through the same authenticated
                # browser cookie. The job ID is used so earlier answers cannot pass.
                state=page.evaluate("""async jobId => {
                   const rooms=await fetch('/web/api/rooms',{cache:'no-store'}).then(r=>r.json());
                   const room=rooms.rooms.find(x=>x.title==='외부 자유질문 실제 응답 시험');
                   if(!room)return {state:'room_missing'};
                   const d=await fetch('/web/api/rooms/'+room.id,{cache:'no-store'}).then(r=>r.json());
                   const job=d.jobs.find(x=>x.id===jobId);
                   const answer=d.messages.find(x=>x.role==='assistant'&&x.job_id===jobId);
                   return {state:job?job.status:'job_missing',answer:answer?answer.text:''};
                }""",j["jobId"])
                last_state=state.get("state","unknown")
                last_assistant=state.get("answer","")
                if last_state=="failed":
                    raise AssertionError("REAL_CHATGPT_WORKER_JOB_FAILED")
                if last_state=="completed" and MARKER in last_assistant:
                    done=True;break
                if last_state=="completed" and MARKER not in last_assistant:
                    raise AssertionError("REAL_CHATGPT_ANSWER_MARKER_MISMATCH")
                page.wait_for_timeout(3000)
            print("ACTUAL_FREE_TEXT_JOB_STATE="+last_state,flush=True)
            assert done,"NO_VERIFIED_CHATGPT_REPLY_AFTER_EXTERNAL_FREE_TEXT"
            print("PASS_REAL_EXTERNAL_FREE_TEXT_CHATGPT_ANSWER_PERSISTED",flush=True)
            page.reload(wait_until="domcontentloaded")
            expect(page.locator("#room-list")).to_contain_text("외부 자유질문 실제 응답 시험",timeout=12000)
            page.locator("#room-list .room-btn").filter(has_text="외부 자유질문 실제 응답 시험").click()
            expect(page.locator("#messages")).to_contain_text(MARKER,timeout=12000)
            print("PASS_REAL_REPLY_VISIBLE_AFTER_BROWSER_RELOAD",flush=True)
            assert not errs,"BROWSER_JS_RUNTIME_ERRORS"
            page.screenshot(path=str(OUT/"external-free-text-success.png"),full_page=True)
            print("PASS_EXTERNAL_FREE_TEXT_END_TO_END_CHROMIUM_TEST",flush=True)
        except Exception as e:
            try:page.screenshot(path=str(OUT/"external-free-text-failure.png"),full_page=True)
            except Exception:pass
            print("FAIL_EXTERNAL_FREE_TEXT_BROWSER_"+type(e).__name__,flush=True)
            raise
        finally:
            browser.close()

if __name__=="__main__":
    main()
