"""ProcureFlow-owned headless browser inspection with forensic screenshots.

Only public K-apt pages. This is NOT an autonomous action/browser submission API.
No session reuse, credentials, free-form URLs or participation/upload/submit actions.
Stored viewport captures and DOM/network observations let operators and AI review
the actual rendered stages remotely via the existing FastAPI/Postgres deployment.
"""
import hashlib
import json
import logging
import re
from datetime import datetime, timezone
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

from db import session

KAPT_ROOT = "https://www.k-apt.go.kr"
LIST_URL = KAPT_ROOT + "/bid/bidList.do"
ALLOWED_HOSTS = {"www.k-apt.go.kr", "k-apt.go.kr"}
# For static GET resources, filenames such as fileUpload.js are safe to LOAD.
# Safety is enforced at the network method/endpoint boundary, not by a
# naive filename substring search, which previously broke real K-apt rendering.
STATIC_CDN_HOSTS = {"fonts.googleapis.com", "fonts.gstatic.com",
                    "dapi.kakao.com", "t1.daumcdn.net"}
BLOCKED_NAVIGATION = re.compile(
    r"(?:/login/|/logout/|/payment/|/bid/[^/]*(?:submit|join|participat|apply|write|insert|update|delete|save|send|sign|attend)\.do$)",
    re.I,
)
READ_ONLY_POST = re.compile(
    r"(?:/bid/(?:bidList|bidDetail|bidResultList)\.do|"
    r"/cmmn/bjd/getBjdList\.do)$", re.I
)
KAPT_ID = re.compile(r"^(?:[0-9]{14,20}|kg2b_[0-9]{1,15})$")
STAGES = ("public_list", "notice_detail", "attachments_area", "before_participation")


def validate_id(external_id):
    if not KAPT_ID.fullmatch(str(external_id or "")):
        raise ValueError("K-apt notice number is invalid")
    return external_id


def safe_request(route, blocked):
    req = route.request
    parsed = urlparse(req.url)
    method = req.method.upper()
    path = parsed.path or "/"
    origin_ok = parsed.scheme == "https" and parsed.hostname in ALLOWED_HOSTS
    static_ok = parsed.scheme == "https" and parsed.hostname in STATIC_CDN_HOSTS
    allowed = (
        method in ("GET", "HEAD") and (
            (origin_ok and not BLOCKED_NAVIGATION.search(path)) or static_ok
        )
    ) or (
        method == "POST" and origin_ok
        and bool(READ_ONLY_POST.search(path))
        and not BLOCKED_NAVIGATION.search(path)
    )
    if allowed:
        route.continue_()
    else:
        blocked.append({"method":method,"host":parsed.hostname or "",
                        "path":path[:140], "reason":"non_readonly_or_off_origin"})
        route.abort(error_code="blockedbyclient")


def page_snapshot(page, name, events, errors):
    try:
        data = page.evaluate("""() => {
          const norm=s=>String(s||'').replace(/\\s+/g,' ').trim();
          const links=[...document.querySelectorAll('a[href]')]
            .filter(e=>e.getAttribute('href')&&
              /첨부|다운|공고|서류|파일|hwp|pdf|zip|xls|입찰|응찰/.test(norm(e.innerText)+' '+e.href))
            .slice(0,50).map(e=>({
              label:norm(e.innerText).slice(0,110),
              href:e.href.slice(0,450)
            }));
          const controls=[...document.querySelectorAll('a,button,input[type=button],input[type=submit]')]
            .map(e=>({
              label:norm(e.innerText||e.value||e.title||e.getAttribute('aria-label')).slice(0,100),
              tag:e.tagName, href:(e.href||'').slice(0,220),
              disabled:!!e.disabled,
              visible:!!(e.offsetWidth||e.offsetHeight||e.getClientRects().length)
            }))
            .filter(x=>x.visible&&/입찰|응찰|참가|서류|첨부|공고|파일|다운|로그인|제출|투찰/.test(x.label))
            .slice(0,70);
          const tables=[...document.querySelectorAll('table')].slice(0,12)
            .map(e=>({rows:e.querySelectorAll('tr').length,
              summary:norm(e.innerText).slice(0,900)}));
          const body=document.body;
          return {title:document.title,
            url:location.origin+location.pathname,
            content_length:body?.innerText.length||0,
            text:(body?.innerText||'').slice(0,12500),
            link_candidates:links,
            controls:controls,
            tables:tables,
            visible_login:!!document.querySelector('input[type=password]')};
        }""")
    except Exception as exc:
        data = {"snapshot_error": type(exc).__name__ + ": " + str(exc)[:160]}
        errors.append({"step": name, "reason": data["snapshot_error"]})
    screenshot = b""
    try:
        screenshot = page.screenshot(type="jpeg", quality=68, full_page=False,
                                      animations="disabled", timeout=18000)
    except Exception as exc:
        errors.append({"step": name, "screenshot_error":
                       type(exc).__name__ + ": " + str(exc)[:160]})
    data["image_sha256"] = hashlib.sha256(screenshot).hexdigest() if screenshot else ""
    data["image_size"] = len(screenshot)
    data["stage"] = name
    data["time_utc"] = datetime.now(timezone.utc).isoformat()
    data["recent_events"] = events[-20:]
    with session() as db:
        db.execute("""
          INSERT INTO procureflow.browser_captures
          (job_id,stage,content_type,image,snapshot)
          VALUES (%s,%s,'image/jpeg',%s,%s::jsonb)
          ON CONFLICT(job_id,stage)
          DO UPDATE SET image=excluded.image,snapshot=excluded.snapshot,
                        created_at=now()
        """, (int(page._procureflow_job_id), name, screenshot,
              json.dumps(data,ensure_ascii=False)))
    logging.info("PF_BROWSER_CAPTURE job=%s stage=%s image_bytes=%s dom_chars=%s",
                 page._procureflow_job_id,name,len(screenshot),
                 data.get("content_length"))
    return data


def collect(job_id, external_id):
    """Execute fixed read-only navigation stages; never click participation."""
    external_id = validate_id(external_id)
    detail_url = KAPT_ROOT + "/bid/bidDetail.do?bidNum=" + external_id
    events = []
    errors = []
    blocked = []
    steps = []

    def add(kind, **kwargs):
        if len(events) < 180:
            events.append({"kind":kind, **kwargs})
    result = {
        "engine":"playwright_chromium_internal", "version":1,
        "target":"kapt", "notice_id":external_id,
        "list_url":LIST_URL, "detail_url":detail_url,
        "read_only":True, "submitted":False, "participation_clicked":False,
        "attachments_downloaded":False, "clicks_performed":0,
        "steps":steps, "errors":errors, "blocked_network":blocked,
    }
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"]
        )
        ctx = browser.new_context(
            locale="ko-KR", timezone_id="Asia/Seoul",
            viewport={"width":1365,"height":920},device_scale_factor=1,
            accept_downloads=False, service_workers="block",
        )
        ctx.route("**/*", lambda route: safe_request(route,blocked))
        page = ctx.new_page()
        page._procureflow_job_id = job_id
        page.on("console",lambda msg:add("console",level=msg.type,text=msg.text[:210])
                if msg.type in ("error","warning") else None)
        page.on("pageerror",lambda error:add("pageerror",reason=str(error)[:230]))
        page.on("response",lambda response:add(
            "http",code=response.status,method=response.request.method,
            path=urlparse(response.url).path[:150])
            if response.status>=400 else None)
        page.on("requestfailed",lambda request:add(
            "requestfailed",method=request.method,
            path=urlparse(request.url).path[:150],
            reason=str(request.failure)[:150]))
        try:
            for name,url in (("public_list",LIST_URL),
                              ("notice_detail",detail_url)):
                try:
                    response=page.goto(url,wait_until="domcontentloaded",timeout=42000)
                    page.wait_for_timeout(2000)
                    if response and response.status>=400:
                        errors.append({"step":name,"http":response.status})
                    steps.append(page_snapshot(page,name,events,errors))
                except Exception as exc:
                    errors.append({"step":name,"reason":
                                   type(exc).__name__ + ": " + str(exc)[:240]})
                    # Do not terminate after a list-navigation error; direct
                    # read-only detail navigation may still work.
            try:
                # Scroll (not click) to attachment section for screenshot.
                found=page.get_by_text("파일첨부",exact=False)
                if found.count():
                    found.first.scroll_into_view_if_needed(timeout=3500)
                else:
                    page.evaluate("window.scrollTo(0, Math.min(900, document.body.scrollHeight))")
                page.wait_for_timeout(450)
                steps.append(page_snapshot(page,"attachments_area",events,errors))
            except Exception as exc:
                errors.append({"step":"attachments_area","reason":
                               type(exc).__name__ + ": " + str(exc)[:240]})
            try:
                # Inspect DOM-only evidence of where participation would start;
                # do not click, submit, log in, or alter any form.
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                page.wait_for_timeout(450)
                steps.append(page_snapshot(page,"before_participation",events,errors))
            except Exception as exc:
                errors.append({"step":"before_participation","reason":
                               type(exc).__name__ + ": " + str(exc)[:240]})
        finally:
            ctx.close()
            browser.close()
    result["screenshots_saved"] = [
        {"stage":s.get("stage"),"sha256":s.get("image_sha256"),
         "bytes":s.get("image_size"),"dom_length":s.get("content_length")}
        for s in steps
    ]
    result["screen_stage_count"] = len(steps)
    result["network_block_count"] = len(blocked)
    result["ui_errors_count"] = len(errors)
    # No implication that a valid bid can be placed.
    result["status"] = ("collected" if len(steps)==len(STAGES) and not errors
                        else "partial" if steps else "error")
    result["participation_gate"]="STOP_BEFORE_ANY_PARTICIPATION_ACTION"
    with session() as db:
        db.execute("""
           INSERT INTO procureflow.browser_reports(job_id,report)
           VALUES (%s,%s::jsonb)
           ON CONFLICT(job_id) DO UPDATE SET report=excluded.report,
                                             updated_at=now()
        """,(job_id,json.dumps(result,ensure_ascii=False,default=str)))
    return result
