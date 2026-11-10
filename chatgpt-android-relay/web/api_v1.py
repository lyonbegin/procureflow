"""Persistent multi-user room, job and file API for the ChatGPT Android test bench.

Only one Android device works jobs; clients are isolated by their API keys.
The web tester may use CONSOLE_TOKEN as an admin credential; this is NOT
a production-user authentication solution, and must not be public.
"""
import base64
import hashlib
import hmac
import json
import mimetypes
import os
import re
import secrets
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, UploadFile, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

BASE = Path(os.environ.get("RELAY_DATA_DIR", str(Path(__file__).resolve().parent / ".localdata")))
BASE.mkdir(parents=True, exist_ok=True)
FILES = BASE / "files"
FILES.mkdir(parents=True, exist_ok=True)
DB = BASE / "relay.sqlite3"
MAX_FILE = 15 * 1024 * 1024
FILE_TYPES = {".txt", ".md", ".pdf", ".doc", ".docx", ".ppt", ".pptx",
              ".csv", ".json", ".xls", ".xlsx", ".png", ".jpeg", ".jpg",
              ".webp", ".gif"}
router = APIRouter(prefix="/api/v1", tags=["relay-api-v1"])
on_new_job = None

def clock():
    return int(time.time() * 1000)

def new_id():
    return uuid.uuid4().hex

@contextmanager
def connection():
    c = sqlite3.connect(DB, timeout=15)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA busy_timeout=15000")
    c.execute("PRAGMA foreign_keys=ON")
    try:
        yield c
        c.commit()
    except BaseException:
        c.rollback()
        raise
    finally:
        c.close()

def init_db():
    with connection() as c:
        c.execute("PRAGMA journal_mode=WAL")
        c.executescript("""
        CREATE TABLE IF NOT EXISTS users(
            id TEXT PRIMARY KEY, name TEXT NOT NULL, api_key_hash TEXT NOT NULL UNIQUE,
            created_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS rooms(
            id TEXT PRIMARY KEY, user_id TEXT NOT NULL, title TEXT NOT NULL,
            android_state TEXT NOT NULL DEFAULT 'uncreated',
            android_title TEXT, status TEXT NOT NULL DEFAULT 'active',
            created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_room_user ON rooms(user_id, created_at DESC);
        CREATE TABLE IF NOT EXISTS jobs(
            id TEXT PRIMARY KEY, user_id TEXT NOT NULL, room_id TEXT NOT NULL,
            action TEXT NOT NULL, text TEXT NOT NULL DEFAULT '',
            attachment_ids TEXT NOT NULL DEFAULT '[]', status TEXT NOT NULL,
            stage TEXT NOT NULL DEFAULT 'queued', result_text TEXT,
            error TEXT, created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_job_status ON jobs(status, created_at);
        CREATE TABLE IF NOT EXISTS messages(
            id TEXT PRIMARY KEY, user_id TEXT NOT NULL, room_id TEXT NOT NULL,
            job_id TEXT, role TEXT NOT NULL, text TEXT NOT NULL,
            created_at INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_messages_room ON messages(room_id, created_at);
        CREATE TABLE IF NOT EXISTS file_objects(
            id TEXT PRIMARY KEY, user_id TEXT NOT NULL, room_id TEXT,
            job_id TEXT, kind TEXT NOT NULL, name TEXT NOT NULL,
            mime TEXT NOT NULL, size INTEGER NOT NULL, sha256 TEXT NOT NULL,
            relative_path TEXT NOT NULL, created_at INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_file_room ON file_objects(room_id, created_at);
        """)

init_db()

def challenge(token, expected):
    return bool(token and expected) and hmac.compare_digest(token, expected)

# Browser sessions are signed server-side, never published into the HTML.
# A session grants the SAME scoped rights as the originally validated API key.
SESSION_COOKIE = "relay_web_session"
SESSION_LIFETIME = 7 * 24 * 3600

def _session_key():
    value = os.environ.get("WEB_SESSION_SIGNING_KEY", "")
    return value.encode("utf-8") if len(value) >= 32 else None

def issue_browser_session(actor):
    key = _session_key()
    if not key:
        raise HTTPException(503, "WEB_SESSION_SIGNING_KEY is not configured")
    data = {
        "v": 1, "admin": bool(actor["admin"]), "uid": actor["user_id"],
        "exp": int(time.time()) + SESSION_LIFETIME,
    }
    if data["admin"]:
        # Existing admin sessions are revoked when CONSOLE_TOKEN is rotated.
        data["admin_fp"] = hashlib.sha256(
            os.environ.get("CONSOLE_TOKEN", "").encode()).hexdigest()
    encoded = base64.urlsafe_b64encode(
        json.dumps(data, separators=(",", ":"), sort_keys=True).encode()
    ).rstrip(b"=").decode()
    signature = hmac.new(key, encoded.encode(), hashlib.sha256).hexdigest()
    return encoded + "." + signature

def validate_browser_session(cookie):
    key = _session_key()
    if not key or not cookie or len(cookie) > 1024 or "." not in cookie:
        return None
    try:
        encoded, signature = cookie.split(".", 1)
        expected = hmac.new(key, encoded.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            return None
        padded = encoded + "=" * (-len(encoded) % 4)
        data = json.loads(base64.urlsafe_b64decode(padded).decode())
        if data.get("v") != 1 or type(data.get("exp")) is not int:
            return None
        now = int(time.time())
        if not now < data["exp"] <= now + SESSION_LIFETIME:
            return None
        if data.get("admin") is True and data.get("uid") is None:
            current_fp = hashlib.sha256(
                os.environ.get("CONSOLE_TOKEN", "").encode()).hexdigest()
            if not challenge(data.get("admin_fp"), current_fp):
                return None
            return {"admin": True, "user_id": None}
        uid = data.get("uid")
        if data.get("admin") is False and isinstance(uid, str) and re.fullmatch(
                r"[a-zA-Z0-9_\-]{1,64}", uid):
            with connection() as c:
                if c.execute("SELECT 1 FROM users WHERE id=?", (uid,)).fetchone():
                    return {"admin": False, "user_id": uid}
    except (ValueError, TypeError, UnicodeError, KeyError):
        pass
    return None

def authentication(request: Request,
                   x_console_token: str | None = Header(default=None),
                   x_api_key: str | None = Header(default=None),
                   authorization: str | None = Header(default=None)):
    admin = os.environ.get("CONSOLE_TOKEN", "")
    if challenge(x_console_token, admin):
        return {"admin": True, "user_id": None}
    token = x_api_key
    if not token and authorization and authorization.startswith("Bearer "):
        token = authorization[7:]
    if token:
        digest = hashlib.sha256(token.encode()).hexdigest()
        with connection() as c:
            user = c.execute("SELECT id FROM users WHERE api_key_hash = ?", (digest,)).fetchone()
        if not user:
            raise HTTPException(403, "Invalid user API key")
        return {"admin": False, "user_id": user["id"]}
    if x_console_token:
        # Explicitly bad admin credentials must not silently fall back.
        raise HTTPException(403, "Invalid admin token")
    actor = validate_browser_session(request.cookies.get(SESSION_COOKIE))
    if actor is not None:
        return actor
    raise HTTPException(401, "Missing API key or expired browser session")

def user_scope(user_id: str | None, actor: dict):
    if actor["admin"]:
        if not user_id or not re.fullmatch(r"[a-zA-Z0-9_\-]{1,64}", user_id):
            raise HTTPException(400, "Admin requests require a valid user_id")
        return user_id
    if user_id and user_id != actor["user_id"]:
        raise HTTPException(403, "Cannot access another user's resources")
    return actor["user_id"]

def existing_room(c, room_id, user_id, include_deleted=False):
    item = c.execute("SELECT * FROM rooms WHERE id=? AND user_id=?", (room_id, user_id)).fetchone()
    if not item or (item["status"] == "deleted" and not include_deleted):
        raise HTTPException(404, "Room not found for user")
    return item

def public_job(r):
    d = dict(r)
    d["attachment_ids"] = json.loads(d["attachment_ids"])
    return d

def public_file(r):
    d = dict(r)
    d.pop("relative_path", None)
    return d

class UserCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    user_id: str | None = None

class RoomCreate(BaseModel):
    user_id: str | None = None
    title: str = Field(min_length=1, max_length=160)

class RoomUpdate(BaseModel):
    user_id: str | None = None
    title: str = Field(min_length=1, max_length=160)

class MessageCreate(BaseModel):
    user_id: str | None = None
    text: str = Field(default="", max_length=24000)
    attachment_ids: list[str] = Field(default_factory=list, max_length=10)

@router.get("/auth/check")
def check_authentication(actor=Depends(authentication)):
    """Validate a supplied console/user credential without disclosing it."""
    return {"authenticated": True, "role": "admin" if actor["admin"] else "user",
            "user_id": actor["user_id"]}


@router.post("/auth/session")
def create_browser_session(response: Response, actor=Depends(authentication)):
    """After first successful key entry, keep the browser signed in.

    Cookie is HttpOnly, Secure, SameSite=Strict and limited to API routes.
    The raw admin token is never returned to or embedded in the web page.
    """
    session = issue_browser_session(actor)
    response.set_cookie(
        key=SESSION_COOKIE, value=session, max_age=SESSION_LIFETIME,
        secure=True, httponly=True, samesite="strict", path="/api/v1",
    )
    return {"authenticated": True, "role": "admin" if actor["admin"] else "user",
            "user_id": actor["user_id"], "session_seconds": SESSION_LIFETIME}

@router.post("/auth/logout")
def logout_browser_session(response: Response):
    response.delete_cookie(key=SESSION_COOKIE, path="/api/v1",
                           secure=True, httponly=True, samesite="strict")
    return {"signed_out": True}


@router.post("/users")
def create_user(data: UserCreate, actor=Depends(authentication)):
    if not actor["admin"]:
        raise HTTPException(403, "Admin only")
    uid = data.user_id or ("usr_" + new_id()[:12])
    if not re.fullmatch(r"[a-zA-Z0-9_\-]{1,64}", uid):
        raise HTTPException(400, "Invalid user_id")
    token = "rlyu_" + secrets.token_urlsafe(32)
    with connection() as c:
        if c.execute("SELECT id FROM users WHERE id=?", (uid,)).fetchone():
            raise HTTPException(409, "User already exists")
        c.execute("INSERT INTO users VALUES(?,?,?,?)", (uid, data.name, hashlib.sha256(token.encode()).hexdigest(), clock()))
    return {"user_id": uid, "name": data.name, "api_key": token, "notice": "API key is shown only once"}

@router.get("/users")
def list_users(actor=Depends(authentication)):
    if not actor["admin"]:
        raise HTTPException(403, "Admin only")
    with connection() as c:
        rows = c.execute("SELECT id, name, created_at FROM users ORDER BY created_at DESC").fetchall()
    return {"users": [dict(r) for r in rows]}

@router.post("/rooms")
def create_room(data: RoomCreate, actor=Depends(authentication)):
    uid = user_scope(data.user_id, actor)
    now = clock()
    rid = "room_" + new_id()
    with connection() as c:
        if not actor["admin"] and not c.execute("SELECT id FROM users WHERE id=?", (uid,)).fetchone():
            raise HTTPException(404, "User missing")
        c.execute("INSERT INTO rooms(id,user_id,title,created_at,updated_at) VALUES(?,?,?,?,?)",
                  (rid, uid, data.title, now, now))
        row = c.execute("SELECT * FROM rooms WHERE id=?", (rid,)).fetchone()
    # An OAuth-connected user gets a Google Drive folder per chat room.
    # Folder creation can be retried from /drive/rooms/{room_id}/folder.
    try:
        import drive_v1
        if drive_v1.has_connection(uid):
            drive_v1.ensure_room_folder(uid, rid)
            with connection() as c:
                row = c.execute("SELECT * FROM rooms WHERE id=?", (rid,)).fetchone()
    except HTTPException as exc:
        print(f"[drive] folder pending for room={rid}: HTTP {exc.status_code}",flush=True)
    return dict(row)

@router.get("/rooms")
def list_rooms(user_id: str | None = None, include_deleted: bool = False, actor=Depends(authentication)):
    uid = user_scope(user_id, actor)
    with connection() as c:
        sql = "SELECT * FROM rooms WHERE user_id=?"
        if not include_deleted:
            sql += " AND status!='deleted'"
        rows = c.execute(sql + " ORDER BY created_at DESC", (uid,)).fetchall()
    return {"rooms": [dict(r) for r in rows]}

@router.get("/rooms/{room_id}")
def get_room(room_id: str, user_id: str | None = None, actor=Depends(authentication)):
    uid = user_scope(user_id, actor)
    with connection() as c:
        row = existing_room(c, room_id, uid)
        return dict(row)

@router.patch("/rooms/{room_id}")
def rename_room(room_id: str, data: RoomUpdate, actor=Depends(authentication)):
    uid = user_scope(data.user_id, actor)
    with connection() as c:
        existing_room(c, room_id, uid)
        c.execute("UPDATE rooms SET title=?,updated_at=? WHERE id=?", (data.title, clock(), room_id))
        return dict(c.execute("SELECT * FROM rooms WHERE id=?", (room_id,)).fetchone())

def store_job(c, uid, rid, action, text="", attachment_ids=None):
    jid = "job_" + new_id()
    now = clock()
    c.execute("INSERT INTO jobs(id,user_id,room_id,action,text,attachment_ids,status,stage,created_at,updated_at) VALUES(?,?,?,?,?,?, 'queued','queued',?,?)",
              (jid,uid,rid,action,text,json.dumps(attachment_ids or []),now,now))
    return jid

@router.delete("/rooms/{room_id}")
async def delete_room(room_id: str, user_id: str | None = None, actor=Depends(authentication)):
    uid = user_scope(user_id, actor)
    with connection() as c:
        room = existing_room(c, room_id, uid)
        if room["status"] == "delete_pending":
            raise HTTPException(409, "Room deletion already pending")
        c.execute("UPDATE rooms SET status='delete_pending',updated_at=? WHERE id=?", (clock(),room_id))
        jid = store_job(c, uid, room_id, "room.delete")
    if on_new_job:
        await on_new_job()
    return {"room_id": room_id, "status": "delete_pending", "job_id": jid,
            "notice": "Deletion is only confirmed after Android verifies removal"}

@router.get("/rooms/{room_id}/messages")
def list_messages(room_id: str, user_id: str | None = None, actor=Depends(authentication)):
    uid = user_scope(user_id, actor)
    with connection() as c:
        existing_room(c, room_id, uid, True)
        rows = c.execute("SELECT * FROM messages WHERE room_id=? AND user_id=? ORDER BY created_at,id",
                         (room_id, uid)).fetchall()
    return {"messages": [dict(r) for r in rows]}

@router.post("/rooms/{room_id}/open")
async def open_existing_chat_room(
    room_id: str,
    user_id: str | None = None,
    actor=Depends(authentication),
):
    """Queue Android navigation to an EXISTING ChatGPT conversation.

    A successful result requires Android to find and verify a distinct
    completed message from this room; the action sends no text/files.
    """
    uid = user_scope(user_id, actor)
    with connection() as c:
        room = existing_room(c, room_id, uid)
        if room["status"] != "active":
            raise HTTPException(409, "Room is not active")
        if room["android_state"] != "active":
            raise HTTPException(409, "ChatGPT conversation has not been created yet")
        jid = store_job(c, uid, room_id, "room.open")
        job = c.execute("SELECT * FROM jobs WHERE id=?", (jid,)).fetchone()
    if on_new_job:
        await on_new_job()
    return public_job(job)


@router.post("/rooms/{room_id}/messages")
async def create_message(room_id: str, data: MessageCreate, actor=Depends(authentication)):
    uid = user_scope(data.user_id, actor)
    if not data.text.strip() and not data.attachment_ids:
        raise HTTPException(422, "Supply text or at least one attachment")
    if len(set(data.attachment_ids)) != len(data.attachment_ids):
        raise HTTPException(422, "Duplicate attachment IDs")
    with connection() as c:
        room = existing_room(c, room_id, uid)
        if room["status"] != "active":
            raise HTTPException(409, "Room is not active")
        for fid in data.attachment_ids:
            f = c.execute("""SELECT id,kind,drive_url,drive_shared
                             FROM file_objects WHERE id=? AND user_id=? AND room_id=?""",
                          (fid,uid,room_id)).fetchone()
            if not f:
                raise HTTPException(422, "File does not belong to this user/room: " + fid)
            if f["kind"] not in ("input", "drive"):
                raise HTTPException(409, "Output files cannot be attached to ChatGPT")
            if f["kind"] == "drive" and (not f["drive_url"] or not f["drive_shared"]):
                raise HTTPException(409, "Drive link is private; only an explicit shared link can be sent")
        jid = store_job(c, uid, room_id, "chat.send", data.text, data.attachment_ids)
        c.execute("INSERT INTO messages VALUES(?,?,?,?,?,?,?)",
                  ("msg_"+new_id(), uid, room_id, jid, "user", data.text, clock()))
        job = c.execute("SELECT * FROM jobs WHERE id=?", (jid,)).fetchone()
    if on_new_job:
        await on_new_job()
    return public_job(job)

@router.post("/rooms/{room_id}/turns")
async def submit_turn_with_files(
    room_id: str,
    user_id: str | None = Form(default=None),
    text: str = Form(default=""),
    files: list[UploadFile] = File(default=[]),
    actor=Depends(authentication)
):
    """One multipart API call: upload real file bytes, queue Android chat job.

    The queued job carries file IDs, authenticated Android fetches real bytes.
    No Drive account, public URL or Google OAuth is required.
    """
    uid = user_scope(user_id, actor)
    if len(text) > 24000:
        raise HTTPException(422, "Question exceeds 24000 characters")
    if not text.strip():
        raise HTTPException(422, "A question is required to send attachments safely")
    if len(files) > 10:
        raise HTTPException(422, "Maximum 10 attachments per turn")
    with connection() as c:
        room = existing_room(c, room_id, uid)
        if room["status"] != "active":
            raise HTTPException(409, "Room is not active")
    accepted = []
    try:
        for upload in files:
            accepted.append(_write_upload(upload, uid, room_id, None, "input"))
        ids = [f["id"] for f in accepted]
        with connection() as c:
            room = existing_room(c, room_id, uid)
            if room["status"] != "active":
                raise HTTPException(409, "Room is not active")
            jid = store_job(c, uid, room_id, "chat.send", text, ids)
            c.execute("INSERT INTO messages VALUES(?,?,?,?,?,?,?)",
                      ("msg_"+new_id(), uid, room_id, jid, "user", text, clock()))
            job = c.execute("SELECT * FROM jobs WHERE id=?", (jid,)).fetchone()
    except Exception:
        # Avoid orphaned files if a later upload or database transaction fails.
        for file in accepted:
            with connection() as c:
                c.execute("DELETE FROM file_objects WHERE id=? AND user_id=?", (file["id"],uid))
            ext = Path(file["name"]).suffix.lower()
            (FILES / (file["id"]+ext)).unlink(missing_ok=True)
        raise
    if on_new_job:
        await on_new_job()
    response = public_job(job)
    response["files"] = accepted
    return response


@router.get("/jobs/{job_id}")
def get_job(job_id: str, user_id: str | None = None, actor=Depends(authentication)):
    uid = user_scope(user_id, actor)
    with connection() as c:
        row = c.execute("SELECT * FROM jobs WHERE id=? AND user_id=?", (job_id, uid)).fetchone()
    if not row:
        raise HTTPException(404, "Job not found")
    return public_job(row)

@router.get("/jobs")
def list_jobs(user_id: str | None = None, room_id: str | None = None, actor=Depends(authentication)):
    uid = user_scope(user_id, actor)
    with connection() as c:
        sql = "SELECT * FROM jobs WHERE user_id=?"
        p = [uid]
        if room_id:
            existing_room(c, room_id, uid, True)
            sql += " AND room_id=?"
            p.append(room_id)
        rows = c.execute(sql + " ORDER BY created_at DESC LIMIT 200", p).fetchall()
    return {"jobs": [public_job(r) for r in rows]}

def _write_upload(up: UploadFile, uid: str, room_id: str | None, job_id: str | None, kind: str):
    name = Path(up.filename or "document.bin").name[:180]
    ext = Path(name).suffix.lower()
    if ext not in FILE_TYPES:
        raise HTTPException(415, "Unsupported extension: " + ext)
    fid = "file_" + new_id()
    file_path = FILES / (fid + ext)
    digest = hashlib.sha256()
    count = 0
    try:
        with file_path.open("wb") as fout:
            while True:
                chunk = up.file.read(256 * 1024)
                if not chunk:
                    break
                count += len(chunk)
                if count > MAX_FILE:
                    raise HTTPException(413, "15MB per file limit")
                digest.update(chunk)
                fout.write(chunk)
        if count == 0:
            raise HTTPException(422, "Empty files are not accepted")
        now = clock()
        mime = mimetypes.guess_type(name)[0] or "application/octet-stream"
        with connection() as c:
            c.execute("INSERT INTO file_objects (id,user_id,room_id,job_id,kind,name,mime,size,sha256,relative_path,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                      (fid, uid, room_id, job_id, kind, name, mime, count, digest.hexdigest(),file_path.name, now))
            row = c.execute("SELECT * FROM file_objects WHERE id=?", (fid,)).fetchone()
        return public_file(row)
    except BaseException:
        file_path.unlink(missing_ok=True)
        raise

@router.post("/files")
def upload_file(user_id: str = Form(...), room_id: str = Form(...), file: UploadFile = File(...),
                actor=Depends(authentication)):
    uid = user_scope(user_id, actor)
    with connection() as c:
        room = existing_room(c, room_id, uid)
        if room["status"] != "active":
            raise HTTPException(409, "Room not active")
    return _write_upload(file, uid, room_id, None, "input")

@router.get("/files")
def list_files(user_id: str | None = None, room_id: str | None = None, actor=Depends(authentication)):
    uid = user_scope(user_id, actor)
    with connection() as c:
        sql = "SELECT * FROM file_objects WHERE user_id=?"
        args = [uid]
        if room_id:
            existing_room(c, room_id, uid, True)
            sql += " AND room_id=?"
            args.append(room_id)
        rows = c.execute(sql+" ORDER BY created_at DESC LIMIT 200",args).fetchall()
    return {"files":[public_file(r) for r in rows]}

@router.get("/files/{file_id}/download")
def download_file(file_id: str, user_id: str | None = None, actor=Depends(authentication)):
    uid = user_scope(user_id, actor)
    with connection() as c:
        r = c.execute("SELECT * FROM file_objects WHERE id=? AND user_id=?", (file_id,uid)).fetchone()
    if not r:
        raise HTTPException(404, "File not found")
    if r["kind"] == "drive" and r["drive_url"]:
        from fastapi.responses import RedirectResponse
        return RedirectResponse(r["drive_url"],status_code=302)
    return FileResponse(FILES / r["relative_path"], filename=r["name"], media_type=r["mime"])

def device_identity(authorization: str | None = Header(default=None)):
    expected = os.environ.get("DEVICE_TOKEN","")
    token = authorization[7:] if authorization and authorization.startswith("Bearer ") else ""
    if not challenge(token, expected):
        raise HTTPException(403, "Invalid device token")
    return True

@router.get("/device/jobs/{job_id}/files/{file_id}")
def device_download(job_id: str, file_id: str, authorized=Depends(device_identity)):
    with connection() as c:
        job = c.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if not job or job["status"] not in ("running","queued"):
            raise HTTPException(404, "No active job")
        if file_id not in json.loads(job["attachment_ids"]):
            raise HTTPException(403, "File is not attached to this job")
        f = c.execute("SELECT * FROM file_objects WHERE id=? AND room_id=? AND user_id=?",
                      (file_id,job["room_id"],job["user_id"])).fetchone()
    if not f:
        raise HTTPException(404, "File missing")
    return FileResponse(FILES / f["relative_path"], filename=f["name"], media_type=f["mime"])

@router.post("/device/jobs/{job_id}/outputs")
def device_upload_output(job_id: str, file: UploadFile = File(...), authorized=Depends(device_identity)):
    with connection() as c:
        job = c.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    if not job or job["status"] not in ("running","completed"):
        raise HTTPException(404, "Job not available for output")
    return _write_upload(file, job["user_id"], job["room_id"], job_id, "output")

def claim_next_job():
    with connection() as c:
        r = c.execute("SELECT * FROM jobs WHERE status='queued' ORDER BY created_at,id LIMIT 1").fetchone()
        if not r:
            return None
        c.execute("UPDATE jobs SET status='running',stage='dispatched',updated_at=? WHERE id=?",
                  (clock(), r["id"]))
        item = c.execute("SELECT * FROM jobs WHERE id=?", (r["id"],)).fetchone()
        room = c.execute("SELECT * FROM rooms WHERE id=?", (r["room_id"],)).fetchone()
        job = public_job(item)
        job["room"] = dict(room)
        # Railway files travel as bytes over authenticated HTTPS. Send
        # metadata to the Android relay; never substitute file URLs for bytes.
        # Retain old Drive links only for explicitly registered legacy links.
        direct_ids = []
        details = []
        links = []
        for fid in job["attachment_ids"]:
            row = c.execute("""SELECT id,kind,name,mime,size,sha256,relative_path,
                                      drive_url,drive_file_id,drive_shared
                               FROM file_objects WHERE id=? AND user_id=? AND room_id=?""",
                            (fid,job["user_id"],job["room_id"])).fetchone()
            if not row:
                raise RuntimeError("Job references a missing scoped file: " + fid)
            if row["kind"] == "input":
                path = FILES / row["relative_path"]
                if not path.is_file():
                    raise RuntimeError("Job references a missing Railway file: " + fid)
                direct_ids.append(fid)
                details.append({k:row[k] for k in ("id","name","mime","size","sha256")})
            elif row["kind"] == "drive" and row["drive_url"] and row["drive_shared"]:
                links.append({"id":fid,"name":row["name"],"mime":row["mime"],
                              "url":row["drive_url"]})
            else:
                raise RuntimeError("Job references an unavailable or private attachment: " + fid)
        if links:
            job["text"] = (job["text"] + "\n\n" +
                "참고할 수 있는 외부 자료 링크 (파일 접근이 불가능하면 그 사실을 설명해 주십시오):\n" +
                "\n".join(f"- {x['name']}: {x['url']}" for x in links)).strip()
        job["drive_links"] = links
        job["attachment_ids"] = direct_ids
        job["attachment_details"] = details
        # A restarted controller has no volatile room mapping. Provide only
        # previously COMPLETED messages from the SAME user and room so the
        # Android accessibility layer can verify the visible conversation.
        # Never include current/new/failed messages as verification anchors.
        history = c.execute("""
            SELECT m.text,m.role,m.job_id
            FROM messages m JOIN jobs completed ON completed.id=m.job_id
            WHERE m.user_id=? AND m.room_id=? AND m.job_id!=?
              AND completed.status='completed'
              AND m.role IN ('assistant','user')
            ORDER BY m.created_at DESC,m.id DESC LIMIT 16
        """, (job["user_id"], job["room_id"], job["id"])).fetchall()
        anchors = []
        seen = set()
        for msg in history:
            txt = " ".join(msg["text"].split())
            # A short greeting or generic response cannot reliably identify
            # an Android conversation; use distinctive nontrivial excerpts.
            if len(txt) < 24 or len(txt) > 50000:
                continue
            first = txt[:200]
            if first in seen:
                continue
            seen.add(first)
            anchors.append({"role": msg["role"], "text": first,
                            "from_job_id": msg["job_id"]})
            if len(anchors) >= 8:
                break
        job["room_anchors"] = anchors
        job.pop("result_text",None)
        return job

def update_job(job_id: str, status: str | None = None, stage: str | None = None,
               error: str | None = None, result_text: str | None = None):
    with connection() as c:
        j = c.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if not j or j["status"] not in ("running","queued"):
            return False
        statuses = {"queued","running","completed","failed"}
        if status and status not in statuses:
            return False
        c.execute("""UPDATE jobs SET status=?,stage=?,error=?,result_text=COALESCE(?,result_text),
                     updated_at=? WHERE id=?""",
                  (status or j["status"],stage or j["stage"],error,result_text,clock(),job_id))
        if status == "completed":
            if j["action"] == "room.delete":
                c.execute("UPDATE rooms SET status='deleted',android_state='deleted',updated_at=? WHERE id=?",
                          (clock(), j["room_id"]))
            elif result_text:
                c.execute("INSERT INTO messages VALUES(?,?,?,?,?,?,?)",
                          ("msg_"+new_id(),j["user_id"],j["room_id"],job_id,"assistant",result_text,clock()))
        elif status == "failed" and j["action"] == "room.delete":
            c.execute("UPDATE rooms SET status='delete_failed',updated_at=? WHERE id=?",
                      (clock(),j["room_id"]))
        return True

def set_room_android_state(room_id: str, state: str, android_title: str | None = None):
    if state not in {"uncreated","active","unverified","deleted"}:
        return
    with connection() as c:
        c.execute("UPDATE rooms SET android_state=?,android_title=COALESCE(?,android_title),updated_at=? WHERE id=?",
                  (state, android_title,clock(),room_id))

def release_running_job(job_id, reason="Device disconnected; will retry"):
    with connection() as c:
        row=c.execute("SELECT status FROM jobs WHERE id=?", (job_id,)).fetchone()
        if row and row["status"]=="running":
            # Automatic retry of a message can duplicate it when transmission was
            # actually completed but the acknowledgement was lost. Fail closed.
            c.execute("UPDATE jobs SET status='failed',stage='connection_lost',error=?,updated_at=? WHERE id=?",
                      (reason,clock(),job_id))
