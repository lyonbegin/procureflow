#!/usr/bin/env python3
"""One public HITEL room per checkpoint. Reconnects observe the saved request."""
from __future__ import annotations
import argparse
import asyncio
import base64
import hashlib
import json
import os
from pathlib import Path
import sys
import uuid

WS_URL = "wss://hitel-integration-api-production.up.railway.app/integrations/v1/public/stream"
PENDING = {"sending", "running", "unverified"}

def save(path, state):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)

async def exchange(ws, path, state, text=None, resume=False):
    ready = json.loads(await ws.recv())
    if ready.get("type") != "session.ready" or not ready.get("session_id"):
        raise RuntimeError("SESSION_NOT_READY")
    session_id = ready["session_id"]
    if state.get("room_id"):
        opening = {"type": "room.bind", "room_id": state["room_id"]}
    else:
        opening = {"type": "room.open", "room_name": state["room_name"]}
    await ws.send(json.dumps(opening))
    bound = json.loads(await ws.recv())
    if bound.get("type") != "room.bound" or bound.get("session_id") != session_id:
        raise RuntimeError("ROOM_BIND_FAILED")
    if state.get("room_id") and state["room_id"] != bound.get("room_id"):
        raise RuntimeError("SAVED_ROOM_CHANGED")
    room_id = bound["room_id"]
    state["room_id"] = room_id
    pending = state.get("status") in PENDING
    if resume or pending:
        if not state.get("request_id"):
            raise RuntimeError("NO_SAVED_REQUEST_TO_RESUME")
        if pending and text is not None:
            if hashlib.sha256(text.encode()).hexdigest() != state.get("text_sha256"):
                raise RuntimeError("PENDING_REQUEST_MUST_FINISH_BEFORE_NEW_QUESTION")
        packet = {"type": "job.resume", "room_id": room_id,
                  "request_id": state["request_id"], "seq": state["seq"]}
    else:
        if not text or not text.strip():
            raise RuntimeError("TEXT_REQUIRED")
        state.update(request_id="hitel-client-" + uuid.uuid4().hex,
                     seq=state.get("seq", 0) + 1,
                     text_sha256=hashlib.sha256(text.encode()).hexdigest(),
                     status="sending")
        state.pop("job_id", None)
        state.pop("answer", None)
        packet = {"type": "chat.send", "room_id": room_id, "text": text,
                  "request_id": state["request_id"], "seq": state["seq"]}
    # Persist BEFORE sending. After any uncertain disconnect, only job.resume.
    save(path, state)
    await ws.send(json.dumps(packet, ensure_ascii=False))
    accepted = json.loads(await ws.recv())
    if accepted.get("type") == "request.error":
        if packet["type"] == "chat.send":
            state["status"] = "rejected"
        state["error_code"] = accepted.get("error_code")
        save(path, state)
        raise RuntimeError("REQUEST_REJECTED_" + str(accepted.get("error_code")))
    if (accepted.get("type") != "job.accepted" or
        accepted.get("session_id") != session_id or
        accepted.get("room_id") != room_id or
        accepted.get("request_id") != state["request_id"] or
        accepted.get("seq") != state["seq"]):
        raise RuntimeError("ACCEPTANCE_SCOPE_MISMATCH")
    if packet["type"] == "job.resume" and state.get("job_id"):
        if accepted.get("job_id") != state["job_id"]:
            raise RuntimeError("RESUMED_JOB_CHANGED")
    state.update(job_id=accepted["job_id"], status="running")
    save(path, state)
    result = bytearray()
    while True:
        packet = json.loads(await ws.recv())
        if (packet.get("session_id") != session_id or
            packet.get("room_id") != room_id or
            packet.get("request_id") != state["request_id"] or
            packet.get("job_id") != state["job_id"] or
            packet.get("seq") != state["seq"]):
            raise RuntimeError("REPLY_SCOPE_MISMATCH")
        kind = packet.get("type")
        if kind == "job.progress":
            print("status=" + str(packet.get("status")), file=sys.stderr, flush=True)
        elif kind == "reply.chunk":
            if packet.get("offset") != len(result):
                raise RuntimeError("REPLY_OFFSET_MISMATCH")
            result.extend(base64.b64decode(packet["data_base64"], validate=True))
            if len(result) > 2_000_000:
                raise RuntimeError("REPLY_TOO_LARGE")
        elif kind == "reply.done":
            if (packet.get("verified") is not True or packet.get("bytes") != len(result)
                or hashlib.sha256(result).hexdigest() != packet.get("sha256")):
                raise RuntimeError("REPLY_INTEGRITY_FAILED")
            answer = result.decode("utf-8")
            state.update(status="completed", answer=answer, sha256=packet["sha256"])
            save(path, state)
            return answer
        elif kind == "reply.unverified":
            state.update(status="unverified", error_code=packet.get("error_code"))
            save(path, state)
            raise RuntimeError("REPLY_UNVERIFIED_USE_RESUME_WITHOUT_RESENDING")
        else:
            raise RuntimeError("UNEXPECTED_REPLY_TYPE")

async def run(args):
    try:
        import websockets
    except ImportError:
        raise RuntimeError("Install dependency: python -m pip install websockets==13.1")
    path = Path(args.state)
    state = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    if args.room and state.get("room_name") not in (None, args.room):
        raise RuntimeError("CHECKPOINT_BELONGS_TO_ANOTHER_ROOM")
    if not state.get("room_name"):
        if not args.room:
            raise RuntimeError("ROOM_REQUIRED_FOR_NEW_CHECKPOINT")
        state["room_name"] = args.room
    async with websockets.connect(WS_URL, open_timeout=30, ping_interval=20,
                                  ping_timeout=20, max_size=4*1024*1024) as ws:
        return await exchange(ws, path, state, args.text, args.resume)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--room", help="Existing public room name; reuse the same name.")
    parser.add_argument("--state", required=True, help="Use a separate checkpoint file for each room.")
    parser.add_argument("--text", help="One new question. A pending request is never resubmitted.")
    parser.add_argument("--resume", action="store_true", help="Observe the saved request, without a new question.")
    args = parser.parse_args()
    if args.resume and args.text:
        parser.error("--resume does not accept --text")
    try:
        print(asyncio.run(run(args)))
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        print("Saved requests remain in the checkpoint. Use --state <same file> --resume.", file=sys.stderr)
        return 1
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
