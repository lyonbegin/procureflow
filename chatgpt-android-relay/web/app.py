import asyncio
import hmac
import json
import os
import time
from collections import deque
from pathlib import Path
from typing import Any
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
import api_v1
import drive_v1
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
CONSOLE_TOKEN = os.environ.get("CONSOLE_TOKEN", "")
DEVICE_TOKEN = os.environ.get("DEVICE_TOKEN", "")
DEVICE_ID = "android-main"
MAX_MESSAGE_SIZE = 100_000
# Legacy console commands have no verified room_id. Never let them
# submit a prompt or create a thread in whichever chat happens to be foreground.
ALLOWED = {"chat.stop", "ui.snapshot", "ui.back"}
ROOM_SCOPED_ONLY = {"chat.send", "chat.new"}
consoles: set[WebSocket] = set()
device: WebSocket | None = None  # existing native Android, unchanged
web2api_device: WebSocket | None = None  # separate GitHub Chrome runner
pending: dict[str, dict[str, Any]] = {}
recent: deque[dict[str, Any]] = deque(maxlen=30)
last_command: dict[str, Any] = {"stage": "idle"}
active_job_id: str | None = None
active_job_transport: str | None = None
job_dispatch_lock = asyncio.Lock()
recovery_checked = False

async def dispatch_next():
    global active_job_id, active_job_transport, recovery_checked
    if active_job_id or (device is None and web2api_device is None):
        return
    async with job_dispatch_lock:
        if active_job_id or (device is None and web2api_device is None):
            return
        if not recovery_checked:
            recovered = 0 if PUBLIC_SMOKE_ONLY else api_v1.fail_orphaned_running_jobs()
            recovery_checked = True
            if recovered:
                print(f"[relay-v1] recovery: failed {recovered} orphaned jobs; no auto-retry", flush=True)
        failed_missing = 0 if PUBLIC_SMOKE_ONLY else api_v1.fail_queued_jobs_with_unavailable_files()
        if failed_missing:
            print(f"[relay-v1] failed {failed_missing} queued jobs with missing attachments", flush=True)
        job = api_v1.claim_next_job(only_user_id=DEMO_UID if PUBLIC_SMOKE_ONLY else None)
        if job is None:
            return

        # Native attachments and original Android controls remain routed to
        # Android when it is connected. Text-only chat prefers GitHub Chrome.
        prefer_web = (web2api_device is not None and
                      job["action"] == "chat.send" and
                      not job.get("attachment_ids"))
        if prefer_web:
            receiver, transport = web2api_device, "web2api"
        elif device is not None:
            receiver, transport = device, "android"
        else:
            # Browser worker will explicitly fail unsupported/file actions;
            # never pretend that it attached an original binary file.
            receiver, transport = web2api_device, "web2api"
        active_job_id = job["id"]
        active_job_transport = transport
        try:
            await transmit(receiver, event("job", job=job))
            await broadcast(event("job.dispatched", job_id=job["id"], room_id=job["room_id"],
                                  action=job["action"], user_id=job["user_id"], worker=transport))
            print(f"[relay-v1] dispatched job={job['id'][:12]} room={job['room_id'][:12]} via={transport}", flush=True)
            asyncio.create_task(job_timeout(job["id"]))
        except Exception:
            api_v1.release_running_job(job["id"], "Worker transport interrupted; not auto-retried")
            active_job_id = None
            active_job_transport = None


async def job_timeout(job_id: str):
    global active_job_id, active_job_transport
    await asyncio.sleep(150)
    if active_job_id == job_id:
        api_v1.update_job(job_id, status="failed", stage="timed_out",
                          error="No verified worker completion after 150 seconds")
        active_job_id = None
        active_job_transport = None
        await broadcast(event("job.error", job_id=job_id, reason="Timeout"))
        await dispatch_next()


api_v1.on_new_job = dispatch_next


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
    return FileResponse(ROOT / "static" / "index.html", headers={"Cache-Control": "no-store, max-age=0"})

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
            "activeApiJob": active_job_id,
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
    if active_job_id:
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
    global device, web2api_device, active_job_id, active_job_transport
    await ws.accept()
    role = ""
    actions_worker = False
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
                if active_job_id and active_job_transport == "web2api":
                    api_v1.release_running_job(
                        active_job_id, "Chrome worker session replaced; no automatic retry")
                    await broadcast(event(
                        "job.error", job_id=active_job_id,
                        reason="Chrome worker replaced; not retried"))
                    active_job_id = None
                    active_job_transport = None
                await old_worker.close(code=1001)
            else:
                web2api_device = ws
            print("[relay] GitHub Chrome worker authenticated", flush=True)
            await transmit(ws, event("auth.ok", role="web2api"))
            await broadcast(event("web2api.status", online=True, worker="github-chrome"))
            await dispatch_next()
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
                    if kind in {"job.received", "job.progress", "job.result", "job.error"}:
                        jid = str(msg.get("job_id", ""))
                        if jid != active_job_id or active_job_transport != ("android" if role == "device" else "web2api"):
                            continue
                        if kind in {"job.received", "job.progress"}:
                            stage = str(msg.get("stage", kind))[:100]
                            api_v1.update_job(jid, stage=stage)
                            await broadcast(event(kind, job_id=jid, stage=stage))
                        else:
                            # Never trust a device-reported room_id as the target
                            # for a job. Bind successful acknowledgements to the
                            # *server-assigned* room of the currently running job.
                            # A mismatched room must fail closed before any
                            # assistant message or room state can be recorded.
                            with api_v1.connection() as c:
                                assigned = c.execute(
                                    "SELECT room_id,action FROM jobs WHERE id=? AND status='running'",
                                    (jid,),
                                ).fetchone()
                            assigned_room = assigned["room_id"] if assigned else None
                            action = assigned["action"] if assigned else None
                            reported_room = msg.get("room_id")
                            identity_ok = bool(
                                assigned_room and isinstance(reported_room, str)
                                and reported_room == assigned_room
                            )
                            claimed_success = kind == "job.result" and msg.get("verified") is True
                            reported_stage = str(msg.get("stage", ""))[:100]
                            expected_stage = {
                                "chat.send": "assistant_reply_stable",
                                "room.bind": "assistant_reply_stable",
                                "room.open": "room_open_verified",
                            }.get(action)
                            output = str(msg.get("result_text", ""))[:100000]
                            proof_ok = bool(
                                expected_stage and reported_stage == expected_stage
                                and (action == "room.open" or output.strip())
                            )
                            # Do not mutate a room until verified result and
                            # conversation URL are committed together.
                            good = claimed_success and identity_ok and proof_ok
                            mismatch = claimed_success and not identity_ok
                            invalid_proof = claimed_success and identity_ok and not proof_ok
                            wrong_browser_chat = False
                            stage = ("ROOM_ID_MISMATCH" if mismatch else
                                     "UNVERIFIED_JOB_COMPLETION" if invalid_proof else
                                     "ROOM_CONVERSATION_ID_MISMATCH" if wrong_browser_chat else
                                     reported_stage or ("completed" if good else "failed"))
                            reason = ("Worker completion room_id did not match the assigned job room"
                                      if mismatch else
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
                            if good and msg.get("room_state") and not saved_by_web2api:
                                api_v1.set_room_android_state(
                                    assigned_room, str(msg["room_state"]),
                                    str(msg.get("android_title", "")) or None)
                            await broadcast(event("job.result" if good else "job.error",
                                                  job_id=jid, verified=good,
                                                  stage=stage, result_text=output,
                                                  reason=None if good else reason))
                            print(f"[relay-v1] job={jid[:12]} verified={good} stage={stage}",flush=True)
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
            web2api_device = None
            if active_job_id and active_job_transport == "web2api":
                api_v1.release_running_job(
                    active_job_id, "GitHub Chrome disconnected; not automatically retried")
                await broadcast(event(
                    "job.error", job_id=active_job_id,
                    reason="GitHub Chrome disconnected; not automatically retried"))
                active_job_id = None
                active_job_transport = None
            await broadcast(event("web2api.status", online=False, worker="github-chrome"))
            await dispatch_next()
