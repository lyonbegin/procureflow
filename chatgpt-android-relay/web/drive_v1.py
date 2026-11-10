"""Google Drive-backed chat-room files for the Relay API test bench.

Each user authorizes their own Google account once via OAuth2 drive.file.
Refresh tokens are encrypted using a Railway-only Fernet key, and never
exposed through the web test console or job payload.

Files are uploaded to the user's Drive, inside an app-owned folder for each
Railway chat room. No Android file picker or Accessibility attachment is used.
"""
import hashlib
import json
import mimetypes
import os
import secrets
import sqlite3
import time
from pathlib import Path
from urllib.parse import urlencode

import httpx
from cryptography.fernet import Fernet, InvalidToken
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import RedirectResponse

import api_v1 as api

router = APIRouter(prefix="/api/v1/drive", tags=["google-drive"])
GOOGLE_SCOPE = "https://www.googleapis.com/auth/drive.file"
GOOGLE_API = "https://www.googleapis.com/drive/v3/files"
GOOGLE_UPLOAD = "https://www.googleapis.com/upload/drive/v3/files"
TOKEN_URI = "https://oauth2.googleapis.com/token"
MAX_SIZE = api.MAX_FILE

def config():
    client_id = os.environ.get("GOOGLE_OAUTH_CLIENT_ID", "").strip()
    client_secret = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET", "").strip()
    key = os.environ.get("DRIVE_TOKEN_ENCRYPTION_KEY", "").strip()
    domain = os.environ.get("RAILWAY_PUBLIC_DOMAIN", "chatgpt-relay-web-production.up.railway.app").strip()
    redirect = os.environ.get("GOOGLE_OAUTH_REDIRECT_URI", "").strip() or (
        "https://" + domain + "/api/v1/drive/oauth/callback")
    return {"client_id": client_id, "client_secret": client_secret,
            "encryption_key": key, "redirect_uri": redirect}

def ready():
    cfg = config()
    if not cfg["client_id"] or not cfg["client_secret"]:
        raise HTTPException(503, "Google Drive OAuth client is not configured in Railway")
    try:
        Fernet(cfg["encryption_key"].encode())
    except (ValueError, TypeError):
        raise HTTPException(503, "DRIVE_TOKEN_ENCRYPTION_KEY must be a valid Fernet encryption key")
    return cfg

def db_init():
    with api.connection() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS drive_connections (
            user_id TEXT PRIMARY KEY,
            refresh_token_encrypted TEXT NOT NULL,
            root_folder_id TEXT,
            connected_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS drive_oauth_states (
            state_hash TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            expires_at INTEGER NOT NULL
        );
        """)
        room_columns = [row["name"] for row in c.execute("PRAGMA table_info(rooms)").fetchall()]
        if "drive_folder_id" not in room_columns:
            c.execute("ALTER TABLE rooms ADD COLUMN drive_folder_id TEXT")
        file_columns = [row["name"] for row in c.execute("PRAGMA table_info(file_objects)").fetchall()]
        if "drive_file_id" not in file_columns:
            c.execute("ALTER TABLE file_objects ADD COLUMN drive_file_id TEXT")
        if "drive_url" not in file_columns:
            c.execute("ALTER TABLE file_objects ADD COLUMN drive_url TEXT")
        if "drive_shared" not in file_columns:
            c.execute("ALTER TABLE file_objects ADD COLUMN drive_shared INTEGER NOT NULL DEFAULT 0")

db_init()

def has_connection(uid):
    with api.connection() as c:
        return c.execute("SELECT 1 FROM drive_connections WHERE user_id=?",(uid,)).fetchone() is not None

def require_conn(uid):
    with api.connection() as c:
        row = c.execute("SELECT * FROM drive_connections WHERE user_id=?", (uid,)).fetchone()
    if not row:
        raise HTTPException(409, "Google Drive is not connected for this user. Use Drive > Connect first.")
    return dict(row)

def encrypted(token: str, cfg) -> str:
    return Fernet(cfg["encryption_key"].encode()).encrypt(token.encode()).decode()

def refreshed_access(uid: str):
    cfg = ready()
    con = require_conn(uid)
    try:
        refresh = Fernet(cfg["encryption_key"].encode()).decrypt(
            con["refresh_token_encrypted"].encode()).decode()
    except (InvalidToken, ValueError):
        raise HTTPException(503, "Google Drive credentials cannot be decrypted. Check encryption key.")
    try:
        with httpx.Client(timeout=25) as client:
            res = client.post(TOKEN_URI, data={
                "client_id":cfg["client_id"], "client_secret":cfg["client_secret"],
                "refresh_token":refresh, "grant_type":"refresh_token"})
    except httpx.RequestError:
        raise HTTPException(502, "Google OAuth token service unavailable")
    if res.status_code != 200:
        raise HTTPException(502, "Google Drive token refresh failed; reconnect account")
    access = res.json().get("access_token")
    if not access:
        raise HTTPException(502, "Google Drive access token missing")
    return access

def google(uid, method, url, *, json_body=None, params=None, content=None, content_type=None):
    access = refreshed_access(uid)
    headers={"Authorization":"Bearer " + access}
    if content_type:
        headers["Content-Type"] = content_type
    try:
        with httpx.Client(timeout=55) as client:
            res = client.request(method, url, json=json_body, params=params, content=content,
                                 headers=headers)
    except httpx.RequestError as e:
        raise HTTPException(502, "Google Drive connection failed: " + type(e).__name__)
    if res.status_code not in (200,201,204):
        try:
            msg = res.json().get("error",{}).get("message","Google Drive API rejected request")
        except (ValueError, AttributeError):
            msg = "Google Drive API rejected request"
        raise HTTPException(502, f"Google Drive API HTTP {res.status_code}: {str(msg)[:200]}")
    if not res.content: return {}
    try: return res.json()
    except ValueError: raise HTTPException(502, "Google Drive API response was not JSON")

def drive_create_folder(uid, name, parent=None):
    data = {"name":name, "mimeType":"application/vnd.google-apps.folder"}
    if parent: data["parents"] = [parent]
    out = google(uid, "POST", GOOGLE_API, json_body=data, params={"fields":"id,name,webViewLink"})
    if not out.get("id"): raise HTTPException(502, "Google Drive folder ID missing")
    return out["id"]

def ensure_room_folder(uid: str, room_id: str):
    with api.connection() as c:
        room = api.existing_room(c, room_id, uid)
        if room["drive_folder_id"]: return room["drive_folder_id"]
    conn = require_conn(uid)
    parent = conn.get("root_folder_id")
    if not parent:
        # A connected user's Drive has its own independent app-owned folder.
        parent = drive_create_folder(uid, "ChatGPT Relay - " + uid[:48])
        with api.connection() as c:
            c.execute("UPDATE drive_connections SET root_folder_id=COALESCE(root_folder_id,?) "
                      "WHERE user_id=?", (parent,uid))
            row = c.execute("SELECT root_folder_id FROM drive_connections WHERE user_id=?",
                            (uid,)).fetchone()
            parent = row["root_folder_id"]
    with api.connection() as c:
        room = api.existing_room(c,room_id,uid)
    safe_title = " ".join(room["title"].split())[:72]
    folder = drive_create_folder(uid, safe_title + " [" + room_id[-8:] + "]",parent)
    with api.connection() as c:
        c.execute("UPDATE rooms SET drive_folder_id=COALESCE(drive_folder_id,?) WHERE id=? AND user_id=?",
                  (folder,room_id,uid))
        final = c.execute("SELECT drive_folder_id FROM rooms WHERE id=? AND user_id=?",
                          (room_id,uid)).fetchone()
    return final["drive_folder_id"]

@router.get("/status")
def status(user_id: str | None = None, actor=Depends(api.authentication)):
    uid = api.user_scope(user_id,actor)
    cfg = config()
    valid = bool(cfg["client_id"] and cfg["client_secret"] and cfg["encryption_key"])
    try:
        con = require_conn(uid)
        connected = True
    except HTTPException as ex:
        if ex.status_code != 409: raise
        con = {}
        connected = False
    return {"user_id":uid, "configured": valid, "connected":connected,
            "root_folder_id":con.get("root_folder_id"),
            "redirect_uri":cfg["redirect_uri"],
            "scope":"drive.file",
            "note": "Google Drive link does not guarantee ChatGPT can inspect file contents"}

@router.post("/connect")
def connect(user_id: str | None = None, actor=Depends(api.authentication)):
    cfg = ready()
    uid = api.user_scope(user_id,actor)
    # One-use state binds OAuth callback to a pre-authenticated API user.
    state = secrets.token_urlsafe(40)
    digest = hashlib.sha256(state.encode()).hexdigest()
    with api.connection() as c:
        c.execute("DELETE FROM drive_oauth_states WHERE expires_at<?",(int(time.time()),))
        c.execute("INSERT INTO drive_oauth_states(state_hash,user_id,expires_at) VALUES(?,?,?)",
                  (digest,uid,int(time.time())+600))
    link = "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode({
        "client_id":cfg["client_id"],
        "redirect_uri":cfg["redirect_uri"],
        "response_type":"code",
        "scope":GOOGLE_SCOPE,
        "state":state,
        "access_type":"offline",
        "prompt":"consent",
    })
    return {"authorization_url":link, "user_id":uid}

@router.get("/oauth/callback",include_in_schema=False)
def callback(state: str = "", code: str = "", error: str = ""):
    if error: return RedirectResponse("/?drive_error=google_consent_declined",status_code=303)
    if not code or not state: raise HTTPException(400,"Google OAuth code/state missing")
    cfg = ready()
    digest = hashlib.sha256(state.encode()).hexdigest()
    with api.connection() as c:
        row = c.execute("SELECT * FROM drive_oauth_states WHERE state_hash=? AND expires_at>?",
                        (digest,int(time.time()))).fetchone()
        if not row: raise HTTPException(403,"OAuth state invalid or expired")
        uid = row["user_id"]
        c.execute("DELETE FROM drive_oauth_states WHERE state_hash=?", (digest,))
    try:
        with httpx.Client(timeout=25) as client:
            response = client.post(TOKEN_URI, data={
                "client_id":cfg["client_id"],"client_secret":cfg["client_secret"],
                "redirect_uri":cfg["redirect_uri"],"code":code,
                "grant_type":"authorization_code"})
    except httpx.RequestError:
        raise HTTPException(502,"Google token exchange unavailable")
    if response.status_code != 200:
        raise HTTPException(502,"Google OAuth code exchange failed")
    refresh = response.json().get("refresh_token")
    if not refresh:
        raise HTTPException(502,"Google did not issue a refresh token; revoke/reconnect with consent")
    crypt = encrypted(refresh,cfg)
    with api.connection() as c:
        c.execute("""INSERT INTO drive_connections(user_id,refresh_token_encrypted,root_folder_id,connected_at)
                     VALUES(?,?,NULL,?)
                     ON CONFLICT(user_id) DO UPDATE SET
                       refresh_token_encrypted=excluded.refresh_token_encrypted,
                       connected_at=excluded.connected_at""",
                  (uid,crypt,api.clock()))
    return RedirectResponse("/?drive_connected=1&user_id=" + uid,status_code=303)

@router.post("/rooms/{room_id}/folder")
def create_room_folder(room_id: str,user_id: str | None = None,
                       actor=Depends(api.authentication)):
    uid = api.user_scope(user_id,actor)
    folder = ensure_room_folder(uid,room_id)
    return {"room_id":room_id, "drive_folder_id":folder,
            "status":"created", "folder_link":"https://drive.google.com/drive/u/0/folders/"+folder}

@router.post("/files")
def upload_to_drive(user_id: str = Form(...),room_id: str = Form(...),
                    share_link: bool = Form(default=False),
                    file: UploadFile = File(...),
                    actor=Depends(api.authentication)):
    uid = api.user_scope(user_id,actor)
    ready()
    # Room ownership checked before calling any external Google API.
    with api.connection() as c:
        room = api.existing_room(c,room_id,uid)
        if room["status"]!="active":raise HTTPException(409,"Room is not active")
    name = Path(file.filename or "attachment.bin").name[:180]
    suffix = Path(name).suffix.lower()
    if suffix not in api.FILE_TYPES:
        raise HTTPException(415,"Unsupported extension: "+suffix)
    payload = file.file.read(MAX_SIZE+1)
    if not payload: raise HTTPException(422,"Empty file")
    if len(payload)>MAX_SIZE: raise HTTPException(413,"Max 15MB per file")
    folder = ensure_room_folder(uid,room_id)
    mime = mimetypes.guess_type(name)[0] or "application/octet-stream"
    params={"uploadType":"multipart","fields":"id,name,mimeType,size,webViewLink,parents"}
    body_meta={"name":name,"parents":[folder],"description":
               "ChatGPT Relay attached file for "+room_id}
    # Drive uploadType=multipart expects multipart/related (NOT multipart/form-data
    # emitted by httpx's files= shorthand).
    boundary = "relaydrive_" + secrets.token_hex(24)
    head = json.dumps(body_meta,ensure_ascii=False).encode("utf-8")
    body = (("--" + boundary + "\r\n"
             "Content-Type: application/json; charset=UTF-8\r\n\r\n").encode()
            + head
            + ("\r\n--" + boundary + "\r\n"
               "Content-Type: " + mime + "\r\n\r\n").encode()
            + payload
            + ("\r\n--" + boundary + "--\r\n").encode())
    resp = google(uid,"POST",GOOGLE_UPLOAD,params=params,
                  content=body,content_type="multipart/related; boundary=" + boundary)
    fid=resp.get("id")
    if not fid:raise HTTPException(502,"Drive API did not return a file ID")
    # Explicit user consent: only set anyone/reader when share_link=true.
    shared=False
    if share_link:
        google(uid,"POST",
               "https://www.googleapis.com/drive/v3/files/"+fid+"/permissions",
               json_body={"type":"anyone","role":"reader"},
               params={"fields":"id"})
        shared=True
    url = resp.get("webViewLink")
    if not url:
        f=google(uid,"GET",GOOGLE_API+"/"+fid,params={"fields":"id,webViewLink"})
        url=f.get("webViewLink")
    if not url or not url.startswith("https://"):
        raise HTTPException(502,"Drive did not supply a file webViewLink")
    local_id = "file_" + api.new_id()
    digest=hashlib.sha256(payload).hexdigest()
    with api.connection() as c:
        c.execute("""INSERT INTO file_objects
           (id,user_id,room_id,job_id,kind,name,mime,size,sha256,relative_path,created_at,
            drive_file_id,drive_url,drive_shared)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                  (local_id,uid,room_id,None,"drive",name,mime,len(payload),digest,"",
                   api.clock(),fid,url,1 if shared else 0))
        stored=c.execute("SELECT * FROM file_objects WHERE id=?",(local_id,)).fetchone()
    return api.public_file(stored)

@router.post("/files/{file_id}/share")
def share_one_file(file_id: str,user_id: str | None = None,
                   actor=Depends(api.authentication)):
    uid=api.user_scope(user_id,actor)
    with api.connection() as c:
        f=c.execute("SELECT * FROM file_objects WHERE id=? AND user_id=? AND drive_file_id IS NOT NULL",
                    (file_id,uid)).fetchone()
        if not f:raise HTTPException(404,"Drive file not found")
        fid=f["drive_file_id"]
        if f["drive_shared"]:return api.public_file(f)
    google(uid,"POST","https://www.googleapis.com/drive/v3/files/"+fid+"/permissions",
           json_body={"type":"anyone","role":"reader"},params={"fields":"id"})
    with api.connection() as c:
        c.execute("UPDATE file_objects SET drive_shared=1 WHERE id=? AND user_id=?",(file_id,uid))
        row=c.execute("SELECT * FROM file_objects WHERE id=?",(file_id,)).fetchone()
    return api.public_file(row)
