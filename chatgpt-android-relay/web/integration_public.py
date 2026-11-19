"""Public no-login HITEL text bridge with durable named conversation rooms.

POST /rooms opens a known name or creates a new named room.
POST /chat routes by room_id or room_name; an omitted room selects the
persistent default room for backwards-compatible callers.
Only an explicit create_new=True replaces a named room mapping.
A verified ChatGPT conversation URL is persisted on the room by api_v1;
the existing Web2API worker then navigates to that exact conversation_id
for every later turn in that room.

All rooms here are public shared test rooms, not the owner's private
integration rooms. Never accept arbitrary external ChatGPT URLs.
"""
from __future__ import annotations

import hashlib
import json
import re
import threading
import time

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

import api_v1
import worker_autostart
import long_job_events

router=APIRouter(prefix="/integrations/v1/public",tags=["HITEL public named rooms"])
USER_ID="usr_browser_hitel_public_link"
DEFAULT_ROOM_NAME="기본 대화방"
REQUEST_ID=re.compile(r"^[A-Za-z0-9_.:-]{16,128}$")
JOB_ID=re.compile(r"^job_[a-f0-9]{32}$")
ROOM_ID=re.compile(r"^room_[a-f0-9]{32}$")
LOCK=threading.RLock()
MAX_TEXT=24000

with api_v1.connection() as db:
    db.execute("""CREATE TABLE IF NOT EXISTS hitel_public_link_requests (
      request_id TEXT PRIMARY KEY,
      fingerprint TEXT NOT NULL,
      job_id TEXT NOT NULL,
      created_at INTEGER NOT NULL
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS hitel_public_named_rooms (
      name_key TEXT PRIMARY KEY,
      name TEXT NOT NULL,
      room_id TEXT NOT NULL,
      created_at INTEGER NOT NULL,
      updated_at INTEGER NOT NULL
    )""")
    db.execute("""CREATE INDEX IF NOT EXISTS idx_hitel_public_named_room_id
                  ON hitel_public_named_rooms(room_id)""")


long_job_events.initialize()


class PublicRoom(BaseModel):
    name: str = Field(min_length=1,max_length=160)
    create_new: bool = False


class PublicChat(BaseModel):
    text: str = Field(min_length=1,max_length=MAX_TEXT)
    request_id: str | None = Field(default=None,min_length=16,max_length=128)
    room_id: str | None = Field(default=None,min_length=37,max_length=37)
    room_name: str | None = Field(default=None,min_length=1,max_length=160)


def _name(value: str) -> tuple[str,str]:
    name=" ".join(value.split())
    if not name or len(name)>160 or any(ord(ch)<32 for ch in name):
        raise HTTPException(422,"room name must contain 1-160 printable characters")
    return name,name.casefold()


def _ensure_public_user(db) -> None:
    db.execute("""INSERT OR IGNORE INTO users
       (id,name,api_key_hash,created_at) VALUES(?,?,?,?)""",
       (USER_ID,"Public shared named ChatGPT rooms",
        "disabled-public-link-no-owner-key",api_v1.clock()))


def _open_named_room(db,name: str, *, create_new:bool=False) -> tuple[dict,bool]:
    name,key=_name(name)
    mapped=db.execute("""SELECT room_id FROM hitel_public_named_rooms
                       WHERE name_key=?""",(key,)).fetchone()
    if mapped and not create_new:
        room=db.execute("""SELECT * FROM rooms WHERE id=? AND user_id=?
                           AND status='active'""",
                        (mapped["room_id"],USER_ID)).fetchone()
        if room:
            return dict(room),False
    _ensure_public_user(db)
    now=api_v1.clock()
    rid="room_"+api_v1.new_id()
    db.execute("""INSERT INTO rooms
                 (id,user_id,title,android_state,created_at,updated_at)
                 VALUES(?,?,?,?,?,?)""",
               (rid,USER_ID,name,"uncreated",now,now))
    db.execute("""INSERT INTO hitel_public_named_rooms
                 (name_key,name,room_id,created_at,updated_at)
                 VALUES(?,?,?,?,?)
                 ON CONFLICT(name_key) DO UPDATE SET
                  name=excluded.name,room_id=excluded.room_id,
                  updated_at=excluded.updated_at""",
               (key,name,rid,now,now))
    room=db.execute("SELECT * FROM rooms WHERE id=?",(rid,)).fetchone()
    return dict(room),True


def _room_by_id(db,room_id:str, room_name: str | None=None) -> dict:
    if not ROOM_ID.fullmatch(room_id):
        raise HTTPException(422,"Invalid room_id")
    room=db.execute("""SELECT * FROM rooms WHERE id=? AND user_id=?
                       AND status='active'""",(room_id,USER_ID)).fetchone()
    if not room:
        raise HTTPException(404,"Public room not found")
    # An explicitly replaced room stays accessible by its original room_id;
    # only name lookup switches to the most recently created room.
    if room_name is not None and _name(room_name)[1]!=_name(room["title"])[1]:
        raise HTTPException(409,"room_id and room_name select different rooms")
    return dict(room)


def _room_result(room:dict, created:bool) -> dict:
    return {"room_id":room["id"],"room_name":room["title"],
            "created":created,
            "conversation_linked":bool(room["chatgpt_url"]),
            "status":"active"}


@router.get("/status")
def public_status():
    # A connected socket does not prove the sole worker is available:
    # it may be processing a long ChatGPT turn in another room.
    # Expose health and capacity only, never private room/job IDs or text.
    from app import (web2api_device, web2api_last_seen_monotonic,
                     web2api_active_jobs, WEB2API_MAX_ACTIVE)
    connected = web2api_device is not None
    heartbeat_age = (max(0, int(time.monotonic() - web2api_last_seen_monotonic))
                     if connected and web2api_last_seen_monotonic > 0 else None)
    heartbeat_recent = bool(heartbeat_age is not None and heartbeat_age <= 75)
    busy = len(web2api_active_jobs) >= WEB2API_MAX_ACTIVE
    return {
        "public_link_enabled":True,
        "login_required":False,
        "hitel_api_key_required":False,
        "github_action_manual_start_required":False,
        "new_conversation_per_question":False,
        "same_room_name_reuses_conversation":True,
        "explicit_new_room_supported":True,
        "default_room_name":DEFAULT_ROOM_NAME,
        "worker_connected":connected,
        "worker_heartbeat_recent":heartbeat_recent,
        "worker_heartbeat_age_seconds":heartbeat_age,
        "worker_busy":bool(web2api_active_jobs),
        "worker_active_jobs_count":len(web2api_active_jobs),
        "worker_capacity":WEB2API_MAX_ACTIVE,
        "worker_available_for_new_job":heartbeat_recent and not busy,
        "worker_autostart_configured":worker_autostart.configured(),
        "supported":"text_only",
    }


@router.get("/rooms")
def list_public_rooms():
    with api_v1.connection() as db:
        rows=db.execute("""SELECT n.name,n.room_id,r.chatgpt_url
            FROM hitel_public_named_rooms n
            JOIN rooms r ON r.id=n.room_id AND r.user_id=? AND r.status='active'
            ORDER BY n.updated_at DESC LIMIT 100""",(USER_ID,)).fetchall()
    return {"rooms":[{"room_name":row["name"],"room_id":row["room_id"],
                      "conversation_linked":bool(row["chatgpt_url"])}
                     for row in rows],"default_room_name":DEFAULT_ROOM_NAME}


@router.post("/rooms")
def open_public_room(payload:PublicRoom):
    with LOCK:
        with api_v1.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            room,created=_open_named_room(
                db,payload.name,create_new=payload.create_new)
    return JSONResponse(_room_result(room,created),status_code=201 if created else 200)


@router.post("/chat",status_code=202)
async def submit_public_chat(payload:PublicChat):
    from app import web2api_device
    text=payload.text.strip()
    if not text or any(ord(x)<32 and x not in "\n\r\t" for x in text):
        raise HTTPException(422,"Provide non-empty text without control characters")
    if web2api_device is None and not worker_autostart.configured():
        raise HTTPException(503,"ChatGPT worker and auto launch unavailable")
    if payload.request_id and not REQUEST_ID.fullmatch(payload.request_id):
        raise HTTPException(422,"request_id must be 16-128 safe characters")
    request_id=payload.request_id or "req_"+api_v1.new_id()
    replay=False
    with LOCK:
        with api_v1.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            previous=db.execute("""SELECT p.fingerprint,p.job_id,j.room_id,
                    r.title AS room_name FROM hitel_public_link_requests p
                    JOIN jobs j ON j.id=p.job_id
                    JOIN rooms r ON r.id=j.room_id
                    WHERE p.request_id=? AND j.user_id=?""",
                    (request_id,USER_ID)).fetchone()
            if previous:
                room_id=previous["room_id"]
                current_hash=hashlib.sha256(json.dumps(
                    {"room_id":room_id,"text":text},
                    ensure_ascii=False,sort_keys=True,separators=(",",":")
                ).encode("utf-8")).hexdigest()
                old_text_hash=hashlib.sha256(text.encode("utf-8")).hexdigest()
                if previous["fingerprint"] not in (current_hash,old_text_hash):
                    raise HTTPException(409,"request_id reused for a different request")
                if payload.room_id and payload.room_id!=room_id:
                    raise HTTPException(409,"request_id belongs to a different room")
                if payload.room_name and _name(payload.room_name)[1]!=_name(previous["room_name"])[1]:
                    raise HTTPException(409,"request_id belongs to a different room")
                room_name=previous["room_name"]
                job_id=previous["job_id"]
                replay=True
            else:
                if payload.room_id is not None:
                    room=_room_by_id(db,payload.room_id,payload.room_name)
                else:
                    room,_=_open_named_room(db,payload.room_name or DEFAULT_ROOM_NAME)
                room_id=room["id"]
                room_name=room["title"]
                if db.execute("""SELECT 1 FROM jobs WHERE user_id=? AND room_id=?
                    AND status IN ('queued','running','unknown','stalled') LIMIT 1""",
                    (USER_ID,room_id)).fetchone():
                    raise HTTPException(409,"Previous question in this room is unfinished; poll first")
                if not room["chatgpt_url"] and db.execute("""SELECT 1 FROM jobs
                    WHERE user_id=? AND room_id=? AND status IN ('completed','failed')
                    LIMIT 1""",(USER_ID,room_id)).fetchone():
                    raise HTTPException(409,
                        "Room has no verified ChatGPT conversation after prior work; "
                        "explicitly create a new room before sending")
                job_id=api_v1.store_job(db,USER_ID,room_id,"chat.send",
                                        text,[],account_id=None)
                now=api_v1.clock()
                db.execute("""INSERT INTO messages
                    (id,user_id,room_id,job_id,role,text,created_at)
                    VALUES(?,?,?,?,?,?,?)""",
                    ("msg_"+api_v1.new_id(),USER_ID,room_id,job_id,"user",text,now))
                digest=hashlib.sha256(json.dumps(
                    {"room_id":room_id,"text":text},
                    ensure_ascii=False,sort_keys=True,separators=(",",":")
                ).encode("utf-8")).hexdigest()
                db.execute("""INSERT INTO hitel_public_link_requests
                    (request_id,fingerprint,job_id,created_at)
                    VALUES(?,?,?,?)""",(request_id,digest,job_id,now))
    if not replay and api_v1.on_new_job:
        await api_v1.on_new_job()
    from app import web2api_device
    return {
        "accepted":True,"replayed":replay,
        "request_id":request_id,"job_id":job_id,"room_id":room_id,
        "room_name":room_name,
        "status":"queued" if not replay else "existing",
        "sent_to_chatgpt":False,
        "worker_connected":web2api_device is not None,
        "result_url":"/integrations/v1/public/jobs/"+job_id,
    }


@router.get("/requests/{request_id}")
def lookup_existing_request(request_id:str):
    """Read-only lookup after a lost POST response; NEVER resubmits a prompt."""
    if not REQUEST_ID.fullmatch(request_id):
        raise HTTPException(404,"Unknown public request")
    with api_v1.connection() as db:
        row=db.execute("""SELECT p.request_id,p.job_id,j.room_id,j.status
            FROM hitel_public_link_requests p
            JOIN jobs j ON j.id=p.job_id
            WHERE p.request_id=? AND j.user_id=? AND j.account_id IS NULL""",
            (request_id,USER_ID)).fetchone()
    if row is None:
        raise HTTPException(404,"Unknown public request")
    return {"request_id":row["request_id"],"job_id":row["job_id"],
            "room_id":row["room_id"],
            "status":row["status"],
            "result_url":"/integrations/v1/public/jobs/"+row["job_id"]}


@router.get("/jobs/{job_id}/result")
def read_public_result_bytes(job_id:str, offset:int=0, limit:int=65536):
    """Return immutable UTF-8 byte chunks as Base64, never re-query ChatGPT."""
    if not JOB_ID.fullmatch(job_id):
        raise HTTPException(404,"Unknown public job")
    row=long_job_events.job_row(job_id)
    if row is None:
        raise HTTPException(404,"Unknown public job")
    if row["status"]!="completed" or row["result_text"] is None:
        raise HTTPException(409,"Final assistant reply not yet verified")
    try:
        chunk=long_job_events.result_slice(row["result_text"],offset,limit)
    except ValueError as exc:
        raise HTTPException(416,str(exc)) from exc
    return {"job_id":job_id,"request_id":row["request_id"],"room_id":row["room_id"],
            "content_encoding":"base64","byte_encoding":"utf-8",**chunk}


@router.get("/jobs/{job_id}")
def read_public_result(job_id:str):
    """Read-only, observation-based state; GET never triggers a ChatGPT turn."""
    if not JOB_ID.fullmatch(job_id):
        raise HTTPException(404,"Unknown public job")
    row=long_job_events.job_row(job_id)
    if row is None:
        raise HTTPException(404,"Unknown public job")
    from app import (web2api_device, web2api_last_seen_monotonic,web2api_active_jobs)
    connected=web2api_device is not None
    heartbeat_age=(time.monotonic()-web2api_last_seen_monotonic
                   if connected and web2api_last_seen_monotonic>0 else None)
    heartbeat_recent=bool(heartbeat_age is not None and heartbeat_age<=75)
    original_status=row["status"]
    stage=row["stage"]
    if stage=="server_restarted":
        status="unknown"
        error_code="SERVER_RESTARTED_DELIVERY_UNKNOWN"
    elif stage=="connection_lost":
        status="stalled"
        error_code="WORKER_CONNECTION_LOST"
    elif original_status=="running" and (not heartbeat_recent or job_id not in web2api_active_jobs):
        status="stalled"
        error_code="WORKER_NOT_ACTIVE_FOR_JOB"
    elif original_status in ("queued","running","completed","failed","stalled","unknown"):
        status=original_status
        error_code=None
    else:
        status="unknown"
        error_code="UNRECOGNIZED_STORED_STATUS"
    if row["error_code"]:
        error_code=row["error_code"]
    if status=="failed" and not error_code:
        error_code="WORKER_REPORTED_FAILURE"
    result_ready=status=="completed" and row["result_text"] is not None
    meta=long_job_events.result_metadata(row["result_text"]) if result_ready else {
        "result_length_bytes":None,"result_sha256":None,
        "result_json_valid":None,"result_json_complete":None,
        "result_chunk_count":None}
    send_confirmed=(bool(row["chatgpt_send_confirmed"])
                    if row["chatgpt_send_confirmed"] is not None else
                    True if result_ready and stage=="assistant_reply_stable" else None)
    reply_observed=(bool(row["assistant_reply_observed"])
                    if row["assistant_reply_observed"] is not None else
                    True if result_ready else None)
    return {
        "job_id":job_id,"request_id":row["request_id"],
        "room_id":row["room_id"],"room_name":row["room_name"],
        "status":status,
        "stage":("completed" if result_ready else
                 row["event_stage"] if status=="running" and row["event_stage"]
                 else stage),
        "worker_connected":connected,
        "worker_heartbeat_at":row["worker_heartbeat_at"],
        "job_last_progress_at":row["job_last_progress_at"],
        "chatgpt_send_confirmed":send_confirmed,
        "assistant_reply_observed":reply_observed,
        "result_ready":result_ready,
        "result_url":"/integrations/v1/public/jobs/"+job_id+"/result" if result_ready else None,
        "created_at":row["created_at"],"updated_at":row["updated_at"],
        "error_code":error_code,
        "error_stage":(row["error_stage"] or stage) if error_code else None,
        "error":row["error"] if original_status=="failed" else None,
        "result_text":row["result_text"] if result_ready and meta["result_length_bytes"]<=65536 else None,
        **meta,
    }
