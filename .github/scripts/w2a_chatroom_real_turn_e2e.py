#!/usr/bin/env python3
"""Browser-level Web2API real-turn verification, with scoped test session.

This sends exactly one fixed, harmless marker prompt. A trusted GitHub
Chrome worker must be connected (or connect while the test is waiting).
"""
import os
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

BASE="https://chatgpt-relay-web-production.up.railway.app"
OUT=Path(os.environ.get("RUNNER_TEMP","/tmp"))/"hitel-chatroom-real-turn"
OUT.mkdir(exist_ok=True,parents=True)

def main():
  with sync_playwright() as pw:
    browser=pw.chromium.launch(headless=True,
      executable_path=os.environ["CHROME_BINARY"],
      args=["--no-sandbox","--disable-dev-shm-usage"])
    page=browser.new_page(viewport={"width":1250,"height":850})
    try:
      page.goto(BASE,wait_until="domcontentloaded",timeout=60000)
      expect(page.locator("#new-room")).to_be_visible(timeout=15000)
      page.locator("#new-room").click()
      page.locator("#room-name").fill("Real ChatGPT Answer E2E")
      page.locator("#room-form button[type=submit]").click()
      expect(page.locator("#room-title")).to_have_text("Real ChatGPT Answer E2E",timeout=12000)
      page.locator("#preset").select_option("connection")
      expect(page.locator("#send")).to_be_enabled(timeout=10000)
      page.locator("#send").click()
      print("PASS_REAL_BROWSER_CREATED_ROOM_AND_SUBMITTED_FIXED_PROMPT",flush=True)
      for i in range(170):
        # Keep Playwright's dispatch loop alive: page.wait_for_timeout is not time.sleep
        page.wait_for_timeout(2500)
        data=page.evaluate("""async () => {
          let rooms=await fetch('/web/api/rooms',{cache:'no-store'}).then(r=>r.json());
          let match=rooms.rooms.find(r=>r.title==='Real ChatGPT Answer E2E');
          if (!match)return null;
          return await fetch('/web/api/rooms/'+match.id,{cache:'no-store'}).then(r=>r.json());
        }""")
        if not data:continue
        answers=[m["text"] for m in data.get("messages",[]) if m.get("role")=="assistant"]
        last_jobs=data.get("jobs",[])
        if answers and "HITEL_W2A_OK_20261113" in answers[-1] and any(j["status"]=="completed" for j in last_jobs):
          print("PASS_ACTUAL_BROWSER_GITHUB_CHROME_CHATGPT_REPLY_IN_ROOM",flush=True)
          print("ACTUAL_BROWSER_JOB_STATE=completed",flush=True)
          page.reload(wait_until="domcontentloaded")
          page.locator("#room-list .room-btn").filter(has_text="Real ChatGPT Answer E2E").click()
          expect(page.locator("#messages")).to_contain_text("HITEL_W2A_OK_20261113",timeout=15000)
          print("PASS_VERIFIED_CHATGPT_ANSWER_PERSISTS_IN_BROWSER_ROOM",flush=True)
          page.screenshot(path=str(OUT/"real-answer-success.png"),full_page=True)
          return
        if last_jobs and last_jobs[0]["status"]=="failed":
          print("FAIL_REAL_TURN_WORKER_JOB_FAILED",flush=True)
          raise RuntimeError("REAL_CHATGPT_WORKER_RETURNED_FAILURE")
        if i%24==0:
          print("REAL_CHATGPT_BROWSER_WAIT_STATE="+(last_jobs[0]["status"] if last_jobs else "not_found"),flush=True)
      raise RuntimeError("REAL_CHATGPT_REPLY_NOT_VERIFIED_BEFORE_DEADLINE")
    except Exception as exc:
      try:page.screenshot(path=str(OUT/"real-answer-failure.png"),full_page=True)
      except Exception:pass
      print("FAIL_REAL_CHATGPT_BROWSER_TURN_"+type(exc).__name__,flush=True)
      raise
    finally:browser.close()

if __name__=="__main__":main()
