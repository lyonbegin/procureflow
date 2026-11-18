"""Public, no-login HITEL ChatGPT text experiment.

This is deliberately separate from /integrations/v1/rooms and the owner's
key-bound resources. Every POST makes a fresh isolated conversation; it cannot
list, join or modify any existing/private ChatGPT conversation. Anyone who
knows this HTTPS URL can send text using the saved Chrome account.
"""
from __future__ import annotations

import hashlib
import json
import re
import threading

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

import api_v1
import worker_autostart

router=APIRouter(prefix="/integrations/v1/public",tags=["HITEL open link test"])
USER_ID="usr_browser_hitel_public_link"
REQUEST_ID=re.compile(r"^[A-Za-z0-9_.:-]{16,128}$")
JOB_ID=re.compile(r"^job_[a-f0-9]{32}$")
LOCK=threading.RLock()
MAX_TEXT=24000

with api_v1.connection() as db:
    db.execute("""CREATE TABLE IF NOT EXISTS hitel_public_link_requests (
      request_id TEXT PRIMARY KEY,
      fingerprint TEXT NOT NULL,
      job_id TEXT NOT NULL,
      created_at INTEGER NOT NULL
    )""")


class PublicChat(BaseModel):
    text: str = Field(min_length=1,max_length=MAX_TEXT)
    request_id: str | None = Field(default=None,min_length=16,max_length=128)


@router.get("/status")
def public_status():
    from app import web2api_device
    return {
        "public_link_enabled":True,
        "login_required":False,
        "hitel_api_key_required":False,
        "github_action_manual_start_required":False,
        "new_conversation_per_question":True,
        "worker_connected":web2api_device is not None,
        "worker_autostart_configured":worker_autostart.configured(),
        "supported":"text_only",
    }


@router.post("/chat",status_code=202)
async def submit_public_chat(payload:PublicChat):
    from app import web2api_device
    text=payload.text.strip()
    if not text or any(ord(x)<32 and x not in "\n\r\t" for x in text):
        raise HTTPException(422,"Provide non-empty text without control characters")
    if web2api_device is None and not worker_autostart.configured():
        raise HTTPException(503,"ChatGPT Chrome worker and automatic launch unavailable")
    if payload.request_id and not REQUEST_ID.fullmatch(payload.request_id):
        raise HTTPException(422,"request_id must be 16-128 safe characters")
    fingerprint=hashlib.sha256(text.encode("utf-8")).hexdigest()
    request_id=payload.request_id or "req_"+api_v1.new_id()
    replay=False
    with LOCK:
        with api_v1.connection() as db:
            row=db.execute("""SELECT fingerprint,job_id
                FROM hitel_public_link_requests WHERE request_id=?""",
                (request_id,)).fetchone()
            if row:
                if row["fingerprint"]!=fingerprint:
                    raise HTTPException(409,"request_id reused with different text")
                job_id=row["job_id"]
                replay=True
            else:
                now=api_v1.clock()
                db.execute("""INSERT OR IGNORE INTO users
                   (id,name,api_key_hash,created_at) VALUES(?,?,?,?)""",
                   (USER_ID,"Public link separate new conversations",
                    "disabled-public-link-no-owner-key",now))
                room_id="room_"+api_v1.new_id()
                db.execute("""INSERT INTO rooms
                  (id,user_id,title,android_state,created_at,updated_at)
                  VALUES(?,?,?,?,?,?)""",
                  (room_id,USER_ID,"Public link question","uncreated",now,now))
                job_id=api_v1.store_job(db,USER_ID,room_id,
                                        "chat.send",text,[],account_id=None)
                db.execute("""INSERT INTO messages
                  (id,user_id,room_id,job_id,role,text,created_at)
                  VALUES(?,?,?,?,?,?,?)""",
                  ("msg_"+api_v1.new_id(),USER_ID,room_id,job_id,
                   "user",text,now))
                db.execute("""INSERT INTO hitel_public_link_requests
                  (request_id,fingerprint,job_id,created_at)
                  VALUES(?,?,?,?)""",
                  (request_id,fingerprint,job_id,now))
    if not replay and api_v1.on_new_job:
        await api_v1.on_new_job()
    from app import web2api_device
    return {
        "accepted":True,
        "replayed":replay,
        "request_id":request_id,
        "job_id":job_id,
        "status":"queued" if not replay else "existing",
        "sent_to_chatgpt":False,
        "worker_connected":web2api_device is not None,
        "result_url":"/integrations/v1/public/jobs/"+job_id,
    }


@router.get("/jobs/{job_id}")
def read_public_result(job_id:str):
    if not JOB_ID.fullmatch(job_id):
        raise HTTPException(404,"Unknown public job")
    # Never permit lookup of private jobs, including jobs created using
    # a signed HITEL integration key or a different public test suite.
    with api_v1.connection() as db:
        row=db.execute("""SELECT j.id,j.status,j.stage,j.result_text,j.error,
                      j.created_at,j.updated_at
                 FROM jobs j JOIN hitel_public_link_requests p ON p.job_id=j.id
                 WHERE j.id=? AND j.user_id=? AND j.account_id IS NULL""",
                 (job_id,USER_ID)).fetchone()
    if row is None:
        raise HTTPException(404,"Unknown public job")
    return {
        "job_id":row["id"],
        "status":row["status"],
        "stage":row["stage"],
        "result_text":row["result_text"] if row["status"]=="completed" else None,
        "error":row["error"] if row["status"]=="failed" else None,
        "created_at":row["created_at"],
        "updated_at":row["updated_at"],
    }
