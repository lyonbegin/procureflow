"""Authenticated machine-to-machine HITEL ChatGPT integration API.

Browser verification is only used for initial identity ownership and one-time
key issuance. Integrators use scoped Bearer tokens (never ChatGPT cookies).
All sends enqueue immutable, account-pinned jobs for the existing GitHub Chrome
worker. A queue acknowledgment must never be represented as a ChatGPT answer.

This API does NOT claim native file attachment or generated file export.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import threading
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

import api_v1
import web_chat

router = APIRouter(prefix="/integrations/v1", tags=["HITEL programmatic integration"])
browser_router = APIRouter(prefix="/web/api/integrations",
                           tags=["HITEL integration-key management"])
LOCK = threading.RLock()
IDEMPOTENCY = re.compile(r"^[A-Za-z0-9_.:-]{16,128}$")
ROOM_ID = re.compile(r"^room_[a-f0-9]{32}$")
KEY_ID = re.compile(r"^ikey_[a-f0-9]{24}$")
ACCOUNT_ID = re.compile(r"^oai_[A-Za-z0-9_-]{3,75}$")
MAX_KEYS_PER_PROFILE = 5
MAX_TEXT = 2000
MAX_PER_HOUR = 5
MAX_PER_DAY = 30

with api_v1.connection() as _db:
    _db.executescript("""
    CREATE TABLE IF NOT EXISTS hitel_integration_keys(
        id TEXT PRIMARY KEY,
        owner_hash TEXT NOT NULL,
        user_id TEXT NOT NULL,
        account_id TEXT NOT NULL,
        name TEXT NOT NULL,
        token_sha256 TEXT NOT NULL UNIQUE,
        created_at INTEGER NOT NULL,
        revoked_at INTEGER
    );
    CREATE INDEX IF NOT EXISTS idx_hitel_integration_keys_user
      ON hitel_integration_keys(user_id,revoked_at);
    CREATE TABLE IF NOT EXISTS hitel_integration_requests(
        key_id TEXT NOT NULL,
        idempotency_key TEXT NOT NULL,
        request_sha256 TEXT NOT NULL,
        job_id TEXT NOT NULL,
        created_at INTEGER NOT NULL,
        PRIMARY KEY(key_id,idempotency_key)
    );
    """)


class KeyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)


class RoomCreate(BaseModel):
    title: str = Field(min_length=1, max_length=160)


class ChatCreate(BaseModel):
    room_id: str = Field(min_length=37, max_length=37)
    account_id: str = Field(min_length=7, max_length=80)
    text: str = Field(min_length=1, max_length=MAX_TEXT)
    attachment_ids: list[str] = Field(default_factory=list, max_length=10)


def _selected_identity(db, owner_hash: str):
    return db.execute("""
        SELECT id FROM hitel_verified_chatgpt_accounts
        WHERE browser_owner=? AND active=1
          AND issuer='https://auth.openai.com'
          AND email IS NOT NULL AND email!=''
        LIMIT 1
    """, (owner_hash,)).fetchone()


def _browser_actor(request: Request, mutate: bool = False):
    raw = web_chat._owner(request, mutate)
    owner = web_chat._owner_hash(raw)
    uid = web_chat._actor(request, mutate)
    with api_v1.connection() as db:
        profile = db.execute("""
            SELECT 1 FROM web_trial_profiles
            WHERE owner_hash=? AND user_id=? AND is_active=1 LIMIT 1
        """, (owner, uid)).fetchone()
    if not profile:
        raise HTTPException(403, "Active browser profile not found")
    return owner, uid


def _api_actor(authorization: Annotated[str | None, Header()] = None):
    if (not authorization or not authorization.startswith("Bearer ")
            or len(authorization) > 200):
        raise HTTPException(401, "Supply Authorization: Bearer <HITEL integration key>")
    token = authorization[7:]
    if not token.startswith("htli_") or len(token) < 30:
        raise HTTPException(403, "Invalid integration key")
    digest = hashlib.sha256(token.encode()).hexdigest()
    with api_v1.connection() as db:
        k = db.execute("""
            SELECT id,owner_hash,user_id,account_id FROM hitel_integration_keys
            WHERE token_sha256=? AND revoked_at IS NULL
        """, (digest,)).fetchone()
        if not k:
            raise HTTPException(403, "Invalid or revoked integration key")
        row = db.execute("""
            SELECT 1 FROM web_trial_profiles p
            JOIN hitel_verified_chatgpt_accounts a
              ON a.browser_owner=p.owner_hash
            WHERE p.owner_hash=? AND p.user_id=? AND p.is_active=1
              AND a.id=? AND a.active=1
              AND a.issuer='https://auth.openai.com'
              AND a.email IS NOT NULL AND a.email!=''
        """, (k["owner_hash"],k["user_id"],k["account_id"])).fetchone()
        if not row:
            raise HTTPException(409, "Selected ChatGPT identity is no longer verified")
    return dict(k)


@browser_router.post("/keys")
def create_integration_key(data: KeyCreate, request: Request):
    """One-time key reveal, protected by existing same-origin browser CSRF."""
    owner, uid = _browser_actor(request, mutate=True)
    with LOCK:
        with api_v1.connection() as db:
            account = _selected_identity(db, owner)
            if account is None:
                raise HTTPException(409, "Select and verify a real ChatGPT account first")
            count = db.execute("""
                SELECT COUNT(*) FROM hitel_integration_keys
                WHERE owner_hash=? AND user_id=? AND revoked_at IS NULL
            """, (owner,uid)).fetchone()[0]
            if count >= MAX_KEYS_PER_PROFILE:
                raise HTTPException(429, "Maximum 5 active integration keys per profile")
            token = "htli_" + secrets.token_urlsafe(36)
            kid = "ikey_" + secrets.token_hex(12)
            db.execute("""
                INSERT INTO hitel_integration_keys
                  (id,owner_hash,user_id,account_id,name,token_sha256,created_at)
                VALUES(?,?,?,?,?,?,?)
            """, (kid,owner,uid,account["id"],data.name.strip(),
                  hashlib.sha256(token.encode()).hexdigest(),api_v1.clock()))
    return JSONResponse({"id":kid,"name":data.name.strip(),
                         "account_id":account["id"],
                         "api_key":token,
                         "warning":"Secret is shown once. Store outside source control."},
                        headers={"Cache-Control":"no-store"})


@browser_router.get("/keys")
def list_integration_keys(request: Request):
    owner,uid = _browser_actor(request)
    with api_v1.connection() as db:
        rows = db.execute("""
            SELECT id,name,account_id,created_at,revoked_at
            FROM hitel_integration_keys WHERE owner_hash=? AND user_id=?
            ORDER BY created_at DESC
        """, (owner,uid)).fetchall()
    return {"keys":[dict(row) for row in rows]}


@browser_router.delete("/keys/{key_id}")
def revoke_integration_key(key_id: str, request: Request):
    owner,uid = _browser_actor(request,mutate=True)
    if not KEY_ID.fullmatch(key_id):
        raise HTTPException(404,"Integration key not found")
    with api_v1.connection() as db:
        cursor = db.execute("""
            UPDATE hitel_integration_keys SET revoked_at=?
            WHERE id=? AND owner_hash=? AND user_id=? AND revoked_at IS NULL
        """, (api_v1.clock(),key_id,owner,uid))
    if cursor.rowcount != 1:
        raise HTTPException(404, "Active integration key not found")
    return {"revoked":True,"id":key_id}


@router.get("/capabilities")
def capabilities():
    from app import web2api_device
    return {
        "service":"hitel-chatgpt-relay",
        "api_version":"1",
        "worker_connected":web2api_device is not None,
        "async_job_api":True,
        "text_chat":{"supported":True,"availability":"requires_verified_account_and_connected_worker"},
        "new_room":{"supported":True},
        "followup_in_same_room":{"supported":True},
        "txt_csv_file_ui_verified_in_actions":{"supported":True,
            "scope":"internal GitHub Chrome UI synthetic tests only"},
        "remote_binary_file_attachment":{"supported":False,
            "reason":"Worker original-byte transport to ChatGPT not implemented"},
        "generated_file_download":{"supported":False,
            "reason":"Native generated-file resource and retrieval unverified"},
        "streaming":{"supported":False,
            "reason":"Integration endpoint is async job polling, not SSE"},
    }


@router.get("/rooms")
def list_rooms(key=Depends(_api_actor)):
    with api_v1.connection() as db:
        rooms = db.execute("""
            SELECT id,title,chatgpt_url,created_at,updated_at
            FROM rooms WHERE user_id=? AND chatgpt_account_id=?
                AND status='active' ORDER BY updated_at DESC LIMIT 100
        """, (key["user_id"],key["account_id"])).fetchall()
    return {"rooms":[dict(row) for row in rooms]}


@router.post("/rooms", status_code=201)
def create_room(data: RoomCreate, key=Depends(_api_actor)):
    now=api_v1.clock()
    with LOCK:
        with api_v1.connection() as db:
            count=db.execute("""
                SELECT COUNT(*) FROM rooms WHERE user_id=? AND status!='deleted'
            """,(key["user_id"],)).fetchone()[0]
            if count>=web_chat.MAX_ROOMS:
                raise HTTPException(429,"Room limit reached")
            rid="room_"+api_v1.new_id()
            db.execute("""
                INSERT INTO rooms
                 (id,user_id,title,android_state,created_at,updated_at,chatgpt_account_id)
                 VALUES(?,?,?,?,?,?,?)
            """,(rid,key["user_id"],data.title.strip(),"uncreated",now,now,
                  key["account_id"]))
    return {"room_id":rid,"title":data.title.strip(),
            "account_id":key["account_id"],"status":"active"}


@router.post("/chat", status_code=202)
async def submit_chat(data: ChatCreate, request: Request,
                      idempotency_key: Annotated[str | None,Header(alias="Idempotency-Key")]=None,
                      key=Depends(_api_actor)):
    """Queue exactly one text turn per idempotency key and pinned account."""
    if not idempotency_key or not IDEMPOTENCY.fullmatch(idempotency_key):
        raise HTTPException(400,"Idempotency-Key must be 16-128 safe characters")
    if not ROOM_ID.fullmatch(data.room_id):
        raise HTTPException(422,"Invalid room_id")
    if not ACCOUNT_ID.fullmatch(data.account_id) or data.account_id != key["account_id"]:
        raise HTTPException(409,"Requested ChatGPT account differs from integration key")
    if data.attachment_ids:
        raise HTTPException(501,"Native file attachment to ChatGPT is not supported")
    message=data.text.strip()
    if not message or any(ord(x)<32 and x not in "\n\r\t" for x in message):
        raise HTTPException(422,"Non-empty text without control characters required")
    fingerprint=hashlib.sha256(json.dumps({
        "room_id":data.room_id,"account_id":data.account_id,"text":message
    },sort_keys=True,ensure_ascii=False,separators=(",",":")).encode()).hexdigest()
    queued=None
    now=api_v1.clock()
    replay=False
    with LOCK:
        with api_v1.connection() as db:
            previous=db.execute("""
                SELECT request_sha256,job_id FROM hitel_integration_requests
                WHERE key_id=? AND idempotency_key=?
            """,(key["id"],idempotency_key)).fetchone()
            if previous:
                if previous["request_sha256"]!=fingerprint:
                    raise HTTPException(409,"Idempotency-Key already used for different request")
                queued=previous["job_id"]
                replay=True
            else:
                room=api_v1.existing_room(db,data.room_id,key["user_id"])
                if room["status"]!="active" or room["chatgpt_account_id"]!=key["account_id"]:
                    raise HTTPException(409,"Room and selected ChatGPT account do not match")
                if db.execute("""
                    SELECT 1 FROM jobs WHERE room_id=? AND user_id=?
                      AND status IN ('queued','running') LIMIT 1
                """,(data.room_id,key["user_id"])).fetchone():
                    raise HTTPException(409,"Room has an unfinished job; poll it before another send")
                if not room["chatgpt_url"] and db.execute("""
                    SELECT 1 FROM jobs WHERE room_id=? AND user_id=?
                      AND status='completed' LIMIT 1
                """,(data.room_id,key["user_id"])).fetchone():
                    raise HTTPException(409,"Unverified previous conversation: use a fresh room")
                hourly=db.execute("""
                    SELECT COUNT(*) FROM jobs WHERE user_id=? AND action='chat.send'
                      AND created_at>?
                """,(key["user_id"], now-3600000)).fetchone()[0]
                if hourly>=MAX_PER_HOUR:
                    raise HTTPException(429,"Hourly integration quota exceeded")
                daily=db.execute("""
                    SELECT COUNT(*) FROM jobs WHERE user_id LIKE 'usr_browser_%'
                      AND action='chat.send' AND created_at>?
                """,(now-86400000,)).fetchone()[0]
                if daily>=MAX_PER_DAY:
                    raise HTTPException(429,"Global integration quota exceeded")
                queued=api_v1.store_job(db,key["user_id"],data.room_id,
                                        "chat.send",message,[],account_id=key["account_id"])
                db.execute("""
                    INSERT INTO messages VALUES(?,?,?,?,?,?,?)
                """,("msg_"+api_v1.new_id(),key["user_id"],data.room_id,
                      queued,"user",message,now))
                db.execute("""
                    INSERT INTO hitel_integration_requests VALUES(?,?,?,?,?)
                """,(key["id"],idempotency_key,fingerprint,queued,now))
                db.execute("UPDATE rooms SET updated_at=? WHERE id=? AND user_id=?",
                           (now,data.room_id,key["user_id"]))
    if not replay and api_v1.on_new_job:
        await api_v1.on_new_job()
    from app import web2api_device
    return {"job_id":queued,"status":"queued" if not replay else "existing",
            "replayed":replay,"accepted":True,
            "sent_to_chatgpt":False,"worker_connected":web2api_device is not None,
            "poll":"/integrations/v1/jobs/"+queued}


@router.get("/jobs/{job_id}")
def job_status(job_id: str,key=Depends(_api_actor)):
    if not re.fullmatch(r"^job_[a-f0-9]{32}$",job_id):
        raise HTTPException(404,"Job not found")
    with api_v1.connection() as db:
        row=db.execute("""
            SELECT id,room_id,account_id,status,stage,error,result_text,created_at,updated_at
            FROM jobs WHERE id=? AND user_id=? AND account_id=?
        """,(job_id,key["user_id"],key["account_id"])).fetchone()
    if not row:
        raise HTTPException(404,"Job not found")
    return {"job_id":row["id"],"room_id":row["room_id"],
            "status":row["status"],"stage":row["stage"],
            "result_text":row["result_text"] if row["status"]=="completed" else None,
            "error":row["error"] if row["status"]=="failed" else None,
            "created_at":row["created_at"],"updated_at":row["updated_at"]}


@router.post("/files")
def unsupported_file_upload(key=Depends(_api_actor)):
    raise HTTPException(501,"Remote file upload to ChatGPT is not implemented or verified")
