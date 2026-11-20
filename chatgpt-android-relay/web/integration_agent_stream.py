"""HITEL public test agents: persistent WebSocket <-> Railway <-> Web2API.

One connected agent is bound to one public test room for its lifetime.
Uses the EXISTING Railway room/job database and signed Web2API worker socket:
no new logins, no OAuth, no GitHub secrets, no new services, no account access.
Do not expose private API rooms through this public no-login endpoint.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import re
import time
import uuid
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

import api_v1
import integration_public as existing
import long_job_events

router=APIRouter(prefix="/integrations/v1/public", tags=["HITEL persistent public test agents"])
ID_RE=re.compile(r"^[A-Za-z0-9_.:-]{16,128}$")
MAX_WS_INBOUND=27000
MAX_WS_RESULT_BYTES=2_000_000
MAX_WS_SIMULTANEOUS_PER_AGENT=1
POLL_SECONDS=1.0
END_STATES={"completed","failed","unknown","stalled"}
MAX_OBSERVE_SECONDS=15000
MAX_WS_IDLE_SECONDS=15000


def _job_scope(job: dict[str,Any], *, room_id:str, request_id:str, job_id:str) -> None:
    """Never deliver another agent's reply to this socket, even if bus is shared."""
    if (job.get("room_id")!=room_id or job.get("request_id")!=request_id
            or job.get("job_id")!=job_id):
        raise ValueError("REPLY_ROOM_REQUEST_JOB_MISMATCH")


def _open_public_room_once(name:str) -> dict:
    # Reuse the existing public-name table and lookup logic, never private rooms.
    with existing.LOCK:
        with api_v1.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            room,created=existing._open_named_room(db,name,create_new=False)
    return existing._room_result(room,created)


def _confirmed_public_room(rid:str) -> dict:
    if not isinstance(rid,str) or not existing.ROOM_ID.fullmatch(rid):
        raise ValueError("ROOM_ID_INVALID")
    with api_v1.connection() as db:
        row=db.execute("""SELECT r.id,r.title,r.chatgpt_url
          FROM hitel_public_named_rooms n
          JOIN rooms r ON r.id=n.room_id AND r.user_id=? AND r.status='active'
          WHERE r.id=? LIMIT 1""",(existing.USER_ID,rid)).fetchone()
    if row is None:
        raise ValueError("NOT_A_PUBLIC_TEST_ROOM")
    return {"room_id":row["id"],"room_name":row["title"],
            "conversation_linked":bool(row["chatgpt_url"])}


async def _confirmed_result_chunks(send, job:dict, room_id:str, request_id:str, job_id:str,
                                    agent_session:str, sequence:int) -> None:
    """Verify each streamed chunk and the final SHA before reporting success."""
    _job_scope(job,room_id=room_id,request_id=request_id,job_id=job_id)
    total=job.get("result_length_bytes")
    checksum=job.get("result_sha256")
    if (not isinstance(total,int) or not 0<total<=MAX_WS_RESULT_BYTES
            or not isinstance(checksum,str) or
            re.fullmatch("[a-f0-9]{64}",checksum) is None):
        raise ValueError("REPLY_LENGTH_OR_DIGEST_MISSING")
    collected=hashlib.sha256()
    offset=0
    while offset<total:
        part=await asyncio.to_thread(existing.read_public_result_bytes,job_id,offset,65536)
        if (part.get("job_id")!=job_id or part.get("room_id")!=room_id
                or part.get("request_id")!=request_id
                or part.get("result_sha256")!=checksum):
            raise ValueError("REPLY_CHUNK_SCOPE_MISMATCH")
        try:
            data=base64.b64decode(part["content_base64"],validate=True)
        except Exception:
            raise ValueError("REPLY_CHUNK_CORRUPT") from None
        count=len(data)
        if not count or offset+count>total or count!=part.get("bytes_returned"):
            raise ValueError("REPLY_CHUNK_OFFSET_MISMATCH")
        collected.update(data)
        await send({"type":"reply.chunk","session_id":agent_session,
                    "room_id":room_id,"job_id":job_id,"request_id":request_id,
                    "seq":sequence,"offset":offset,"data_base64":part["content_base64"]})
        offset+=count
    if collected.hexdigest()!=checksum:
        raise ValueError("REPLY_SHA256_MISMATCH")
    await send({"type":"reply.done","session_id":agent_session,
                "room_id":room_id,"job_id":job_id,"request_id":request_id,
                "seq":sequence,"sha256":checksum,"bytes":total,"verified":True})


async def _follow_existing_job(send, *, room_id:str, request_id:str, job_id:str,
                               session_id:str, seq:int) -> None:
    """Observe Railway's *existing* job; NEVER submit or retry a ChatGPT turn."""
    started=time.monotonic()
    prior=None
    try:
        while time.monotonic()-started < MAX_OBSERVE_SECONDS:
            job=await asyncio.to_thread(existing.read_public_result,job_id)
            _job_scope(job,room_id=room_id,request_id=request_id,job_id=job_id)
            stage=(job.get("status"),job.get("stage"),job.get("error_code"))
            if stage!=prior:
                await send({"type":"job.progress","session_id":session_id,
                            "room_id":room_id,"request_id":request_id,"job_id":job_id,
                            "seq":seq,"status":stage[0],"stage":stage[1],
                            "error_code":stage[2]})
                prior=stage
            if job.get("status")=="completed":
                if job.get("assistant_reply_observed") is not True or job.get("result_ready") is not True:
                    raise ValueError("COMPLETED_WITHOUT_VERIFIED_ASSISTANT_REPLY")
                await _confirmed_result_chunks(send,job,room_id,request_id,job_id,session_id,seq)
                return
            if job.get("status") in END_STATES:
                await send({"type":"reply.unverified","session_id":session_id,
                            "room_id":room_id,"request_id":request_id,"job_id":job_id,
                            "seq":seq,"status":job["status"],
                            "error_code":job.get("error_code"),
                            "never_auto_retry":True})
                return
            await asyncio.sleep(POLL_SECONDS)
        await send({"type":"reply.unverified","session_id":session_id,
                    "room_id":room_id,"request_id":request_id,"job_id":job_id,
                    "seq":seq,"status":"timeout","error_code":"RESULT_NOT_OBSERVED",
                    "never_auto_retry":True})
    except asyncio.CancelledError:
        # Losing an agent socket must NOT cancel a remote ChatGPT turn.
        raise
    except Exception as exc:
        await send({"type":"reply.unverified","session_id":session_id,
                    "room_id":room_id,"request_id":request_id,"job_id":job_id,
                    "seq":seq,"status":"unknown","error_code":type(exc).__name__,
                    "never_auto_retry":True})


@router.websocket("/stream")
async def agent_stream(ws: WebSocket):
    """One durable agent->room socket; two sockets work independently."""
    await ws.accept()
    session_id="hws_"+uuid.uuid4().hex
    send_lock=asyncio.Lock()
    bound_room=None
    seq_seen=0
    active_task=None
    active_job=None

    async def send(packet):
        async with send_lock:
            await ws.send_json(packet)

    try:
        await send({"type":"session.ready","session_id":session_id,
                    "transport":"persistent_websocket",
                    "scope":"public_test_rooms_only"})
        while True:
            # An agent can send keepalives while an independent background
            # task receives Web2API completion on the SAME socket.
            try:
                raw=await asyncio.wait_for(ws.receive_text(),timeout=MAX_WS_IDLE_SECONDS)
            except asyncio.TimeoutError:
                await send({"type":"session.timeout","session_id":session_id})
                break
            if len(raw)>MAX_WS_INBOUND:
                await send({"type":"request.error","error_code":"MESSAGE_TOO_LARGE"})
                continue
            try:
                item=json.loads(raw)
            except (TypeError,ValueError):
                await send({"type":"request.error","error_code":"INVALID_JSON"})
                continue
            if not isinstance(item,dict):
                await send({"type":"request.error","error_code":"MESSAGE_MUST_BE_OBJECT"})
                continue
            typ=item.get("type")
            if typ=="ping":
                await send({"type":"pong","session_id":session_id})
                continue
            if typ=="room.open":
                if bound_room:
                    await send({"type":"request.error","error_code":"SESSION_ROOM_REBIND_FORBIDDEN"})
                    continue
                try:
                    name=item.get("room_name")
                    if not isinstance(name,str):
                        raise ValueError("ROOM_NAME_MISSING")
                    room=await asyncio.to_thread(_open_public_room_once,name)
                    bound_room=room["room_id"]
                    await send({"type":"room.bound","session_id":session_id,**room})
                except Exception as exc:
                    await send({"type":"request.error","error_code":type(exc).__name__})
                continue
            if typ=="room.bind":
                if bound_room:
                    await send({"type":"request.error","error_code":"SESSION_ROOM_REBIND_FORBIDDEN"})
                    continue
                try:
                    room=await asyncio.to_thread(_confirmed_public_room,item.get("room_id"))
                    bound_room=room["room_id"]
                    await send({"type":"room.bound","session_id":session_id,**room})
                except Exception as exc:
                    await send({"type":"request.error","error_code":type(exc).__name__})
                continue
            if typ not in ("chat.send","job.resume"):
                await send({"type":"request.error","error_code":"UNSUPPORTED_MESSAGE_TYPE"})
                continue
            if bound_room is None or item.get("room_id")!=bound_room:
                await send({"type":"request.error","error_code":"AGENT_NOT_BOUND_TO_MESSAGE_ROOM"})
                continue
            request_id=item.get("request_id")
            seq=item.get("seq")
            if (not isinstance(request_id,str) or not ID_RE.fullmatch(request_id)
                    or not isinstance(seq,int) or isinstance(seq,bool)
                    or not 1<=seq<=1000000000 or seq<=seq_seen):
                await send({"type":"request.error","error_code":"REQUEST_ID_OR_SEQUENCE_INVALID"})
                continue
            if active_task is not None and not active_task.done():
                await send({"type":"request.error","error_code":"ROOM_JOB_BUSY",
                            "pending_job_id":active_job})
                continue
            if typ=="chat.send":
                text=item.get("text")
                if not isinstance(text,str) or not text.strip() or len(text)>existing.MAX_TEXT:
                    await send({"type":"request.error","error_code":"PROMPT_INVALID"})
                    continue
                # Existing POST handler's DB transaction enforces idempotency,
                # one unfinished request/room, and explicit fixed room routing.
                try:
                    accepted=await existing.submit_public_chat(
                        existing.PublicChat(text=text,request_id=request_id,room_id=bound_room))
                    job_id=accepted["job_id"]
                    if accepted["room_id"]!=bound_room or accepted["request_id"]!=request_id:
                        raise ValueError("SERVER_ACCEPTANCE_ROUTE_MISMATCH")
                except Exception as exc:
                    await send({"type":"request.error","error_code":type(exc).__name__,
                                "request_id":request_id,"seq":seq})
                    continue
            else:
                # Reconnect/resume is READ ONLY. Never resubmit a question.
                try:
                    old=await asyncio.to_thread(existing.lookup_existing_request,request_id)
                    if old["room_id"]!=bound_room:
                        raise ValueError("RESUME_CROSS_ROOM_FORBIDDEN")
                    job_id=old["job_id"]
                except Exception as exc:
                    await send({"type":"request.error","error_code":type(exc).__name__,
                                "request_id":request_id,"seq":seq})
                    continue
            seq_seen=seq
            active_job=job_id
            await send({"type":"job.accepted","session_id":session_id,"room_id":bound_room,
                        "request_id":request_id,"job_id":job_id,"seq":seq,
                        "replayed":typ=="job.resume"})
            active_task=asyncio.create_task(
                _follow_existing_job(send,room_id=bound_room,request_id=request_id,
                                     job_id=job_id,session_id=session_id,seq=seq))
    except (WebSocketDisconnect,RuntimeError):
        pass
    finally:
        if active_task is not None and not active_task.done():
            active_task.cancel()
            await asyncio.gather(active_task,return_exceptions=True)
