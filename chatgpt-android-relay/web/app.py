import asyncio
import hmac
import json
import os
import time
from collections import deque
from pathlib import Path
from typing import Any
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
import api_v1
import drive_v1
import web_chat
import chatgpt_accounts
import integration_api
import integration_public
import integration_agent_stream
import task_worker_isolation
import long_job_events
import file_scenario_api
import bridge_qa_api
import integration_pairing
import worker_autostart
import remote_login_landing
from gh_oidc import verify_worker_identity

ROOT = Path(__file__).resolve().parent
PUBLIC_SMOKE_ONLY = os.environ.get("PUBLIC_SMOKE_ONLY", "") == "1"
DEMO_UID = "usr_public_web2api_probe_20261113"
DEMO_ROOM = "room_public_web2api_probe_20261113"
DEMO_QUESTION = "연결 확인 시험입니다. 정확히 HITEL_W2A_OK_20261113만 답변하십시오."
DEMO_MARKER = "HITEL_W2A_OK_20261113"
DEMO_COOLDOWN_MS = 10 * 60 * 1000
app = FastAPI(title="ChatGPT Android Relay API Test Server", docs_url="/docs", redoc_url=None)
app.include_router(api_v1.router)
app.include_router(drive_v1.router)
app.include_router(web_chat.router)
app.include_router(chatgpt_accounts.router)
app.include_router(integration_api.browser_router)
app.include_router(integration_api.router)
app.include_router(integration_public.router)
app.include_router(integration_agent_stream.router)
app.include_router(task_worker_isolation.router)
app.include_router(file_scenario_api.router)
app.include_router(bridge_qa_api.router)
app.include_router(integration_pairing.browser_router)
app.include_router(integration_pairing.worker_router)
app.include_router(remote_login_landing.router)
CONSOLE_TOKEN = os.environ.get("CONSOLE_TOKEN", "")
DEVICE_TOKEN = os.environ.get("DEVICE_TOKEN", "")
DEVICE_ID = "android-main"
MAX_MESSAGE_SIZE = 2_800_000
MAX_FINAL_REPLY_BYTES = 2_000_000
# Legacy console commands have no verified room_id. Never let them
# submit a prompt or create a thread in whichever chat happens to be foreground.
ALLOWED = {"chat.stop", "ui.snapshot", "ui.back"}
ROOM_SCOPED_ONLY = {"chat.send", "chat.new"}
consoles: set[WebSocket] = set()
device: WebSocket | None = None  # existing native Android, unchanged
web2api_device: WebSocket | None = None  # separate GitHub Chrome runner
web2api_last_seen_monotonic: float = 0.0
worker_watch_task: asyncio.Task | None = None
pending: dict[str, dict[str, Any]] = {}
recent: deque[dict[str, Any]] = deque(maxlen=30)
last_command: dict[str, Any] = {"stage": "idle"}
active_job_id: str | None = None
active_job_transport: str | None = None
# Internal multi-tab dispatch: each in-flight Web2API request belongs to ONE room.
# The native Android device retains its independent legacy active_job_id.
web2api_active_jobs: dict[str, str] = {}  # job_id -> room_id
# Cutover protects all old queued jobs from accidental replay by the v4 worker.
WEB2API_V4_CUTOVER_CREATED_AT = 1795104560000
# Preserve all pre-v4 jobs and prior chat records; never replay a stalled
# request merely because a new Chrome worker has empty tab slots.
WEB2API_V4_CUTOVER_CREATED_AT = 1795104560000  # 2026-11-19 16:09:20 UTC
# Exact two previously-linked user rooms. Never use new room IDs or overwrite
# existing saved conversation URLs for a prewarming task.
PREWARM_KNOWN_ROOMS = {
    "room_e43054eed81d46fba991b946ede92d1b":
        "STOCK-KG-A-RESEARCH-20261119-R3",
    "room_e31b6755688748f6a9ddb5a0f6b3cdaf":
        "HITEL-SCRIBD-18109-TITLE-CLASSIFY-G003",
}
worker_bootstrap_ready = False
worker_prewarm_targets: dict[str,str] = {}
job_dispatch_lock = asyncio.Lock()


def linked_rooms_for_authenticated_worker() -> list[dict[str,str]]:
    """Recover *actual* previously bound conversation URLs from room DB.

    Only the signed GitHub worker receives these private editable links.
    No public endpoint accepts or exposes the resulting tab target IDs.
    """
    with api_v1.connection() as c:
        ids=tuple(PREWARM_KNOWN_ROOMS)
        rows=c.execute("""SELECT id,title,chatgpt_url,user_id,status FROM rooms
                          WHERE id IN (?,?)""", ids).fetchall()
    result=[]
    for row in rows:
        if (row["user_id"]!="usr_browser_hitel_public_link"
            or row["title"]!=PREWARM_KNOWN_ROOMS.get(row["id"])
            or row["status"]!="active" or not row["chatgpt_url"]):
            continue
        try:
            url=api_v1.normalize_chatgpt_conversation_url(row["chatgpt_url"])
        except Exception:
            continue
        if url:
            result.append({"room_id":row["id"],"chatgpt_url":url})
    return sorted(result,key=lambda x:x["room_id"])
recovery_checked = False

async def dispatch_next():
    """Dispatch eligible independent rooms without arbitrary numeric slot caps.

    A room has at most one RUNNING job (enforced atomically by claim_next_job).
    Each signed Web2API job gets its own adapter process + Chrome owned tab.
    """
    global active_job_id, active_job_transport, recovery_checked
    if device is None and web2api_device is None:
        return
    async with job_dispatch_lock:
        if not recovery_checked:
            recovered = api_v1.fail_orphaned_running_jobs(
                public_trial_only=PUBLIC_SMOKE_ONLY)
            recovery_checked = True
            if recovered:
                print(f"[relay-v1] recovery: {recovered} orphaned uncertain jobs; no auto-retry",
                      flush=True)
        failed_missing = (0 if PUBLIC_SMOKE_ONLY
                          else api_v1.fail_queued_jobs_with_unavailable_files())
        if failed_missing:
            print(f"[relay-v1] unavailable attachments: {failed_missing}", flush=True)

        if web2api_device is not None and worker_bootstrap_ready:
            while True:
                job = api_v1.claim_next_job(
                    public_trial_only=PUBLIC_SMOKE_ONLY,
                    allow_account_bound=True,
                    web_text_only=True,
                    min_created_at=WEB2API_V4_CUTOVER_CREATED_AT,
                )
                if job is None:
                    break
                jid = job["id"]
                web2api_active_jobs[jid] = job["room_id"]
                try:
                    await transmit(web2api_device, event("job", job=job))
                    long_job_events.observe(jid, "worker_dispatched")
                    await broadcast(event(
                        "job.dispatched", job_id=jid, room_id=job["room_id"],
                        action=job["action"], user_id=job["user_id"], worker="web2api"))
                    asyncio.create_task(job_timeout(jid))
                except Exception:
                    api_v1.update_job(
                        jid,status="unknown",stage="worker_transport_interrupted",
                        error="Web2API transport interrupted; delivery unconfirmed; no retry")
                    long_job_events.observe(
                        jid, "worker_transport_interrupted",
                        error_code="WORKER_CONNECTION_LOST", error_stage="dispatch")
                    web2api_active_jobs.pop(jid, None)
                    break
        # Preserve existing Android / file operations on a separate route.
        if device is not None and active_job_id is None:
            job = api_v1.claim_next_job(
                public_trial_only=PUBLIC_SMOKE_ONLY,
                allow_account_bound=False,
                web_text_only=False,
            )
            if job is not None:
                jid = job["id"]
                active_job_id = jid
                active_job_transport = "android"
                try:
                    await transmit(device, event("job", job=job))
                    await broadcast(event(
                        "job.dispatched", job_id=jid, room_id=job["room_id"],
                        action=job["action"], user_id=job["user_id"], worker="android"))
                    asyncio.create_task(job_timeout(jid))
                except Exception:
                    api_v1.release_running_job(
                        jid, "Android transport interrupted; not auto-retried")
                    active_job_id = None
                    active_job_transport = None


# A slow ChatGPT model is not a failed model. This is a *progress* threshold,
# not a hard deadline: the actual worker result (or a confirmed connection
# loss) is authoritative. In particular do NOT dispatch the next question
# merely because 150 seconds elapsed: that would overlap two conversations.
JOB_SLOW_NOTICE_SECONDS = 10 * 60


async def job_timeout(job_id: str):
    """After ten minutes, report 'still waiting' without failing the job.

    The legacy 150-second failure discarded valid long-running generations.
    The job remains RUNNING, retains the same room/conversation identity and
    continues to await the original worker's verified response. Never resend.
    """
    await asyncio.sleep(JOB_SLOW_NOTICE_SECONDS)
    if active_job_id != job_id and job_id not in web2api_active_jobs:
        return
    with api_v1.connection() as db:
        changed = db.execute(
            """UPDATE jobs SET stage=?, updated_at=?
               WHERE id=? AND status='running'""",
            ("waiting_for_verified_reply", api_v1.clock(), job_id),
        ).rowcount
    if changed and (active_job_id == job_id or job_id in web2api_active_jobs):
        await broadcast(event("job.progress", job_id=job_id,
                              stage="waiting_for_verified_reply"))
        integration_agent_stream.notify_job_changed(job_id)


async def notify_new_job():
    """Dispatch immediately when online; launch signed worker on real demand."""
    if web2api_device is not None:
        await dispatch_next()
    elif worker_autostart.configured():
        await worker_autostart.ensure_started(
            reason="authenticated_queue",connected=False)


api_v1.on_new_job = notify_new_job


async def _close_unresponsive_chrome():
    """A valid WebSocket alone is not proof that Chrome is responsive."""
    if (web2api_device is not None and web2api_last_seen_monotonic>0
            and time.monotonic()-web2api_last_seen_monotonic>75):
        print("[relay] authenticated Chrome heartbeat timed out",flush=True)
        # Finally-block fails a running job, never resends an uncertain prompt.
        await web2api_device.close(code=1011)


@app.on_event("startup")
async def boot_worker_recovery():
    global worker_watch_task
    # DB status may say "connected" from the previous Railway container.
    # After a deployment there is no live WebSocket until a v2 worker
    # actually authenticates. Do not expose that stale state as connected.
    if web2api_device is None:
        worker_autostart.worker_disconnected()
    if worker_watch_task is None:
        worker_watch_task=asyncio.create_task(worker_autostart.monitor_connected(
            check_connected=lambda:web2api_device is not None,
            close_stale=_close_unresponsive_chrome,
            interval=15))


@app.on_event("shutdown")
async def stop_worker_recovery():
    global worker_watch_task
    if worker_watch_task is not None:
        worker_watch_task.cancel()
        try:
            await worker_watch_task
        except asyncio.CancelledError:
            pass
        worker_watch_task=None


async def timeout_command(command_id: str):
    await asyncio.sleep(50)
    if command_id in pending:
        pending.pop(command_id, None)
        last_command.update({"id": command_id, "stage": "timeout"})
        await broadcast(event("command.error", id=command_id,
                              reason="Android did not confirm the command within 50 seconds"))

def token_equals(a: str, b: str) -> bool:
    return bool(b) and hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))

def event(kind: str, **data: Any):
    return {"type": kind, "ts": round(time.time() * 1000), **data}

async def transmit(ws: WebSocket, packet: dict[str, Any]):
    await ws.send_json(packet)

async def broadcast(packet: dict[str, Any]):
    recent.append(packet)
    for ws in list(consoles):
        try:
            await transmit(ws, packet)
        except Exception:
            consoles.discard(ws)

@app.middleware("http")
async def block_legacy_private_apis_in_public_test(request: Request, call_next):
    if PUBLIC_SMOKE_ONLY and request.url.path.startswith(("/api/v1", "/download/", "/docs", "/openapi.json", "/redoc")):
        return JSONResponse({"detail": "Previous private console disabled for public test"}, status_code=404)
    return await call_next(request)

@app.get("/")
async def home():
    return FileResponse(ROOT / "static" / "chat.html",
                        headers={"Cache-Control":"no-store, max-age=0",
                                 "X-Content-Type-Options":"nosniff",
                                 "Content-Security-Policy":"default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; connect-src 'self'; frame-src blob:; object-src 'none'; frame-ancestors 'none'", "Referrer-Policy":"no-referrer"})

@app.get("/integrations/public", include_in_schema=False)
def public_chat_page():
    return FileResponse(
        ROOT / "static" / "integrations-public.html",
        media_type="text/html; charset=utf-8",
        headers={"Cache-Control":"no-store",
                 "X-Content-Type-Options":"nosniff",
                 "Referrer-Policy":"no-referrer",
                 "Content-Security-Policy":
                    "default-src 'none'; script-src 'unsafe-inline'; "
                    "style-src 'unsafe-inline'; connect-src 'self'; "
                    "base-uri 'none'; frame-ancestors 'none'"}
    )


@app.get("/integrations/test", include_in_schema=False)
def web2api_user_test_page():
    """Human-operated one-shot live Chrome test; no automatic ChatGPT send."""
    return FileResponse(
        ROOT / "static" / "web2api-test.html",
        media_type="text/html; charset=utf-8",
        headers={"Cache-Control":"no-store, max-age=0",
                 "X-Content-Type-Options":"nosniff",
                 "Referrer-Policy":"no-referrer",
                 "Content-Security-Policy":
                    "default-src 'none'; script-src 'unsafe-inline'; "
                    "style-src 'unsafe-inline'; connect-src 'self'; "
                    "base-uri 'none'; form-action 'none'; frame-ancestors 'none'"}
    )


@app.get("/integrations/worker", include_in_schema=False)
def integration_worker_start_page():
    return FileResponse(
        ROOT / "static" / "integrations-worker.html",
        media_type="text/html; charset=utf-8",
        headers={"Cache-Control":"no-store",
                 "X-Content-Type-Options":"nosniff",
                 "Referrer-Policy":"no-referrer",
                 "Content-Security-Policy":
                   "default-src 'none'; script-src 'unsafe-inline'; "
                   "style-src 'unsafe-inline'; connect-src 'self'; "
                   "base-uri 'none'; frame-ancestors 'none'"}
    )


@app.get("/integrations/quick-start", include_in_schema=False)
def integration_quick_start_page():
    return FileResponse(
        ROOT / "static" / "integrations-quick-start.html",
        media_type="text/html; charset=utf-8",
        headers={"Cache-Control":"no-store",
                 "X-Content-Type-Options":"nosniff",
                 "Referrer-Policy":"no-referrer",
                 "Content-Security-Policy":
                    "default-src 'none'; style-src 'unsafe-inline'; "
                    "base-uri 'none'; frame-ancestors 'none'"}
    )


@app.get("/integrations/connect", include_in_schema=False)
def integration_admin_pairing_page():
    # The public test no longer asks users for login, API keys, or owner pairing.
    return RedirectResponse("/integrations/public", status_code=303,
                            headers={"Cache-Control":"no-store"})

@app.get("/integrations/docs", include_in_schema=False)
async def public_integration_reference():
    return FileResponse(
        ROOT / "static" / "integrations-quick-start.html",
        media_type="text/html",
        headers={"Cache-Control":"no-store","X-Content-Type-Options":"nosniff",
                 "Referrer-Policy":"no-referrer",
                 "Content-Security-Policy":
                 "default-src 'none'; style-src 'unsafe-inline'; "
                 "img-src 'self'; base-uri 'none'; frame-ancestors 'none'; "
                 "form-action 'none'"},
    )


@app.get("/integrations/openapi.yaml", include_in_schema=False)
async def public_integration_openapi():
    return FileResponse(ROOT / "static" / "integrations-public-openapi.yaml",
                        media_type="application/yaml",
                        headers={"X-Content-Type-Options":"nosniff"})


@app.get("/integrations/example_client.py", include_in_schema=False)
async def public_integration_python_example():
    return FileResponse(ROOT / "static" / "integrations-example-client.py",
                        filename="hitel_api_example_client.py",
                        media_type="text/plain",
                        headers={"X-Content-Type-Options":"nosniff"})


@app.get("/demo")
async def old_connection_test():
    return FileResponse(ROOT / "static" / "index.html",
                        headers={"Cache-Control":"no-store, max-age=0"})

@app.get("/download/ChatGPT-Relay-Control.apk")
async def download_controller():
    path = ROOT / "static" / "ChatGPT-Relay-Control.apk"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Android APK has not been published yet")
    return FileResponse(path, media_type="application/vnd.android.package-archive", filename="ChatGPT-Relay-Control.apk")

@app.get("/health")
async def health():
    return {"status": "ok", "deviceOnline": device is not None,
            "web2apiOnline": web2api_device is not None,
            "activeApiJob": active_job_id or next(iter(web2api_active_jobs), None),
            "consoleCount": len(consoles),
            "lastCommand": {"stage": last_command.get("stage", "idle")}}

@app.get("/demo/status")
async def demo_status():
    if not PUBLIC_SMOKE_ONLY:
        raise HTTPException(404)
    with api_v1.connection() as db:
        job = db.execute(
            "SELECT id,status,stage,result_text,created_at FROM jobs "
            "WHERE user_id=? AND room_id=? ORDER BY created_at DESC,id DESC LIMIT 1",
            (DEMO_UID, DEMO_ROOM),
        ).fetchone()
    state = job["status"] if job else "not_started"
    is_verified = bool(job and state == "completed"
                       and DEMO_MARKER in (job["result_text"] or ""))
    return {
        "server": "online",
        "workerConnected": web2api_device is not None,
        "testState": state,
        "testVerified": is_verified,
        "lastTestAt": job["created_at"] if job else None,
    }


@app.post("/demo/start")
async def demo_start(request: Request):
    if not PUBLIC_SMOKE_ONLY:
        raise HTTPException(404)
    # Browser test: no user-supplied text or file, no old private records.
    origin = request.headers.get("origin")
    host = request.headers.get("host", "").split(":")[0]
    if origin and origin != ("https://" + host) and origin != ("http://" + host):
        raise HTTPException(403, "Cross-site test requests denied")
    # Queue the fixed, isolated test even when the GitHub Chrome runner is
    # offline. A scheduled GitHub Actions workflow starts the runner when
    # this queue is non-empty. Do not expose a disabled button.
    if active_job_id or web2api_active_jobs:
        raise HTTPException(409, "Another test is already running")
    now = api_v1.clock()
    with api_v1.connection() as db:
        last = db.execute(
            "SELECT created_at FROM jobs WHERE user_id=? AND room_id=? "
            "ORDER BY created_at DESC LIMIT 1", (DEMO_UID, DEMO_ROOM),
        ).fetchone()
        if last and now - last["created_at"] < DEMO_COOLDOWN_MS:
            raise HTTPException(429, "Public test cooling down")
        db.execute(
            "INSERT OR IGNORE INTO users(id,name,api_key_hash,created_at) "
            "VALUES(?,?,?,?)",
            (DEMO_UID, "Isolated public connection test",
             "disabled-public-smoke-user-no-login", now),
        )
        db.execute(
            "INSERT OR IGNORE INTO rooms(id,user_id,title,android_state,created_at,updated_at) "
            "VALUES(?,?,?,?,?,?)",
            (DEMO_ROOM, DEMO_UID, "Web2API connection test", "uncreated", now, now),
        )
        job_id = api_v1.store_job(db, DEMO_UID, DEMO_ROOM, "chat.send", DEMO_QUESTION, [])
        db.execute(
            "INSERT INTO messages VALUES(?,?,?,?,?,?,?)",
            ("msg_" + api_v1.new_id(), DEMO_UID, DEMO_ROOM, job_id,
             "user", DEMO_QUESTION, now),
        )
    await dispatch_next()
    return {"started": True, "testState": "queued",
            "workerConnected": web2api_device is not None,
            "notice": "Test request queued. GitHub Actions picks it up when scheduled."}


@app.websocket("/ws")
async def socket(ws: WebSocket):
    global device, web2api_device, web2api_last_seen_monotonic, active_job_id, active_job_transport
    global worker_bootstrap_ready
    await ws.accept()
    role = ""
    actions_worker = False
    preflight_jobs: set[str] = set()  # per-authenticated-WebSocket only
    try:
        initial = await asyncio.wait_for(ws.receive_text(), timeout=10)
        if len(initial) > 12000:
            await ws.close(code=1009)
            return
        auth = json.loads(initial)
        role = str(auth.get("role", ""))
        if PUBLIC_SMOKE_ONLY and role != "web2api":
            await ws.close(code=1008)
            return
        token = str(auth.get("token", ""))
        expected = DEVICE_TOKEN if role == "device" else CONSOLE_TOKEN if role == "console" else ""
        valid_legacy = token_equals(token, expected)
        # Second, short-lived authentication path ONLY for the exact GitHub
        # Actions Chrome worker. The existing Android/console tokens stay
        # unchanged, and OIDC cannot authorize a console connection.
        oidc_token = auth.get("oidc_token", "") if role == "web2api" else ""
        valid_actions = bool(
            role == "web2api" and isinstance(oidc_token, str) and oidc_token
            and await asyncio.to_thread(verify_worker_identity, oidc_token)
        )
        if not (valid_legacy or valid_actions):
            await transmit(ws, event("auth.error", reason="Invalid credentials or tokens not configured"))
            await ws.close(code=1008)
            return
        actions_worker = valid_actions
        if role == "web2api" and valid_actions and auth.get("hitel_protocol_version") != 4:
            # Old workers have a single blocking Web2API driver and cannot
            # honor concurrent room-affine ownership. Fail closed: never send
            # 3 simultaneous messages to the old shared-tab implementation.
            await transmit(ws, event("auth.error", reason="WORKER_PROTOCOL_UPGRADE_REQUIRED"))
            await ws.close(code=1008)
            print("[relay-v1] refused outdated GitHub Chrome worker version",flush=True)
            return
        if role == "device":
            if auth.get("deviceId", DEVICE_ID) != DEVICE_ID:
                await ws.close(code=1008)
                return
            if device is not None and device is not ws:
                # Transfer ownership before any await. The previous socket
                # must not acknowledge a job subsequently assigned to this
                # new device session.
                previous_device = device
                device = ws
                if active_job_id and active_job_transport == "android":
                    api_v1.release_running_job(
                        active_job_id, "Android device session was superseded")
                    await broadcast(event(
                        "job.error", job_id=active_job_id,
                        reason="Device session replaced; not retried to avoid duplicates"))
                    active_job_id = None
                    active_job_transport = None
                await previous_device.close(code=1001)
            else:
                device = ws
            print("[relay] Android authenticated", flush=True)
            await transmit(ws, event("auth.ok", role="device"))
            await broadcast(event("device.status", online=True, deviceId=DEVICE_ID))
            await dispatch_next()
        elif role == "web2api":
            if auth.get("deviceId") != "web2api-main":
                await ws.close(code=1008)
                return
            if web2api_device is not None and web2api_device is not ws:
                old_worker = web2api_device
                web2api_device = ws
                for jid in list(web2api_active_jobs):
                    api_v1.update_job(
                        jid,status="unknown",stage="worker_replaced",
                        error="Chrome worker replaced; delivery unconfirmed; no retry")
                    long_job_events.observe(jid, "worker_replaced",
                        error_code="WORKER_CONNECTION_LOST",error_stage="worker_replaced")
                    web2api_active_jobs.pop(jid, None)
                await old_worker.close(code=1001)
            else:
                web2api_device = ws
            worker_bootstrap_ready=False
            worker_prewarm_targets.clear()
            web2api_last_seen_monotonic=time.monotonic()
            worker_autostart.worker_connected()
            print("[relay] GitHub Chrome worker authenticated", flush=True)
            await transmit(ws, event("auth.ok", role="web2api"))
            warm=linked_rooms_for_authenticated_worker()
            await transmit(ws,event("room.bootstrap",rooms=warm))
            print("[relay] requested signed Chrome prewarm for "+str(len(warm))+
                  " verified existing rooms",flush=True)
            await broadcast(event("web2api.status", online=True, worker="github-chrome"))
        else:
            consoles.add(ws)
            print("[relay] Web console authenticated", flush=True)
            await transmit(ws, event("auth.ok", role="console", deviceOnline=device is not None,
                                    web2apiOnline=web2api_device is not None))
            for packet in list(recent):
                await transmit(ws, packet)
        while True:
            raw = await ws.receive_text()
            if len(raw) > MAX_MESSAGE_SIZE:
                await ws.close(code=1009)
                break
            try:
                msg = json.loads(raw)
                kind = msg.get("type")
                if role == "web2api" and web2api_device is ws:
                    web2api_last_seen_monotonic=time.monotonic()
                    if kind == "worker.heartbeat":
                        for jid in tuple(web2api_active_jobs):
                            long_job_events.heartbeat(jid)
                        continue
                if role=="web2api" and kind=="room.bootstrap.done":
                    expected={x["room_id"] for x in linked_rooms_for_authenticated_worker()}
                    ready={}
                    received=msg.get("ready_rooms",[])
                    if isinstance(received,list):
                        for info in received:
                            if not isinstance(info,dict):
                                continue
                            rid,tid=info.get("room_id"),info.get("target_id")
                            if (rid in expected and isinstance(tid,str)
                                and 8<=len(tid)<=100):
                                ready[rid]=tid
                    # A lone browser heartbeat cannot be mistaken for two
                    # independently prewarmed and navigated conversation tabs.
                    worker_prewarm_targets.clear()
                    worker_prewarm_targets.update(ready)
                    worker_bootstrap_ready=(bool(expected)
                        and expected==set(ready)
                        and len(set(ready.values()))==len(ready))
                    print("[relay] signed room-tabs prewarm verified="
                        +str(len(ready))+"/"+str(len(expected)),flush=True)
                    if worker_bootstrap_ready:
                        await dispatch_next()
                    continue
                if kind == "ping":
                    await transmit(ws, event("pong"))
                    continue
                if role == "console":
                    if kind != "command":
                        continue
                    if active_job_id:
                        await transmit(ws, event("command.error", reason="API job in progress; use /api/v1/jobs"))
                        continue
                    cmd_id = str(msg.get("id", ""))[:80]
                    action = str(msg.get("action", ""))
                    payload = msg.get("payload", {})
                    if action in ROOM_SCOPED_ONLY:
                        await transmit(ws, event("command.error", id=cmd_id,
                            reason="ROOM_SCOPED_API_REQUIRED: use /api/v1/rooms/{room_id}/turns"))
                        continue
                    if action not in ALLOWED or not cmd_id or not isinstance(payload, dict):
                        await transmit(ws, event("command.error", id=cmd_id, reason="Invalid command"))
                        continue
                    if action == "chat.send" and (not isinstance(payload.get("text"), str) or not 0 < len(payload["text"]) <= 24000):
                        await transmit(ws, event("command.error", id=cmd_id, reason="Invalid text"))
                        continue
                    if cmd_id in pending:
                        await transmit(ws, event("command.error", id=cmd_id, reason="Duplicate command"))
                        continue
                    if device is None:
                        await transmit(ws, event("command.error", id=cmd_id, reason="Android device offline"))
                        continue
                    pending[cmd_id] = {"action": action, "created": time.monotonic()}
                    last_command.update({"id": cmd_id, "stage": "accepted"})
                    print(f"[relay] command accepted action={action} id={cmd_id[:8]}", flush=True)
                    await transmit(ws, event("command.accepted", id=cmd_id, action=action))
                    try:
                        await transmit(device, event("command", id=cmd_id, action=action, payload=payload))
                        last_command["stage"] = "forwarded"
                        print(f"[relay] command forwarded id={cmd_id[:8]}", flush=True)
                        await broadcast(event("command.queued", id=cmd_id, action=action))
                        asyncio.create_task(timeout_command(cmd_id))
                    except Exception:
                        pending.pop(cmd_id, None)
                        await transmit(ws, event("command.error", id=cmd_id, reason="Device transport failed"))
                elif role in ("device", "web2api"):
                    if (role == "device" and device is not ws) or (
                            role == "web2api" and web2api_device is not ws):
                        # A replaced WebSocket is no longer authorized to
                        # mutate the currently active job or its room state.
                        await ws.close(code=1008)
                        break
                    if role == "web2api" and kind == "job.preflight":
                        # A separate, server-authorized gate immediately before
                        # the browser worker submits any account-bound text.
                        # A queued/deleted/foreign-room job is never approved.
                        jid = msg.get("job_id")
                        rid = msg.get("room_id")
                        aid = msg.get("account_id")
                        email = msg.get("execution_account_email")
                        approved = bool(
                            actions_worker
                            and isinstance(jid,str)
                            and jid in web2api_active_jobs
                            and web2api_active_jobs[jid] == rid
                            and api_v1.authorize_web2api_preflight(jid,rid,aid,email)
                        )
                        if approved:
                            preflight_jobs.add(jid)
                        await transmit(ws,event(
                            "job.preflight.ok" if approved else "job.preflight.denied",
                            job_id=jid if isinstance(jid,str) else "",
                            room_id=rid if isinstance(rid,str) else "",
                        ))
                        continue
                    if kind in {"job.received", "job.progress", "job.result", "job.error", "job.uncertain"}:
                        jid = str(msg.get("job_id", ""))
                        if role == "web2api":
                            if jid not in web2api_active_jobs:
                                continue
                            if msg.get("room_id") != web2api_active_jobs[jid]:
                                continue
                        elif jid != active_job_id or active_job_transport != "android":
                            continue
                        if kind == "job.uncertain":
                            # A lost upstream HTTP response does not prove AI failure.
                            # Preserve the same job_id; never auto-resubmit.
                            reason = str(msg.get("reason", "UPSTREAM_DELIVERY_UNKNOWN"))[:100]
                            api_v1.update_job(jid,status="unknown",
                                stage="upstream_delivery_unknown",error=reason)
                            long_job_events.observe(
                                jid,"upstream_delivery_unknown",
                                error_code=reason,error_stage="upstream_delivery_unknown")
                            web2api_active_jobs.pop(jid,None)
                            preflight_jobs.discard(jid)
                            integration_agent_stream.notify_job_changed(jid)
                            await dispatch_next()
                            continue
                        if kind in {"job.received", "job.progress"}:
                            stage = str(msg.get("stage", kind))[:100]
                            api_v1.update_job(jid, stage=stage)
                            if role=="web2api":
                                long_job_events.observe(
                                    jid,"worker_received" if kind=="job.received" else stage,
                                    # UI acknowledgment is not an upstream HTTP
                                    # acceptance receipt; only mark the matching
                                    # user's rendered send as observed.
                                    send_confirmed=(stage=="web2api_send_ui_acknowledged"),
                                    reply_observed=(stage in {
                                        "web2api_assistant_seen",
                                        "web2api_turn_completed",
                                        "web2api_adapter_reply_parsed",
                                    }))
                            await broadcast(event(kind, job_id=jid, stage=stage))
                            integration_agent_stream.notify_job_changed(jid)
                        else:
                            # Never trust a device-reported room_id as the target
                            # for a job. Bind successful acknowledgements to the
                            # *server-assigned* room of the currently running job.
                            # A mismatched room must fail closed before any
                            # assistant message or room state can be recorded.
                            with api_v1.connection() as c:
                                assigned = c.execute(
                                    "SELECT room_id,action,account_id,user_id FROM jobs WHERE id=? AND status='running'",
                                    (jid,),
                                ).fetchone()
                                # Bind the returned browser identity to the
                                # OpenAI-verified email of the owner of this job.
                                # Neither account ID nor expected email from the
                                # worker is authoritative; never trust a UI label.
                                verified_account = None
                                if assigned and assigned["account_id"]:
                                    verified_account = c.execute("""
                                        SELECT a.email FROM hitel_verified_chatgpt_accounts a
                                        JOIN web_trial_profiles p ON p.owner_hash=a.browser_owner
                                        WHERE a.id=? AND p.user_id=?
                                          AND a.issuer IN ('https://auth.openai.com','urn:hitel:chatgpt:github-actions-verified-browser')
                                          AND a.email IS NOT NULL AND a.email!='' LIMIT 1
                                    """, (assigned["account_id"], assigned["user_id"])).fetchone()
                            assigned_room = assigned["room_id"] if assigned else None
                            action = assigned["action"] if assigned else None
                            reported_room = msg.get("room_id")
                            identity_ok = bool(
                                assigned_room and isinstance(reported_room, str)
                                and reported_room == assigned_room
                            )
                            # An account-bound job must never be accepted under
                            # a different Chrome login, even if a worker reports
                            # a valid room and response. No credentials are sent.
                            account_bound = bool(assigned and assigned["account_id"])
                            account_mismatch = bool(
                                role == "web2api" and account_bound and
                                msg.get("execution_account_id") != assigned["account_id"]
                            )
                            claimed_success = kind == "job.result" and msg.get("verified") is True
                            reported_stage = str(msg.get("stage", ""))[:100]
                            expected_stage = {
                                "chat.send": "assistant_reply_stable",
                                "room.bind": "assistant_reply_stable",
                                "room.open": "room_open_verified",
                            }.get(action)
                            output = msg.get("result_text", "")
                            if not isinstance(output,str):
                                output = ""
                            reply_too_large=(len(output.encode("utf-8"))>MAX_FINAL_REPLY_BYTES)
                            if reply_too_large:
                                output = ""
                                claimed_success = False
                            proof_ok = bool(
                                expected_stage and reported_stage == expected_stage
                                and (action == "room.open" or output.strip())
                            )
                            # Do not mutate a room until verified result and
                            # conversation URL are committed together.
                            # Only a signed GitHub worker that checked the
                            # actual ChatGPT HTTPS session may attest to the
                            # execution email; the server compares this with
                            # its separately stored, verified OpenAI account.
                            # The bare account ID alone can never pass.
                            actual_email = msg.get("execution_account_email")
                            expected_email = (verified_account["email"]
                                              if verified_account else None)
                            email_verified = bool(
                                actions_worker and role == "web2api"
                                and jid in preflight_jobs
                                and msg.get("session_verified") is True
                                and isinstance(actual_email, str) and actual_email.strip()
                                and isinstance(expected_email, str) and expected_email.strip()
                                and actual_email.strip().casefold() == expected_email.strip().casefold()
                            )
                            account_not_verified = bool(account_bound and not email_verified)
                            good = (claimed_success and identity_ok and proof_ok
                                    and not account_mismatch and not account_not_verified)
                            mismatch = claimed_success and not identity_ok
                            invalid_proof = claimed_success and identity_ok and not proof_ok
                            wrong_browser_chat = False
                            stage = ("REPLY_TOO_LARGE_NO_TRUNCATION" if reply_too_large else
                                     "ROOM_ID_MISMATCH" if mismatch else
                                     "ACCOUNT_ID_MISMATCH" if account_mismatch else
                                     "ACCOUNT_EXECUTION_NOT_VERIFIED" if account_not_verified else
                                     "UNVERIFIED_JOB_COMPLETION" if invalid_proof else
                                     "ROOM_CONVERSATION_ID_MISMATCH" if wrong_browser_chat else
                                     reported_stage or ("completed" if good else "failed"))
                            reason = ("Assistant reply exceeds verified transport maximum; never truncated" if reply_too_large else
                                      "Worker completion room_id did not match the assigned job room"
                                      if mismatch else
                                      "Chrome execution account differs from request account"
                                      if account_mismatch else
                                      "Worker did not prove matching live ChatGPT session email"
                                      if account_not_verified else
                                      "Worker completion did not provide action-specific verification"
                                      if invalid_proof else
                                      "Web2API conversation did not match its assigned room"
                                      if wrong_browser_chat else
                                      str(msg.get("reason", "Remote action was not verified"))[:500])
                            # A verified OIDC worker is not an Android app.
                            # It must prove the *returned* conversation URL,
                            # not merely report a success stage. Only persist
                            # the returned assistant text atomically with the
                            # room URL when the server also validates its scope.
                            saved_by_web2api = False
                            if good and actions_worker:
                                url = msg.get("chatgpt_url")
                                if action != "chat.send" or not isinstance(url, str):
                                    good = False
                                else:
                                    saved_by_web2api = api_v1.complete_web2api_job(
                                        jid, assigned_room, output, url)
                                    good = saved_by_web2api
                                if not good:
                                    stage = "ROOM_CONVERSATION_ID_MISMATCH"
                                    reason = "Chrome worker conversation URL or job scope not verified"
                            if not saved_by_web2api:
                                api_v1.update_job(jid, status="completed" if good else "failed",
                                                  stage=stage, result_text=output if good else None,
                                                  error=None if good else reason)
                            if role=="web2api":
                                long_job_events.observe(
                                    jid,"assistant_reply_verified" if good else "worker_reported_failure",
                                    send_confirmed=good,reply_observed=good,
                                    error_code=None if good else stage,
                                    error_stage=None if good else stage)
                            if good and msg.get("room_state") and not saved_by_web2api:
                                api_v1.set_room_android_state(
                                    assigned_room, str(msg["room_state"]),
                                    str(msg.get("android_title", "")) or None)
                            await broadcast(event("job.result" if good else "job.error",
                                                  job_id=jid, verified=good,
                                                  stage=stage, result_text=output,
                                                  reason=None if good else reason))
                            print(f"[relay-v1] job={jid[:12]} verified={good} stage={stage}",flush=True)
                            # Wake only subscribers for this validated job.
                            # Agent sockets still read signed results from DB
                            # and reject any room/request/job mismatch.
                            integration_agent_stream.notify_job_changed(jid)
                            # Acknowledgment is sent only AFTER the ChatGPT reply
                            # and conversation URL have been durably stored by
                            # complete_web2api_job. The worker may then close
                            # only its own idle temporary Chrome tab.
                            if role == "web2api" and good and saved_by_web2api:
                                await transmit(ws,event(
                                    "job.committed", job_id=jid,
                                    room_id=assigned_room, verified=True))
                            preflight_jobs.discard(jid)
                            if role == "web2api":
                                web2api_active_jobs.pop(jid, None)
                            else:
                                active_job_id = None
                                active_job_transport = None
                            await dispatch_next()
                    elif role == "device" and kind in {"command.received", "command.progress", "command.result", "command.error"}:
                        cmd_id = str(msg.get("id", ""))[:80]
                        if cmd_id not in pending:
                            continue
                        if kind in {"command.received", "command.progress"}:
                            stage = str(msg.get("stage", "received"))[:100]
                            last_command.update({"id": cmd_id, "stage": stage})
                            print(f"[relay] Android stage={stage} id={cmd_id[:8]}", flush=True)
                            await broadcast(event(kind, id=cmd_id, stage=stage))
                        else:
                            pending.pop(cmd_id, None)
                            last_command.update({"id": cmd_id, "stage": "done" if kind == "command.result" else "failed"})
                            print(f"[relay] Android completed type={kind} id={cmd_id[:8]}", flush=True)
                            await broadcast({"type": kind, "id": cmd_id, "result": msg.get("result"), "reason": msg.get("reason"), "ts": round(time.time()*1000)})
                    elif role == "device" and kind == "ui.snapshot":
                        nodes = msg.get("nodes", [])
                        if isinstance(nodes, list):
                            await broadcast(event("ui.snapshot", nodes=nodes[:150], package="com.openai.chatgpt"))
                    elif role == "device" and kind == "device.log":
                        await broadcast(event("device.log", level=str(msg.get("level", "info"))[:16], message=str(msg.get("message", ""))[:500]))
            except (ValueError, TypeError, KeyError):
                await transmit(ws, event("protocol.error", reason="Invalid JSON message"))
    except (WebSocketDisconnect, asyncio.TimeoutError):
        pass
    finally:
        if role == "console":
            consoles.discard(ws)
        elif role == "device" and device is ws:
            device = None
            if active_job_id and active_job_transport == "android":
                api_v1.release_running_job(active_job_id)
                await broadcast(event(
                    "job.error", job_id=active_job_id,
                    reason="Android disconnected; not automatically retried"))
                active_job_id = None
                active_job_transport = None
            for cmd_id in list(pending):
                pending.pop(cmd_id, None)
                await broadcast(event("command.error", id=cmd_id,
                                      reason="Android device disconnected"))
            await broadcast(event("device.status", online=False, deviceId=DEVICE_ID))
            await dispatch_next()
        elif role == "web2api" and web2api_device is ws:
            worker_bootstrap_ready=False
            worker_prewarm_targets.clear()
            web2api_device = None
            for jid in list(web2api_active_jobs):
                api_v1.update_job(
                    jid,status="unknown",stage="connection_lost",
                    error="GitHub Chrome disconnected; delivery unconfirmed; no retry")
                long_job_events.observe(
                    jid,"worker_connection_lost",
                    error_code="WORKER_CONNECTION_LOST",error_stage="connection_lost")
                web2api_active_jobs.pop(jid,None)
            web2api_last_seen_monotonic=0.0
            worker_autostart.worker_disconnected()
            await broadcast(event("web2api.status", online=False, worker="github-chrome"))
            # The next authenticated request or Railway supervisor may start
            # another worker, without repeating an unverified ChatGPT send.
            if worker_autostart.configured() and worker_autostart.pending_count()>0:
                await worker_autostart.ensure_started(reason="chrome_disconnected",connected=False)
            await dispatch_next()
