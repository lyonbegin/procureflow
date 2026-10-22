#!/usr/bin/env python3
"""One-time Freemoa authorization in ordinary Windows Google Chrome.

Phase 1 opens Chrome WITHOUT Playwright / remote debugging while the account
owner completes the official Google sign-in. Phase 2 restarts the same
dedicated Chrome profile with a LOCAL CDP port to export ONLY Freemoa
cookies/origin state. No Google credentials or cookies are exported.

If GitHub CLI is already authenticated, securely sets the GitHub Secret
through stdin and triggers the headless crawler. Otherwise copies the
secret to the Windows clipboard for one-time manual GitHub Secrets entry.
"""
import json
import csv
import tempfile
import os
import shutil
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

from playwright.sync_api import sync_playwright
from tools.freemoa_google_login import (
    LOGIN_URL, PROJECTS_URL, export_session_secret, verify_freemoa_account
)

REPO="lyonbegin/procureflow"
PORT=9337

def chrome_executable():
    locations=[
        Path(os.environ.get("PROGRAMFILES",r"C:\Program Files"))/"Google"/"Chrome"/"Application"/"chrome.exe",
        Path(os.environ.get("PROGRAMFILES(X86)",r"C:\Program Files (x86)"))/"Google"/"Chrome"/"Application"/"chrome.exe",
        Path(os.environ.get("LOCALAPPDATA",str(Path.home())))/"Google"/"Chrome"/"Application"/"chrome.exe"
    ]
    return next((str(x) for x in locations if x.is_file()),shutil.which("chrome"))

def launch(chrome,profile,debug=False):
    args=[
        chrome,
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-background-mode",
        "--user-data-dir="+str(profile),
    ]
    if debug:
        args.extend(["--remote-debugging-address=127.0.0.1",
                     "--remote-debugging-port="+str(PORT)])
    args.append(PROJECTS_URL if debug else LOGIN_URL)
    return subprocess.Popen(args,stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)

def wait_debugger(seconds=24):
    for _ in range(seconds*2):
        try:
            with urllib.request.urlopen(
                "http://127.0.0.1:"+str(PORT)+"/json/version",timeout=1
            ) as response:
                if response.status==200:
                    return True
        except Exception:
            time.sleep(.5)
    return False

def gh_available():
    cli=shutil.which("gh")
    if not cli:
        return None
    try:
        status=subprocess.run([cli,"auth","status"],stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL,timeout=12)
        return cli if status.returncode==0 else None
    except Exception:
        return None

def register_secret(secret):
    cli=gh_available()
    if not cli:
        return False
    # stdin instead of command-line arguments prevents process-list leakage.
    result=subprocess.run([cli,"secret","set","FREEMOA_SESSION_B64",
                           "--repo",REPO],input=secret.encode("ascii"),
                          stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,
                          timeout=25)
    if result.returncode:
        print("GitHub Secret 자동 등록에 실패했습니다. 수동 등록을 이용합니다.")
        return False
    print("GitHub Secret FREEMOA_SESSION_B64 등록 완료.")
    run=subprocess.run([cli,"workflow","run","freemoa-google.yml",
                        "--repo",REPO,"--ref","main","-f","mode=crawl"],
                       stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                       timeout=25)
    if run.returncode==0:
        print("GitHub Actions 상세 수집 실행을 요청했습니다.")
    return True

def main():
    if os.name!="nt":
        print("이 프로그램은 Windows Chrome 전용입니다.")
        return 2
    chrome=chrome_executable()
    if not chrome:
        print("Google Chrome 설치 경로를 찾지 못했습니다.")
        return 2
    root=Path.home()/".procureflow"/"freemoa_normal_chrome"
    root.mkdir(parents=True,exist_ok=True)
    print("1/3 일반 Chrome을 엽니다. 프리모아의 Google 로그인을 완료하세요.")
    normal=launch(chrome,root,debug=False)
    input("로그인 완료 후 새로 열린 Chrome 창을 닫고 Enter를 누르세요: ")
    # Gracefully closed Chrome is preferred. If left running, we cannot
    # attach to its initial non-debug process; do not destroy user's tabs.
    try:
        normal.wait(timeout=10)
    except subprocess.TimeoutExpired:
        print("프리모아용 새 Chrome 창을 먼저 닫아 주세요.")
        return 2
    print("2/3 동일한 Chrome 세션의 프리모아 로그인 상태를 확인합니다.")
    debug=launch(chrome,root,debug=True)
    try:
        if not wait_debugger():
            print("Chrome 로컬 연결에 실패했습니다.")
            return 2
        with sync_playwright() as p:
            browser=p.chromium.connect_over_cdp(
                "http://127.0.0.1:"+str(PORT),timeout=15000)
            try:
                if not browser.contexts:
                    print("Chrome 브라우저 세션이 없습니다.")
                    return 2
                context=browser.contexts[0]
                page=context.new_page()
                result=verify_freemoa_account(page)
                print("프리모아 상세 API 인증:",result.get("reason","응답 없음"))
                if result.get("authenticated") is not True:
                    print("프리모아 계정 인증이 유효하지 않습니다.")
                    return 2
                secret=export_session_secret(context.storage_state())
            finally:
                browser.close()
        print("3/3 로그인된 세션으로 실제 프로젝트 상세 10건을 수집합니다.")
        try:
            from tools.freemoa_google_login import import_session_secret
            from tools.crawl_probe import scan
            local_out=Path.home()/"Documents"/"ProcureFlow"/"Freemoa"
            with tempfile.TemporaryDirectory() as td:
                session_file=Path(td)/"freemoa.json"
                session_file.write_text(
                    json.dumps(import_session_secret(secret),ensure_ascii=False),
                    encoding="utf-8")
                report=scan("freemoa","projects",local_out,max_records=10,
                            storage_state=session_file)
            records=report.get("records",[])
            def safe_csv(value):
                text=str(value or "")
                if text.startswith(("=","+","-","@")):
                    return "'"+text
                return text
            with (local_out/"projects.csv").open(
                "w",newline="",encoding="utf-8-sig") as handle:
                writer=csv.writer(handle)
                writer.writerow(["project_id","title","status","budget",
                                 "period","full_work_content","requirements",
                                 "client_public_info","tech_stack","verified"])
                for item in records:
                    fields=item.get("fields") or {}
                    detail=item.get("detail") or {}
                    writer.writerow([safe_csv(item.get("source_id")),
                        safe_csv(item.get("title")),
                        safe_csv(fields.get("status")),
                        safe_csv(fields.get("budget") or fields.get("monthly_pay")),
                        safe_csv(fields.get("period")),
                        safe_csv(detail.get("project_description")),
                        safe_csv(detail.get("recruit_requirements")),
                        safe_csv(detail.get("client_company_info")),
                        safe_csv(", ".join(detail.get("related_technologies") or [])),
                        item.get("detail_verified",False)])
            print("실제 전체 상세 검증:",report.get("detail_records_parsed",0),"건")
            print("결과 JSON/CSV 폴더:",local_out)
        except Exception as exc:
            print("상세 수집 단계 오류:",type(exc).__name__)
        print("GitHub Actions에 프리모아 로그인 세션을 연결합니다.")
        if register_secret(secret):
            print("완료: 다음 실행부터 GitHub Actions Headless Chrome이 세션을 재사용합니다.")
            return 0
        subprocess.run(["clip"],input=secret.encode("ascii"),check=True)
        print("프리모아 세션이 클립보드에 복사됐습니다.")
        print("GitHub Secrets의 FREEMOA_SESSION_B64에 붙여넣으세요.")
        webbrowser.open(
            "https://github.com/"+REPO+"/settings/secrets/actions"
        )
        return 0
    finally:
        if debug.poll() is None:
            debug.terminate()

if __name__=="__main__":
    sys.exit(main())
