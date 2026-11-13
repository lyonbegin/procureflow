import asyncio
import hmac
import json
import os
import time
from collections import deque
from pathlib import Path
from typing import Any
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import FileResponse
import api_v1
import drive_v1
from gh_oidc import verify_worker_identity

ROOT = Path(__file__).resolve().parent
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
device: WebSocket | None = None
pending: dict[str, dict[str, Any]] = {}
recent: deque[dict[str, Any]] = deque(maxlen=30)
last_command: dict[str, Any] = {"stage": "idle"}
active_job_id: str | None = None
job_dispatch_lock = asyncio.Lock()
recovery_checked = False

async def dispatch_next():
    global active_job_id, recovery_checked
    if device is None or active_job_id:
        return
    async with job_dispatch_lock:
        if device is None or active_job_id:
            return
        if not recovery_checked:
            recovered = api_v1.fail_orphaned_running_jobs()
            recovery_checked = True
            if recovered:
                print(f"[relay-v1] recovery: failed {recovered} orphaned jobs; no auto-retry", flush=True)
        failed_missing = api_v1.fail_queued_jobs_with_unavailable_files()
        if failed_missing:
            print(f"[relay-v1] failed {failed_missing} queued jobs with missing attachments", flush=True)
        job = api_v1.claim_next_job()
        if job is None:
            return
        active_job_id = job["id"]
        try:
            await transmit(device, event("job", job=job))
            await broadcast(event("job.dispatched", job_id=job["id"], room_id=job["room_id"],
                                  action=job["action"], user_id=job["user_id"]))
            print(f"[relay-v1] dispatched job={job['id'][:12]} room={job['room_id'][:12]}", flush=True)
            asyncio.create_task(job_timeout(job["id"]))
        except Exception as exc:
            api_v1.release_running_job(job["id"], "Device transport: " + str(exc))
            active_job_id = None

async def job_timeout(job_id: str):
    global active_job_id
    await asyncio.sleep(150)
    if active_job_id == job_id:
        api_v1.update_job(job_id, status="failed", stage="timed_out",
                          error="No verified Android completion after 150 seconds")
        active_job_id = None
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

@app.get("/")
async def home():
    return FileResponse(ROOT / "static" / "index.html")

@app.get("/download/ChatGPT-Relay-Control.apk")
async def download_controller():
    path = ROOT / "static" / "ChatGPT-Relay-Control.apk"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Android APK has not been published yet")
    return FileResponse(path, media_type="application/vnd.android.package-archive", filename="ChatGPT-Relay-Control.apk")

@app.get("/health")
async def health():
    return {"status": "ok", "deviceOnline": device is not None,
            "activeApiJob": active_job_id,
            "consoleCount": len(consoles),
            "lastCommand": {"stage": last_command.get("stage", "idle")}}

@app.websocket("/ws")
async def socket(ws: WebSocket):
    global device, active_job_id
    await ws.accept()
    role = ""
    try:
        initial = await asyncio.wait_for(ws.receive_text(), timeout=10)
        if len(initial) > 4096:
            await ws.close(code=1009)
            return
        auth = json.loads(initial)
        role = str(auth.get("role", ""))
        token = str(auth.get("token", ""))
        expected = DEVICE_TOKEN if role == "device" else CONSOLE_TOKEN if role == "console" else ""
        valid_legacy = token_equals(token, expected)
        # Second, short-lived authentication path ONLY for the exact GitHub
        # Actions Chrome worker. The existing Android/console tokens stay
        # unchanged, and OIDC cannot authorize a console connection.
        oidc_token = auth.get("oidc_token", "") if role == "device" else ""
        valid_actions = bool(
            role == "device" and isinstance(oidc_token, str) and oidc_token
            and await asyncio.to_thread(verify_worker_identity, oidc_token)
        )
        if not (valid_legacy or valid_actions):
            await transmit(ws, event("auth.error", reason="Invalid credentials or tokens not configured"))
            await ws.close(code=1008)
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
                if active_job_id:
                    api_v1.release_running_job(
                        active_job_id, "Android device session was superseded")
                    await broadcast(event(
                        "job.error", job_id=active_job_id,
                        reason="Device session replaced; not retried to avoid duplicates"))
                    active_job_id = None
                await previous_device.close(code=1001)
            else:
                device = ws
            print("[relay] Android authenticated", flush=True)
            await transmit(ws, event("auth.ok", role="device"))
            await broadcast(event("device.status", online=True, deviceId=DEVICE_ID))
            await dispatch_next()
        else:
            consoles.add(ws)
            print("[relay] Web console authenticated", flush=True)
            await transmit(ws, event("auth.ok", role="console", deviceOnline=device is not None))
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
                elif role == "device":
                    if device is not ws:
                        # A replaced WebSocket is no longer authorized to
                        # mutate the currently active job or its room state.
                        await ws.close(code=1008)
                        break
                    if kind in {"job.received", "job.progress", "job.result", "job.error"}:
                        jid = str(msg.get("job_id", ""))
                        if jid != active_job_id:
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
                            good = claimed_success and identity_ok and proof_ok
                            mismatch = claimed_success and not identity_ok
                            invalid_proof = claimed_success and identity_ok and not proof_ok
                            stage = ("ROOM_ID_MISMATCH" if mismatch else
                                     "UNVERIFIED_JOB_COMPLETION" if invalid_proof else
                                     reported_stage or ("completed" if good else "failed"))
                            reason = ("Android completion room_id did not match the assigned job room"
                                      if mismatch else
                                      "Android completion did not provide action-specific verification"
                                      if invalid_proof else
                                      str(msg.get("reason", "Android action was not verified"))[:500])
                            api_v1.update_job(jid, status="completed" if good else "failed",
                                              stage=stage, result_text=output if good else None,
                                              error=None if good else reason)
                            if good and msg.get("room_state"):
                                api_v1.set_room_android_state(
                                    assigned_room, str(msg["room_state"]),
                                    str(msg.get("android_title", "")) or None)
                            await broadcast(event("job.result" if good else "job.error",
                                                  job_id=jid, verified=good,
                                                  stage=stage, result_text=output,
                                                  reason=None if good else reason))
                            print(f"[relay-v1] job={jid[:12]} verified={good} stage={stage}",flush=True)
                            active_job_id = None
                            await dispatch_next()
                    elif kind in {"command.received", "command.progress", "command.result", "command.error"}:
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
                    elif kind == "ui.snapshot":
                        nodes = msg.get("nodes", [])
                        if isinstance(nodes, list):
                            await broadcast(event("ui.snapshot", nodes=nodes[:150], package="com.openai.chatgpt"))
                    elif kind == "device.log":
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
            if active_job_id:
                api_v1.release_running_job(active_job_id)
                await broadcast(event("job.error",job_id=active_job_id,
                                      reason="Device disconnected; not automatically retried to prevent duplicate submissions"))
                active_job_id = None
            for cmd_id in list(pending):
                pending.pop(cmd_id, None)
                await broadcast(event("command.error", id=cmd_id, reason="Android device disconnected"))
            await broadcast(event("device.status", online=False, deviceId=DEVICE_ID))
