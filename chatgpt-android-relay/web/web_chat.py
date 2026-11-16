"""Isolated browser-room and file trial (no console tokens or API keys).

Visitors receive private, signed, HttpOnly cookie sessions. This anonymous
public trial deliberately permits only FIXED harmless ChatGPT test prompts;
it never grants public strangers arbitrary access to the owner's ChatGPT
account, private rooms, files, or encrypted Chrome credentials.
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
MAX_UPLOAD_BYTES = 8 * 1024 * 1024
MAX_USER_BYTES = 24 * 1024 * 1024
MAX_TOTAL_PUBLIC_BYTES = 256 * 1024 * 1024
_storage_lock = threading.RLock()

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

def _csrf(raw: str):
    return hmac.new(SESSION_KEY, ("csrf:"+raw).encode(),hashlib.sha256).hexdigest()

def _secure_cookie(request: Request):
    # Railway terminates TLS at its gateway, so request.url.scheme may be http.
    # A browser-facing application on an HTTPS domain must use Secure.
    host = request.headers.get("host","")
    return host != "testserver" and not host.startswith(("localhost","127.0.0.1"))

def _actor(request: Request, mutate=False):
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
    return _uid(raw)

def _room(db,uid,rid):
    return api_v1.existing_room(db,rid,uid)

class RoomInput(BaseModel):
    title: str = Field(min_length=1,max_length=80)

class PresetInput(BaseModel):
    preset: str = Field(min_length=1,max_length=30)

@router.get("/bootstrap")
def bootstrap(request: Request, response: Response):
    if os.environ.get("PUBLIC_SMOKE_ONLY") != "1":
        raise HTTPException(404)
    raw=_unpack(request.cookies.get(COOKIE))
    created = raw is None
    if created:
        raw=secrets.token_hex(24)
    uid=_uid(raw)
    with api_v1.connection() as db:
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
            "presets":[{"id":k,"label":v} for k,v in PRESETS.items()],
            "limits":{"rooms":MAX_ROOMS,"fileMB":8}}

@router.get("/status")
def status(request: Request):
    _actor(request)
    # app globals imported lazily to avoid circular imports.
    from app import web2api_device
    return {"workerConnected":web2api_device is not None,
            "mode":"isolated_demo","freeTextSendSupported":False,
            "fileToChatGPTSupported":False}

@router.get("/rooms")
def list_rooms(request: Request):
    uid=_actor(request)
    with api_v1.connection() as db:
        rows=db.execute(
            "SELECT id,title,created_at,updated_at FROM rooms "
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
