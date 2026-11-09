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

ROOT = Path(__file__).resolve().parent
app = FastAPI(title="ChatGPT Android Relay", docs_url=None, redoc_url=None)
CONSOLE_TOKEN = os.environ.get("CONSOLE_TOKEN", "")
DEVICE_TOKEN = os.environ.get("DEVICE_TOKEN", "")
DEVICE_ID = "android-main"
MAX_MESSAGE_SIZE = 100_000
ALLOWED = {"chat.send", "chat.new", "chat.stop", "ui.snapshot", "ui.back"}
consoles: set[WebSocket] = set()
device: WebSocket | None = None
pending: dict[str, dict[str, Any]] = {}
recent: deque[dict[str, Any]] = deque(maxlen=30)

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
    return {"status": "ok", "deviceOnline": device is not None, "consoleCount": len(consoles)}

@app.websocket("/ws")
async def socket(ws: WebSocket):
    global device
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
        if not token_equals(token, expected):
            await transmit(ws, event("auth.error", reason="Invalid credentials or tokens not configured"))
            await ws.close(code=1008)
            return
        if role == "device":
            if auth.get("deviceId", DEVICE_ID) != DEVICE_ID:
                await ws.close(code=1008)
                return
            if device is not None and device is not ws:
                await device.close(code=1001)
            device = ws
            await transmit(ws, event("auth.ok", role="device"))
            await broadcast(event("device.status", online=True, deviceId=DEVICE_ID))
        else:
            consoles.add(ws)
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
                    cmd_id = str(msg.get("id", ""))[:80]
                    action = str(msg.get("action", ""))
                    payload = msg.get("payload", {})
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
                    try:
                        await transmit(device, event("command", id=cmd_id, action=action, payload=payload))
                        await broadcast(event("command.queued", id=cmd_id, action=action))
                    except Exception:
                        pending.pop(cmd_id, None)
                        await transmit(ws, event("command.error", id=cmd_id, reason="Device transport failed"))
                elif role == "device":
                    if kind in {"command.result", "command.error"}:
                        cmd_id = str(msg.get("id", ""))[:80]
                        if cmd_id not in pending:
                            continue
                        pending.pop(cmd_id, None)
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
            for cmd_id in list(pending):
                pending.pop(cmd_id, None)
                await broadcast(event("command.error", id=cmd_id, reason="Android device disconnected"))
            await broadcast(event("device.status", online=False, deviceId=DEVICE_ID))
