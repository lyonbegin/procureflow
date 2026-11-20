#!/usr/bin/env python3
"""Browserless HITEL v4 WebSocket worker. NO Chrome/CDP/UI imports or processes.

Manual promotion only: HITEL_DIRECT_ENABLE_PRODUCTION=1 is required even to
connect to the existing signed Relay. Readiness and source-account binding are
checked BEFORE connecting; absent credentials do not trigger fake PASS.
"""
from __future__ import annotations
import asyncio
import json
import os
import re
import time
import urllib.parse
import urllib.request
from typing import Any

import websockets

from hitel_direct_http_transport import DirectError, DirectWeb2API, ROOM_RE, conversation_from_url

AUDIENCE = "urn:lyonbegin:procureflow:chatgpt-relay:device"
RELAY = "wss://hitel-integration-api-production.up.railway.app/ws"
MAX_CONCURRENT = 3
MAX_PAYLOAD = 24000
JOB_RE = re.compile(r"^job_[a-f0-9]{32}$")


def _oidc_token() -> str:
    url = os.getenv("ACTIONS_ID_TOKEN_REQUEST_URL", "")
    bearer = os.getenv("ACTIONS_ID_TOKEN_REQUEST_TOKEN", "")
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname or not bearer:
        raise DirectError("DIRECT_GITHUB_OIDC_UNAVAILABLE")
    target = url + ("&" if parsed.query else "?") + urllib.parse.urlencode({"audience": AUDIENCE})
    req = urllib.request.Request(target, headers={"Authorization": "Bearer " + bearer,
                                                   "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as response:
        payload = json.load(response)
    token = payload.get("value") if isinstance(payload, dict) else None
    if not isinstance(token, str) or len(token) < 50:
        raise DirectError("DIRECT_GITHUB_OIDC_INVALID")
    return token


def _job_contract(job: dict[str, Any]) -> tuple[str, str, str, str | None]:
    if not isinstance(job, dict):
        raise DirectError("DIRECT_JOB_INVALID")
    jid, rid, content = job.get("id"), job.get("room_id"), job.get("text")
    if not isinstance(jid, str) or not JOB_RE.fullmatch(jid):
        raise DirectError("DIRECT_JOB_ID_INVALID")
    if not isinstance(rid, str) or not ROOM_RE.fullmatch(rid):
        raise DirectError("DIRECT_JOB_ROOM_INVALID")
    if job.get("action") != "chat.send":
        raise DirectError("DIRECT_JOB_ACTION_UNSUPPORTED")
    if not isinstance(content, str) or not content.strip() or len(content) > MAX_PAYLOAD:
        raise DirectError("DIRECT_JOB_TEXT_INVALID")
    if any(job.get(field) for field in ("attachment_ids", "attachment_details", "drive_links")):
        raise DirectError("DIRECT_JOB_ATTACHMENT_NOT_VERIFIED")
    if job.get("account_id") is not None:
        # This version cannot confirm each account-bound identity from
        # ChatGPT's authenticated /me endpoint; fail closed.
        raise DirectError("DIRECT_ACCOUNT_BOUND_UNVERIFIED")
    cid, url = job.get("target_conversation_id"), job.get("target_chatgpt_url")
    if cid is None and url:
        raise DirectError("DIRECT_TARGET_CID_MISSING")
    if cid is not None:
        if not isinstance(cid, str) or not isinstance(url, str):
            raise DirectError("DIRECT_TARGET_PAIR_MISSING")
        if cid != conversation_from_url(url):
            raise DirectError("DIRECT_TARGET_PAIR_MISMATCH")
    else:
        url = None
    return jid, rid, content, url


async def _heartbeat(socket, stop: asyncio.Event):
    while not stop.is_set():
        await asyncio.sleep(15)
        if stop.is_set():
            return
        await socket.send('{"type":"worker.heartbeat"}')


async def run(transport: DirectWeb2API, *, seconds: int = 10800) -> None:
    if os.getenv("HITEL_DIRECT_ENABLE_PRODUCTION", "") != "1":
        raise DirectError("DIRECT_PRODUCTION_NOT_ENABLED")
    if os.environ.get("GPTWEB_TRANSPORT_MODE") != "direct":
        raise DirectError("DIRECT_BROWSER_FALLBACK_MUST_BE_DISABLED")
    if os.environ.get("GPTWEB_BROWSER_RELAY_URL"):
        raise DirectError("DIRECT_BROWSER_FALLBACK_CONFIGURED")
    await asyncio.to_thread(transport.ready)
    url = os.getenv("HITEL_RELAY_WS_URL", RELAY)
    if url != RELAY:
        raise DirectError("DIRECT_RELAY_URL_NOT_PINNED")
    deadline = time.monotonic() + max(300, min(seconds, 14000))
    seen: set[str] = set()
    active: dict[str, asyncio.Task] = {}
    rooms_busy: set[str] = set()
    connected = False
    try:
        token = await asyncio.to_thread(_oidc_token)
        async with websockets.connect(url, ping_interval=20, ping_timeout=20,
                                      max_size=4*1024*1024, close_timeout=5) as socket:
            await socket.send(json.dumps({
                "role": "web2api",
                "deviceId": "web2api-main",
                "oidc_token": token,
                "hitel_protocol_version": 4,
                "max_concurrent_jobs": MAX_CONCURRENT
            }))
            response = json.loads(await asyncio.wait_for(socket.recv(), 25))
            if response.get("type") != "auth.ok":
                raise DirectError("DIRECT_RELAY_AUTH_FAILED")
            connected = True
            print("DIRECT_HTTP_SIGNED_WORKER_CONNECTED", flush=True)
            stop = asyncio.Event()
            beat = asyncio.create_task(_heartbeat(socket, stop))
            try:
                async def execute(job: dict):
                    jid, rid = job["id"], job["room_id"]
                    try:
                        await socket.send(json.dumps({"type":"job.received",
                            "job_id": jid,"room_id": rid,"stage":"direct_http_received"}))
                        _, _, prompt, target_url = _job_contract(job)
                        answer, cid = await asyncio.to_thread(transport.send, rid, prompt, target_url)
                        if cid != (conversation_from_url(target_url) if target_url else cid):
                            raise DirectError("DIRECT_RESULT_ROOM_CHANGED", after_post=True)
                        await socket.send(json.dumps({
                            "type":"job.result","job_id":jid,"room_id":rid,
                            "verified":True,"stage":"assistant_reply_stable",
                            "result_text":answer,
                            "chatgpt_url":"https://chatgpt.com/c/"+cid,
                            "room_state":"active",
                        }, ensure_ascii=False))
                        print("DIRECT_HTTP_VERIFIED_REPLY",flush=True)
                    except asyncio.CancelledError:
                        raise
                    except DirectError as exc:
                        if exc.after_post:
                            transport.quarantine(rid)
                        await socket.send(json.dumps({
                            "type":"job.uncertain" if exc.after_post else "job.error",
                            "job_id":jid,"room_id":rid,
                            "stage":"upstream_delivery_unknown" if exc.after_post else "direct_preflight_failed",
                            "reason":exc.code,
                        }))
                        print("DIRECT_HTTP_JOB_"+("UNCERTAIN" if exc.after_post else "FAILED")+
                              "_"+exc.code,flush=True)
                    except Exception:
                        # Unknown error may happen after a POST; do not send
                        # another job into this room, even after reconnect.
                        transport.quarantine(rid)
                        await socket.send(json.dumps({
                            "type":"job.uncertain","job_id":jid,"room_id":rid,
                            "stage":"upstream_delivery_unknown",
                            "reason":"DIRECT_UNCLASSIFIED_UNCERTAIN",
                        }))
                        print("DIRECT_HTTP_JOB_UNCERTAIN_UNCLASSIFIED",flush=True)
                    finally:
                        rooms_busy.discard(rid)
                        active.pop(jid, None)
                while time.monotonic() < deadline:
                    try:
                        raw = await asyncio.wait_for(socket.recv(), timeout=30)
                    except asyncio.TimeoutError:
                        # Heartbeat is sent by another task.
                        continue
                    msg = json.loads(raw)
                    typ = msg.get("type")
                    if typ == "ping":
                        await socket.send('{"type":"pong"}')
                        continue
                    if typ == "room.bootstrap":
                        ready = []
                        rooms = msg.get("rooms")
                        if not isinstance(rooms, list) or len(rooms) > MAX_CONCURRENT:
                            rooms = []
                        for entry in rooms:
                            if not isinstance(entry, dict):
                                continue
                            rid, route = entry.get("room_id"), entry.get("chatgpt_url")
                            try:
                                # Read-only HTTP! No chat question is sent here.
                                handle = await asyncio.to_thread(transport.bootstrap,rid,route)
                                ready.append({"room_id":rid,"target_id":handle})
                            except DirectError as exc:
                                print("DIRECT_HTTP_BOOTSTRAP_FAILED_"+exc.code,flush=True)
                        await socket.send(json.dumps({
                            "type":"room.bootstrap.done","ready_rooms":ready}))
                        print(f"DIRECT_HTTP_BOOTSTRAP_READONLY={len(ready)}/{len(rooms)}",flush=True)
                        continue
                    if typ != "job":
                        continue
                    job = msg.get("job")
                    if not isinstance(job, dict):
                        continue
                    try:
                        jid, rid, _, _ = _job_contract(job)
                    except DirectError:
                        continue
                    if jid in seen:
                        print("DIRECT_HTTP_DUPLICATE_JOB_REFUSED",flush=True)
                        continue
                    if len(active) >= MAX_CONCURRENT or rid in rooms_busy:
                        await socket.send(json.dumps({
                            "type":"job.error","job_id":jid,"room_id":rid,
                            "stage":"capacity_mismatch",
                            "reason":"DIRECT_HTTP_ROOM_OR_CAPACITY_BUSY"}))
                        continue
                    seen.add(jid)
                    rooms_busy.add(rid)
                    active[jid] = asyncio.create_task(execute(job),name="direct-"+rid)
            finally:
                stop.set()
                beat.cancel()
                await asyncio.gather(beat, return_exceptions=True)
    finally:
        if active:
            for task in active.values():
                task.cancel()
            await asyncio.gather(*active.values(), return_exceptions=True)
    if not connected:
        raise DirectError("DIRECT_RELAY_NEVER_CONNECTED")


if __name__ == "__main__":
    transport = DirectWeb2API(
        oauth_file=os.getenv("GPTWEB_OAUTH_TOKEN_FILE",""),
        api_key=os.getenv("GPTWEB_API_KEY",""),
        timeout=int(os.getenv("HITEL_DIRECT_REPLY_TIMEOUT","1500")),
    )
    asyncio.run(run(transport,seconds=int(os.getenv("HITEL_DIRECT_RUN_SECONDS","10800"))))
