"""Isolated browser-room and file trial (no console tokens or API keys).

Visitors receive private, signed, HttpOnly cookie sessions. The external
trial accepts short free-text questions under both per-browser and global rate
caps, with strictly isolated rooms. It does not expose private existing rooms,
owner credentials or browser session files; native binary attachment to the
remote ChatGPT account remains unsupported.
"""
import hashlib
import hmac
import os
import secrets
import time
import threading
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
import api_v1

router = APIRouter(prefix="/web/api", tags=["browser-chat-trial"])
COOKIE = "hitel_web_trial"
SESSION_KEY = (os.getenv("WEB_SESSION_SIGNING_KEY") or "").encode("utf-8")
# Volatile key is limited to local dev/tests. Production must have stable key.
if not SESSION_KEY:
    if os.getenv("PUBLIC_SMOKE_ONLY") == "1" and os.getenv("RELAY_DATA_DIR","") == "/data":
        raise RuntimeError("WEB_SESSION_SIGNING_KEY is mandatory for persistent browser sessions")
    SESSION_KEY = secrets.token_bytes(32)
PRESETS = {
    "connection": "연결 확인 시험입니다. 정확히 HITEL_W2A_OK_20261113만 답변하십시오.",
    "hello": "안녕하세요. 한 문장으로 인사해 주세요.",
    "capabilities": "어떤 일을 도와주실 수 있는지 한 문장으로 알려주세요.",
}
COOKIE_MAX_AGE = 7 * 86400
MAX_ROOMS = 12
MAX_FILES_PER_ROOM = 20
MAX_PUBLIC_TESTS_PER_HOUR = 8
MAX_GLOBAL_TESTS_PER_DAY = 100
MAX_FREE_TEXT_CHARACTERS = 2000
MAX_FREE_TEXT_PER_HOUR = 5
MAX_GLOBAL_FREE_TEXT_PER_DAY = 30
MAX_UPLOAD_BYTES = 8 * 1024 * 1024
MAX_USER_BYTES = 24 * 1024 * 1024
MAX_TOTAL_PUBLIC_BYTES = 256 * 1024 * 1024
_storage_lock = threading.RLock()
MAX_LOCAL_PROFILES = 5

# Local test profiles belong only to one signed browser visitor. They are NOT
# Google or ChatGPT accounts and never grant OAuth or ChatGPT login access.
with api_v1.connection() as _db:
    _db.execute("""CREATE TABLE IF NOT EXISTS web_trial_profiles(
        owner_hash TEXT NOT NULL,
        profile_id TEXT NOT NULL,
        user_id TEXT NOT NULL UNIQUE,
        name TEXT NOT NULL,
        is_active INTEGER NOT NULL DEFAULT 0,
        created_at INTEGER NOT NULL,
        PRIMARY KEY(owner_hash,profile_id)
    )""")
    _db.execute("CREATE INDEX IF NOT EXISTS idx_trial_profile_owner ON web_trial_profiles(owner_hash)")


def _sign(raw: str) -> str:
    return hmac.new(SESSION_KEY, raw.encode("ascii"), hashlib.sha256).hexdigest()

def _unpack(cookie: str | None):
    if not cookie or "." not in cookie:
        return None
    raw, sig = cookie.rsplit(".",1)
    if len(raw) != 48 or len(sig) != 64:
        return None
    if not all(c in "0123456789abcdef" for c in raw+sig):
        return None
    if not hmac.compare_digest(_sign(raw),sig):
        return None
    return raw

def _uid(raw: str):
    digest = hmac.new(SESSION_KEY, ("user:"+raw).encode(),hashlib.sha256).hexdigest()
    return "usr_browser_" + digest[:48]

def _owner_hash(raw: str):
    return hmac.new(SESSION_KEY, ("owner:" + raw).encode(), hashlib.sha256).hexdigest()

def _profile_uid(raw: str, profile_id: str):
    if profile_id == "default":
        return _uid(raw)  # Existing visitors retain all prior rooms and files.
    digest = hmac.new(
        SESSION_KEY, ("profile:" + raw + ":" + profile_id).encode(), hashlib.sha256
    ).hexdigest()
    return "usr_browser_" + digest[:48]

def _ensure_default_profile(db, raw: str):
    owner = _owner_hash(raw)
    row = db.execute("SELECT 1 FROM web_trial_profiles WHERE owner_hash=? LIMIT 1", (owner,)).fetchone()
    if not row:
        db.execute(
            "INSERT INTO web_trial_profiles(owner_hash,profile_id,user_id,name,is_active,created_at) "
            "VALUES(?,?,?,?,1,?)",
            (owner, "default", _uid(raw), "기본 프로필", api_v1.clock())
        )
    return owner

def _active_profile(db, raw: str):
    owner = _owner_hash(raw)
    row = db.execute(
        "SELECT profile_id,user_id,name FROM web_trial_profiles "
        "WHERE owner_hash=? AND is_active=1 LIMIT 1", (owner,)
    ).fetchone()
    return dict(row) if row else None

def _csrf(raw: str):
    return hmac.new(SESSION_KEY, ("csrf:"+raw).encode(),hashlib.sha256).hexdigest()

def _secure_cookie(request: Request):
    # Railway terminates TLS at its gateway, so request.url.scheme may be http.
    # A browser-facing application on an HTTPS domain must use Secure.
    host = request.headers.get("host","")
    return host != "testserver" and not host.startswith(("localhost","127.0.0.1"))

def _owner(request: Request, mutate=False):
    if os.environ.get("PUBLIC_SMOKE_ONLY") != "1":
        raise HTTPException(404)
    raw = _unpack(request.cookies.get(COOKIE))
    if not raw:
        raise HTTPException(401,"이 브라우저에서 먼저 화면을 열어주세요.")
    if mutate:
        origin = request.headers.get("origin","")
        host = request.headers.get("host","").lower()
        if origin and origin not in {"https://"+host,"http://"+host}:
            raise HTTPException(403,"다른 사이트에서는 변경할 수 없습니다.")
        if not hmac.compare_digest(request.headers.get("x-web-csrf",""),_csrf(raw)):
            raise HTTPException(403,"잘못된 브라우저 요청입니다.")
    return raw

def _actor(request: Request, mutate=False):
    raw = _owner(request, mutate)
    with api_v1.connection() as db:
        profile = _active_profile(db, raw)
    if not profile:
        # Old browser cookies remain readable until bootstrap migrates them.
        return _uid(raw)
    return profile["user_id"]

def _room(db,uid,rid):
    return api_v1.existing_room(db,rid,uid)

class ProfileInput(BaseModel):
    name: str = Field(min_length=1, max_length=40)

class RoomInput(BaseModel):
    title: str = Field(min_length=1,max_length=80)

class PresetInput(BaseModel):
    preset: str = Field(min_length=1,max_length=30)

class MessageInput(BaseModel):
    text: str = Field(min_length=1,max_length=MAX_FREE_TEXT_CHARACTERS)
    # Sent separately on every message; never a cookie, password, or bearer token.
    account_id: str | None = Field(default=None, max_length=80)

@router.get("/bootstrap")
def bootstrap(request: Request, response: Response):
    if os.environ.get("PUBLIC_SMOKE_ONLY") != "1":
        raise HTTPException(404)
    raw=_unpack(request.cookies.get(COOKIE))
    created = raw is None
    if created:
        raw=secrets.token_hex(24)
    with _storage_lock:
        with api_v1.connection() as db:
            _ensure_default_profile(db, raw)
            active = _active_profile(db, raw)
            uid = active["user_id"]
            db.execute(
                "INSERT OR IGNORE INTO users(id,name,api_key_hash,created_at) VALUES(?,?,?,?)",
                (uid,"Isolated browser trial",hashlib.sha256((uid+":disabled").encode()).hexdigest(),api_v1.clock()),
            )
    if created:
        response.set_cookie(COOKIE,raw+"."+_sign(raw),
                            httponly=True,secure=_secure_cookie(request),
                            samesite="strict",max_age=COOKIE_MAX_AGE,path="/")
    response.headers["Cache-Control"]="no-store"
    return {"csrf":_csrf(raw),"workerConnected":False,
            "profile":{"id":active["profile_id"],"name":active["name"]},
            "loginProvider":"anonymous_local_trial",
            "presets":[{"id":k,"label":v} for k,v in PRESETS.items()],
            "limits":{"rooms":MAX_ROOMS,"fileMB":8,"profiles":MAX_LOCAL_PROFILES}}

@router.get("/status")
def status(request: Request):
    # The identifier below distinguishes this anonymous browser session from
    # another visitor. It is a non-secret display tag, not a ChatGPT identity.
    uid = _actor(request)
    from app import web2api_device
    raw = _owner(request)
    with api_v1.connection() as db:
        active = _active_profile(db, raw)
    with api_v1.connection() as db:
        linked = db.execute(
            "SELECT count(*) FROM hitel_verified_chatgpt_accounts WHERE browser_owner=?",
            (_owner_hash(raw),)
        ).fetchone()[0]
    return {"workerConnected":web2api_device is not None,
            "verifiedChatGPTIdentityCount":linked,
            "profileName":active["name"] if active else "기본 프로필",
            "profileId":active["profile_id"] if active else "default",
            "browserSessionType":"anonymous_cookie",
            "browserSessionTag":uid[-8:],
            "chatgptAccountLinked":False,
            "workerAccountIdentityAvailable":False,
            "mode":"isolated_external_trial","freeTextSendSupported":True,
            "maxFreeTextCharacters":MAX_FREE_TEXT_CHARACTERS,
            "fileToChatGPTSupported":False}

@router.get("/profiles")
def list_profiles(request: Request):
    raw = _owner(request)
    with api_v1.connection() as db:
        rows = db.execute(
            "SELECT profile_id,name,is_active,created_at FROM web_trial_profiles "
            "WHERE owner_hash=? ORDER BY created_at,profile_id",
            (_owner_hash(raw),)
        ).fetchall()
    return {"profiles": [
        {"id":r["profile_id"],"name":r["name"],
         "active":bool(r["is_active"]),"deletable":r["profile_id"] != "default"}
        for r in rows
    ],"provider":"HITEL_local_test_profiles","chatgptAccountLinked":False,
       "maxProfiles":MAX_LOCAL_PROFILES}


@router.post("/profiles")
def add_profile(body: ProfileInput, request: Request):
    raw = _owner(request, True)
    name = body.name.strip()
    if not name:
        raise HTTPException(422, "프로필 이름을 입력해 주십시오.")
    owner = _owner_hash(raw)
    with _storage_lock:
        with api_v1.connection() as db:
            _ensure_default_profile(db, raw)
            n = db.execute(
                "SELECT count(*) FROM web_trial_profiles WHERE owner_hash=?", (owner,)
            ).fetchone()[0]
            if n >= MAX_LOCAL_PROFILES:
                raise HTTPException(429, "시험 프로필은 최대 5개입니다.")
            if db.execute("SELECT 1 FROM web_trial_profiles WHERE owner_hash=? AND name=?",
                          (owner,name)).fetchone():
                raise HTTPException(409, "같은 이름의 프로필이 있습니다.")
            profile_id = secrets.token_hex(12)
            uid = _profile_uid(raw,profile_id)
            db.execute("INSERT INTO users(id,name,api_key_hash,created_at) VALUES(?,?,?,?)",
                       (uid,"Isolated browser trial",
                        hashlib.sha256((uid+":disabled").encode()).hexdigest(),api_v1.clock()))
            db.execute(
                "INSERT INTO web_trial_profiles VALUES(?,?,?,?,0,?)",
                (owner,profile_id,uid,name,api_v1.clock())
            )
    return {"profile":{"id":profile_id,"name":name,"active":False},
            "chatgptAccountLinked":False}


@router.post("/profiles/{profile_id}/activate")
def activate_profile(profile_id: str, request: Request):
    raw = _owner(request, True)
    owner = _owner_hash(raw)
    with _storage_lock:
        with api_v1.connection() as db:
            selected = db.execute(
                "SELECT profile_id,name FROM web_trial_profiles "
                "WHERE owner_hash=? AND profile_id=?", (owner,profile_id)
            ).fetchone()
            if not selected:
                raise HTTPException(404,"해당 프로필이 없습니다.")
            db.execute("UPDATE web_trial_profiles SET is_active=0 WHERE owner_hash=?", (owner,))
            db.execute(
                "UPDATE web_trial_profiles SET is_active=1 WHERE owner_hash=? AND profile_id=?",
                (owner,profile_id)
            )
    return {"profile":{"id":selected["profile_id"],"name":selected["name"]},
            "chatgptAccountLinked":False}


@router.delete("/profiles/{profile_id}")
def remove_profile(profile_id: str, request: Request):
    raw = _owner(request, True)
    if profile_id == "default":
        raise HTTPException(409,"기본 프로필은 삭제할 수 없습니다.")
    owner = _owner_hash(raw)
    with _storage_lock:
        with api_v1.connection() as db:
            selected = db.execute(
                "SELECT user_id,is_active FROM web_trial_profiles "
                "WHERE owner_hash=? AND profile_id=?", (owner,profile_id)
            ).fetchone()
            if not selected:
                raise HTTPException(404,"해당 프로필이 없습니다.")
            uid = selected["user_id"]
            pending = db.execute(
                "SELECT 1 FROM jobs WHERE user_id=? AND status IN ('queued','running') LIMIT 1",
                (uid,)
            ).fetchone()
            if pending:
                raise HTTPException(409,"이 프로필의 전송 작업이 완료된 후 삭제할 수 있습니다.")
            paths = db.execute(
                "SELECT relative_path FROM file_objects WHERE user_id=?", (uid,)
            ).fetchall()
            # Only data belonging to the chosen profile may be deleted.
            db.execute("DELETE FROM file_objects WHERE user_id=?", (uid,))
            db.execute("DELETE FROM messages WHERE user_id=?", (uid,))
            db.execute("DELETE FROM jobs WHERE user_id=?", (uid,))
            db.execute("DELETE FROM rooms WHERE user_id=?", (uid,))
            db.execute("DELETE FROM users WHERE id=?", (uid,))
            db.execute("DELETE FROM web_trial_profiles WHERE owner_hash=? AND profile_id=?",
                       (owner,profile_id))
            if selected["is_active"]:
                db.execute(
                    "UPDATE web_trial_profiles SET is_active=1 "
                    "WHERE owner_hash=? AND profile_id='default'", (owner,)
                )
        for item in paths:
            (api_v1.FILES/item["relative_path"]).unlink(missing_ok=True)
    return {"deleted":True, "activeProfileId":"default" if selected["is_active"] else None,
            "chatgptAccountDeleted":False}


@router.get("/rooms")
def list_rooms(request: Request):
    uid=_actor(request)
    with api_v1.connection() as db:
        rows=db.execute(
            "SELECT id,title,created_at,updated_at,chatgpt_account_id FROM rooms "
            "WHERE user_id=? AND status!='deleted' ORDER BY updated_at DESC LIMIT 100",
            (uid,)).fetchall()
    return {"rooms":[dict(x) for x in rows]}

@router.post("/rooms")
def create_room(body:RoomInput,request:Request):
    uid=_actor(request,True)
    title=body.title.strip()
    if not title:raise HTTPException(422,"방 이름을 입력해주세요.")
    now=api_v1.clock()
    with api_v1.connection() as db:
        count=db.execute("SELECT count(*) FROM rooms WHERE user_id=? AND status!='deleted'",(uid,)).fetchone()[0]
        if count>=MAX_ROOMS:raise HTTPException(429,"시험용 대화방은 최대 12개입니다.")
        rid="room_"+api_v1.new_id()
        db.execute("INSERT INTO rooms(id,user_id,title,android_state,created_at,updated_at) VALUES(?,?,?,?,?,?)",
                   (rid,uid,title,"uncreated",now,now))
    return {"room":{"id":rid,"title":title,"created_at":now,"updated_at":now}}

@router.patch("/rooms/{rid}")
def rename_room(rid:str,body:RoomInput,request:Request):
    uid=_actor(request,True)
    title=body.title.strip()
    if not title:raise HTTPException(422,"방 이름을 입력해주세요.")
    with api_v1.connection() as db:
        _room(db,uid,rid)
        db.execute("UPDATE rooms SET title=?,updated_at=? WHERE id=? AND user_id=?",
                   (title,api_v1.clock(),rid,uid))
    return {"id":rid,"title":title}

@router.delete("/rooms/{rid}")
def delete_room(rid:str,request:Request):
    uid=_actor(request,True)
    with _storage_lock:
        with api_v1.connection() as db:
            _room(db,uid,rid)
            in_flight=db.execute(
                "SELECT 1 FROM jobs WHERE user_id=? AND room_id=? AND status IN ('queued','running') LIMIT 1",
                (uid,rid)).fetchone()
            if in_flight:raise HTTPException(409,"진행 중인 시험이 끝난 뒤 삭제할 수 있습니다.")
            paths=db.execute("SELECT relative_path FROM file_objects WHERE user_id=? AND room_id=?",
                             (uid,rid)).fetchall()
            db.execute("DELETE FROM file_objects WHERE user_id=? AND room_id=?",(uid,rid))
            db.execute("DELETE FROM messages WHERE user_id=? AND room_id=?",(uid,rid))
            db.execute("DELETE FROM jobs WHERE user_id=? AND room_id=?",(uid,rid))
            db.execute("DELETE FROM rooms WHERE user_id=? AND id=?",(uid,rid))
        for row in paths:
            (api_v1.FILES / row["relative_path"]).unlink(missing_ok=True)
    return {"deleted":True}

@router.get("/rooms/{rid}")
def room_detail(rid:str,request:Request):
    uid=_actor(request)
    with api_v1.connection() as db:
        room=dict(_room(db,uid,rid))
        msgs=db.execute(
            "SELECT id,role,text,job_id,created_at FROM messages "
            "WHERE user_id=? AND room_id=? ORDER BY created_at,id LIMIT 300",
            (uid,rid)).fetchall()
        jobs=db.execute(
            "SELECT id,status,stage,error,created_at FROM jobs "
            "WHERE user_id=? AND room_id=? ORDER BY created_at DESC LIMIT 30",
            (uid,rid)).fetchall()
        files=db.execute(
            "SELECT id,name,mime,size,created_at FROM file_objects "
            "WHERE user_id=? AND room_id=? ORDER BY created_at DESC LIMIT 50",
            (uid,rid)).fetchall()
    return {"room":{"id":room["id"],"title":room["title"],"chatgpt_url":room["chatgpt_url"]},
            "messages":[dict(x) for x in msgs],"jobs":[dict(x) for x in jobs],
            "files":[dict(x) for x in files]}

@router.post("/rooms/{rid}/files")
def attach_file(rid:str,request:Request,file:UploadFile=File(...)):
    uid=_actor(request,True)
    length=file.size
    if length is not None and length>MAX_UPLOAD_BYTES:
        raise HTTPException(413,"파일당 8MB 이하만 업로드할 수 있습니다.")
    requested=length if length is not None else MAX_UPLOAD_BYTES
    # Single Railway replica: process-local lock also serializes quota checks
    # against concurrent browser uploads and deletions.
    with _storage_lock:
        with api_v1.connection() as db:
            _room(db,uid,rid)
            n=db.execute("SELECT count(*) FROM file_objects WHERE user_id=? AND room_id=?",
                         (uid,rid)).fetchone()[0]
            user_bytes=db.execute("SELECT coalesce(sum(size),0) FROM file_objects WHERE user_id=?",
                                  (uid,)).fetchone()[0]
            public_bytes=db.execute("SELECT coalesce(sum(size),0) FROM file_objects "
                                    "WHERE user_id LIKE 'usr_browser_%'").fetchone()[0]
        if n>=MAX_FILES_PER_ROOM:
            raise HTTPException(429,"방당 첨부 파일은 최대 20개입니다.")
        if user_bytes + requested > MAX_USER_BYTES:
            raise HTTPException(413,"브라우저별 파일 보관 한도는 총 24MB입니다.")
        if public_bytes + requested > MAX_TOTAL_PUBLIC_BYTES:
            raise HTTPException(507,"공개 시험 파일 저장 공간 한도에 도달했습니다.")
        # Reuse the audited streaming writer. Never store unsupported files.
        out=api_v1._write_upload(file,uid,rid,None,"input")
        if out["size"]>MAX_UPLOAD_BYTES:
            with api_v1.connection() as db:
                db.execute("DELETE FROM file_objects WHERE id=? AND user_id=?",(out["id"],uid))
            (api_v1.FILES/(out["id"]+Path(out["name"]).suffix.lower())).unlink(missing_ok=True)
            raise HTTPException(413,"파일당 8MB 이하만 업로드할 수 있습니다.")
    return {"file":{"id":out["id"],"name":out["name"],"size":out["size"],"mime":out["mime"]},
            "sentToChatGPT":False}

@router.get("/files/{fid}")
def download(fid:str,request:Request):
    uid=_actor(request)
    with api_v1.connection() as db:
        f=db.execute("SELECT name,mime,relative_path,room_id FROM file_objects "
                     "WHERE id=? AND user_id=? AND kind='input'",(fid,uid)).fetchone()
        if not f:raise HTTPException(404,"파일을 찾을 수 없습니다.")
        _room(db,uid,f["room_id"])
    path=api_v1.FILES/f["relative_path"]
    if not path.is_file():raise HTTPException(404,"보관 파일이 존재하지 않습니다.")
    return FileResponse(path,media_type="application/octet-stream",filename=f["name"],
                        headers={"Cache-Control":"no-store","X-Content-Type-Options":"nosniff",
                                 "Content-Security-Policy":"sandbox"})

@router.post("/rooms/{rid}/test")
async def send_preset(rid:str,body:PresetInput,request:Request):
    uid=_actor(request,True)
    # Preset buttons cannot omit account_id and reach a different session.
    with api_v1.connection() as db:
        selected=db.execute(
            "SELECT 1 FROM hitel_verified_chatgpt_accounts "
            "WHERE browser_owner=? AND active=1 LIMIT 1",
            (_owner_hash(_owner(request)),),
        ).fetchone()
    if selected:
        raise HTTPException(409,"계정이 선택된 경우 계정 ID가 포함된 일반 채팅으로 보내십시오.")
    if body.preset not in PRESETS:raise HTTPException(422,"허용된 시험 질문이 아닙니다.")
    now=api_v1.clock()
    with api_v1.connection() as db:
        room=_room(db,uid,rid)
        if db.execute("SELECT 1 FROM jobs WHERE user_id=? AND room_id=? "
                      "AND status IN ('queued','running') LIMIT 1",(uid,rid)).fetchone():
            raise HTTPException(409,"이 방에는 진행 중인 질문이 있습니다.")
        per_user=db.execute("SELECT count(*) FROM jobs WHERE user_id=? AND "
                            "created_at>? ",(uid,now-3600*1000)).fetchone()[0]
        global_count=db.execute(
            "SELECT count(*) FROM jobs WHERE user_id LIKE 'usr_browser_%' AND created_at>?",
            (now-86400*1000,)).fetchone()[0]
        if per_user>=MAX_PUBLIC_TESTS_PER_HOUR or global_count>=MAX_GLOBAL_TESTS_PER_DAY:
            raise HTTPException(429,"시험 횟수 제한에 도달했습니다.")
        if not room["chatgpt_url"] and db.execute(
            "SELECT 1 FROM jobs WHERE user_id=? AND room_id=? AND status='completed' LIMIT 1",
            (uid,rid)).fetchone():
            raise HTTPException(409,"방의 이전 대화 연결을 확인할 수 없어 중복 전송을 막았습니다.")
        jid=api_v1.store_job(db,uid,rid,"chat.send",PRESETS[body.preset],[])
        db.execute("INSERT INTO messages VALUES(?,?,?,?,?,?,?)",
                   ("msg_"+api_v1.new_id(),uid,rid,jid,"user",PRESETS[body.preset],now))
        db.execute("UPDATE rooms SET updated_at=? WHERE id=?",(now,rid))
    from app import dispatch_next
    await dispatch_next()
    return {"jobId":jid,"queued":True,"sentToChatGPT":False}

@router.post("/rooms/{rid}/message")
async def send_free_text(rid: str, body: MessageInput, request: Request):
    """Queue a real free-text ChatGPT turn from this browser's own room.

    This is NOT a public ChatGPT account administration API. The anonymous
    external trial has strict input, frequency and total quota limits. Its
    browser cookie and CSRF header never permit viewing another visitor's or
    the owner's existing rooms, credentials or files.
    """
    uid = _actor(request, True)
    text = body.text.strip()
    if not text:
        raise HTTPException(422, "질문 내용을 입력해 주십시오.")
    if len(text) > MAX_FREE_TEXT_CHARACTERS:
        raise HTTPException(422, "외부 시험은 질문당 최대 2,000자입니다.")
    if any(ord(ch) < 32 and ch not in (chr(10), chr(13), chr(9)) for ch in text):
        raise HTTPException(422, "제어 문자는 전송할 수 없습니다.")

    now = api_v1.clock()
    with _storage_lock:
        with api_v1.connection() as db:
            room = _room(db, uid, rid)
            unfinished = db.execute(
                "SELECT 1 FROM jobs WHERE user_id=? AND room_id=? "
                "AND status IN ('queued','running') LIMIT 1", (uid, rid)
            ).fetchone()
            if unfinished:
                raise HTTPException(409, "진행 중인 질문이 있습니다. 답변을 확인해 주십시오.")
            hourly = db.execute(
                "SELECT count(*) FROM jobs WHERE user_id=? AND action='chat.send' "
                "AND created_at>?", (uid, now - 3600 * 1000)
            ).fetchone()[0]
            daily = db.execute(
                "SELECT count(*) FROM jobs WHERE user_id LIKE 'usr_browser_%' "
                "AND action='chat.send' AND created_at>?",
                (now - 86400 * 1000,)
            ).fetchone()[0]
            if hourly >= MAX_FREE_TEXT_PER_HOUR or daily >= MAX_GLOBAL_FREE_TEXT_PER_DAY:
                raise HTTPException(429, "외부 시험 전송 횟수 제한입니다. 나중에 다시 시험해 주십시오.")
            # Never guess the target of an already completed conversation.
            if not room["chatgpt_url"] and db.execute(
                "SELECT 1 FROM jobs WHERE user_id=? AND room_id=? "
                "AND status='completed' LIMIT 1", (uid, rid)
            ).fetchone():
                raise HTTPException(409, "기존 ChatGPT 대화 연결을 확인할 수 없습니다. 새 방에서 시험해 주십시오.")
            # A verified OpenAI identity is not automatically a Chrome
            # session. Refuse to execute the selected identity's prompt under
            # the unrelated shared GitHub worker's ChatGPT login.
            real_identity = db.execute(
                "SELECT id FROM hitel_verified_chatgpt_accounts "
                "WHERE browser_owner=? AND active=1 LIMIT 1",
                (_owner_hash(_owner(request)),)
            ).fetchone()
            selected_id = real_identity["id"] if real_identity else None
            if body.account_id != selected_id:
                raise HTTPException(409,
                    "요청 계정이 현재 선택된 ChatGPT 계정과 다릅니다. 계정 상태를 새로 확인한 뒤 전송하십시오.")
            if real_identity:
                # A verified OIDC email is only a TARGET. No unverified browser
                # profile may receive this request: the signed worker reads the
                # actual ChatGPT session and compares it before posting text.
                verified = db.execute(
                    "SELECT email,issuer FROM hitel_verified_chatgpt_accounts "
                    "WHERE id=? AND browser_owner=?",
                    (selected_id, _owner_hash(_owner(request))),
                ).fetchone()
                if not verified or verified["issuer"] != "https://auth.openai.com" or not verified["email"]:
                    raise HTTPException(409, "ChatGPT 계정 이메일이 검증되지 않았습니다.")
            # A private ChatGPT thread belongs to exactly one execution
            # identity. Guest and verified accounts are NEVER interchangeable;
            # selecting another account requires a separate HITEL room.
            room_account = selected_id or "__guest__"
            if (room["chatgpt_account_id"] is not None
                    and room["chatgpt_account_id"] != room_account):
                raise HTTPException(409,
                    "이 대화방은 다른 ChatGPT 계정에 연결되어 있습니다. "
                    "전환한 계정의 새 대화방을 만들어 주십시오.")
            if room["chatgpt_account_id"] is None:
                db.execute("UPDATE rooms SET chatgpt_account_id=? "
                           "WHERE id=? AND user_id=?", (room_account,rid,uid))
            jid = api_v1.store_job(db, uid, rid, "chat.send", text, [], account_id=selected_id)
            db.execute(
                "INSERT INTO messages VALUES(?,?,?,?,?,?,?)",
                ("msg_" + api_v1.new_id(), uid, rid, jid, "user", text, now)
            )
            db.execute("UPDATE rooms SET updated_at=? WHERE id=? AND user_id=?",
                       (now, rid, uid))
    from app import dispatch_next, web2api_device
    await dispatch_next()
    return {"jobId": jid, "queued": True,
            "workerConnected": web2api_device is not None,
            "sentToChatGPT": False,
            "fileToChatGPTSupported": False}


@router.get("/queue-status")
def queue_status(request:Request):
    # This endpoint reveals no user data; it is intended only for the
    # automatic GitHub worker wakeup check.
    if os.environ.get("PUBLIC_SMOKE_ONLY") != "1":raise HTTPException(404)
    with api_v1.connection() as db:
        n=db.execute(
            "SELECT count(*) FROM jobs WHERE status='queued' AND "
            "(user_id=? OR user_id LIKE 'usr_browser_%')",
            ("usr_public_web2api_probe_20261113",)).fetchone()[0]
    return {"pendingDemoWork":n>0}
