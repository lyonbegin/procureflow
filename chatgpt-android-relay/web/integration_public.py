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

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

import api_v1
import worker_autostart

router=APIRouter(prefix="/integrations/v1/public",tags=["HITEL public named rooms"])
USER_ID="usr_browser_hitel_public_link"
DEFAULT_ROOM_NAME="기본 대화방"
REQUEST_ID=re.compile(r"^[A-Za-z0-9_.:-]{16,128}$")
JOB_ID=re.compile(r"^job_[a-f0-9]{32}$")
ROOM_ID=re.compile(r"^room_[a-f0-9]{32}$")
LOCK=threading.RLock()
MAX_TEXT=24000
SERVICE_ID=re.compile(r"^[A-Za-z0-9_.-]{2,64}$")

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
    # Opt-in service namespaces. Existing clients remain in the legacy global
    # namespace with their room IDs and history fully unchanged.
    db.execute("""CREATE TABLE IF NOT EXISTS hitel_public_service_names (
       service_id TEXT NOT NULL,
       name_key TEXT NOT NULL,
       name TEXT NOT NULL,
       room_id TEXT NOT NULL,
       created_at INTEGER NOT NULL,
       updated_at INTEGER NOT NULL,
       PRIMARY KEY(service_id,name_key)
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS hitel_public_room_services (
       room_id TEXT PRIMARY KEY,
       service_id TEXT NOT NULL
    )""")
    db.execute("""CREATE INDEX IF NOT EXISTS idx_hitel_public_room_service
                  ON hitel_public_room_services(service_id)""")


class PublicRoom(BaseModel):
    name: str = Field(min_length=1,max_length=160)
    create_new: bool = False
    service_id: str | None = Field(default=None,min_length=2,max_length=64,pattern=r"^[A-Za-z0-9_.-]{2,64}$")


class PublicChat(BaseModel):
    text: str = Field(min_length=1,max_length=MAX_TEXT)
    request_id: str | None = Field(default=None,min_length=16,max_length=128)
    room_id: str | None = Field(default=None,min_length=37,max_length=37)
    room_name: str | None = Field(default=None,min_length=1,max_length=160)
    service_id: str | None = Field(default=None,min_length=2,max_length=64,pattern=r"^[A-Za-z0-9_.-]{2,64}$")


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


def _service_for_room(db, room_id: str) -> str | None:
    row=db.execute("""SELECT service_id FROM hitel_public_room_services
                      WHERE room_id=?""",(room_id,)).fetchone()
    return row["service_id"] if row else None


def _open_named_room(db,name: str, *, create_new:bool=False,
                     service_id:str | None=None) -> tuple[dict,bool]:
    name,key=_name(name)
    if service_id is None:
        mapped=db.execute("""SELECT room_id FROM hitel_public_named_rooms
                           WHERE name_key=?""",(key,)).fetchone()
    else:
        if not SERVICE_ID.fullmatch(service_id):
            raise HTTPException(422,"Invalid service_id")
        mapped=db.execute("""SELECT room_id FROM hitel_public_service_names
                            WHERE service_id=? AND name_key=?""",
                          (service_id,key)).fetchone()
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
    if service_id is None:
        db.execute("""INSERT INTO hitel_public_named_rooms
                     (name_key,name,room_id,created_at,updated_at)
                     VALUES(?,?,?,?,?)
                     ON CONFLICT(name_key) DO UPDATE SET
                      name=excluded.name,room_id=excluded.room_id,
                      updated_at=excluded.updated_at""",
                   (key,name,rid,now,now))
    else:
        db.execute("""INSERT INTO hitel_public_service_names
                     (service_id,name_key,name,room_id,created_at,updated_at)
                     VALUES(?,?,?,?,?,?)
                     ON CONFLICT(service_id,name_key) DO UPDATE SET
                      name=excluded.name,room_id=excluded.room_id,
                      updated_at=excluded.updated_at""",
                   (service_id,key,name,rid,now,now))
        db.execute("""INSERT INTO hitel_public_room_services
                     (room_id,service_id) VALUES(?,?)""",(rid,service_id))
    room=db.execute("SELECT * FROM rooms WHERE id=?",(rid,)).fetchone()
    return dict(room),True


def _room_by_id(db,room_id:str, room_name: str | None=None,
                service_id:str | None=None) -> dict:
    if not ROOM_ID.fullmatch(room_id):
        raise HTTPException(422,"Invalid room_id")
    room=db.execute("""SELECT * FROM rooms WHERE id=? AND user_id=?
                       AND status='active'""",(room_id,USER_ID)).fetchone()
    if not room:
        raise HTTPException(404,"Public room not found")
    # Explicitly selected old room IDs continue to work even when the
    # same name was later recreated. A scoped program must match its ID.
    actual_service=_service_for_room(db,room_id)
    if service_id is not None and actual_service!=service_id:
        raise HTTPException(409,"room_id belongs to a different service")
    if room_name is not None and _name(room_name)[1]!=_name(room["title"])[1]:
        raise HTTPException(409,"room_id and room_name select different rooms")
    return dict(room)


def _room_result(room:dict, created:bool, service_id:str | None=None) -> dict:
    return {"room_id":room["id"],"room_name":room["title"],
            "service_id":service_id,
            "created":created,
            "conversation_linked":bool(room["chatgpt_url"]),
            "status":"active"}


@router.get("/status")
def public_status():
    from app import web2api_device
    return {
        "public_link_enabled":True,
        "login_required":False,
        "hitel_api_key_required":False,
        "github_action_manual_start_required":False,
        "new_conversation_per_question":False,
        "same_room_name_reuses_conversation":True,
        "explicit_new_room_supported":True,
        "default_room_name":DEFAULT_ROOM_NAME,
        "service_id_supported":True,
        "worker_connected":web2api_device is not None,
        "worker_autostart_configured":worker_autostart.configured(),
        "supported":"text_only",
    }


@router.get("/rooms")
def list_public_rooms():
    with api_v1.connection() as db:
        rows=db.execute("""SELECT r.id,r.title,r.chatgpt_url,
                      s.service_id
              FROM rooms r LEFT JOIN hitel_public_room_services s ON s.room_id=r.id
              WHERE r.user_id=? AND r.status='active'
                AND (EXISTS(SELECT 1 FROM hitel_public_named_rooms n WHERE n.room_id=r.id)
                 OR EXISTS(SELECT 1 FROM hitel_public_service_names sn WHERE sn.room_id=r.id))
              ORDER BY r.updated_at DESC LIMIT 250""",(USER_ID,)).fetchall()
    return {"rooms":[{"room_name":row["title"],"room_id":row["id"],
                      "service_id":row["service_id"],
                      "conversation_linked":bool(row["chatgpt_url"])}
                     for row in rows],"default_room_name":DEFAULT_ROOM_NAME}


@router.post("/rooms")
def open_public_room(payload:PublicRoom):
    with LOCK:
        with api_v1.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            room,created=_open_named_room(
                db,payload.name,create_new=payload.create_new,
                service_id=payload.service_id)
    return JSONResponse(_room_result(room,created,payload.service_id),
                        status_code=201 if created else 200)


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
                    r.title AS room_name,
                    (SELECT service_id FROM hitel_public_room_services s
                     WHERE s.room_id=j.room_id) AS service_id
                    FROM hitel_public_link_requests p
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
                if payload.service_id is not None and payload.service_id!=previous["service_id"]:
                    raise HTTPException(409,"request_id belongs to a different service")
                room_name=previous["room_name"]
                job_id=previous["job_id"]
                replay=True
            else:
                if payload.room_id is not None:
                    room=_room_by_id(db,payload.room_id,payload.room_name,
                                     payload.service_id)
                else:
                    room,_=_open_named_room(db,payload.room_name or DEFAULT_ROOM_NAME,
                                           service_id=payload.service_id)
                room_id=room["id"]
                room_name=room["title"]
                if db.execute("""SELECT 1 FROM jobs WHERE user_id=? AND room_id=?
                    AND status IN ('queued','running') LIMIT 1""",
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
        "service_id":payload.service_id,
        "status":"queued" if not replay else "existing",
        "sent_to_chatgpt":False,
        "worker_connected":web2api_device is not None,
        "result_url":"/integrations/v1/public/jobs/"+job_id,
    }


@router.get("/jobs/{job_id}")
def read_public_result(job_id:str):
    if not JOB_ID.fullmatch(job_id):
        raise HTTPException(404,"Unknown public job")
    with api_v1.connection() as db:
        row=db.execute("""SELECT j.id,j.room_id,r.title AS room_name,
                      (SELECT service_id FROM hitel_public_room_services s
                       WHERE s.room_id=j.room_id) AS service_id,
                      j.status,
                      j.stage,j.result_text,j.error,j.created_at,j.updated_at
                 FROM jobs j
                 JOIN rooms r ON r.id=j.room_id AND r.user_id=j.user_id
                 JOIN hitel_public_link_requests p ON p.job_id=j.id
                 WHERE j.id=? AND j.user_id=? AND j.account_id IS NULL""",
                 (job_id,USER_ID)).fetchone()
    if row is None:
        raise HTTPException(404,"Unknown public job")
    return {
        "job_id":row["id"],"room_id":row["room_id"],
        "room_name":row["room_name"],"service_id":row["service_id"],"status":row["status"],
        "stage":row["stage"],
        "result_text":row["result_text"] if row["status"]=="completed" else None,
        "error":row["error"] if row["status"]=="failed" else None,
        "created_at":row["created_at"],"updated_at":row["updated_at"],
    }
