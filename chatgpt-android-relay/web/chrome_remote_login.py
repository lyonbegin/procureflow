"""Privileged HITEL-to-GitHub-Chrome login control.

Google credentials are ECDH(P-256)+AES-GCM encrypted inside the visitor's browser
directly to the ephemeral GitHub worker public key. Railway only forwards the
ciphertext. No passwords/OTPs are persisted, logged, or passed as URL arguments.

The public HITEL test page is anonymous, so modifying the shared remote Chrome
requires unlocking with the existing server management secret first. Without
that gate an arbitrary visitor could sign out the owner's ChatGPT account.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
import secrets
import threading
import time
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
import api_v1
import web_chat

router=APIRouter(prefix="/web/api/chrome-login",tags=["privileged-chrome-login"])
_lock=threading.RLock()
_worker=None
_worker_key=None
_worker_generation=0
_owner_access=None
_owner_access_until=0.0
_bootstrap_until=0.0
_attempts: dict[str,dict[str,Any]]={}
_MAX_AGE=10*60
SESSION_ISSUER="https://chatgpt.com/session"
SESSION_CLIENT="hitel-github-chrome-verified"


def _timestamp() -> float:
    return time.monotonic()


def _owner(request:Request,modify:bool=False) -> str:
    return web_chat._owner_hash(web_chat._owner(request,modify))


def _admin(request:Request,modify:bool=False) -> str:
    owner=_owner(request,modify)
    with _lock:
        if _owner_access != owner or _owner_access_until <= _timestamp():
            raise HTTPException(403,"먼저 HITEL 관리 권한을 확인하십시오.")
    return owner


def _expire() -> None:
    now=_timestamp()
    for key in tuple(_attempts):
        if _attempts[key]["created"]+_MAX_AGE<now:
            del _attempts[key]


def wants_worker() -> bool:
    with _lock:
        return _bootstrap_until > _timestamp()


def worker_ready() -> bool:
    with _lock:
        return _worker is not None and _worker_key is not None


def register_worker(ws,key_b64:str) -> None:
    """Called only after actual signed GitHub OIDC authentication in app.py."""
    raw=base64.b64decode(key_b64,validate=True)
    if len(raw)!=65 or raw[0]!=4:
        raise ValueError("INVALID_WORKER_ECDH_PUBLIC_KEY")
    # Cryptographically validate the curve point, not just its length.
    from cryptography.hazmat.primitives.asymmetric import ec
    ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(),raw)
    global _worker,_worker_key,_worker_generation,_bootstrap_until
    with _lock:
        _worker=ws
        _worker_key=key_b64
        _worker_generation+=1
        _bootstrap_until=0.0
        for attempt in _attempts.values():
            if attempt["status"] in ("sealed","running","requires_verification"):
                attempt["status"]="failed"
                attempt["reason"]="CHROME_WORKER_REPLACED"


def unregister_worker(ws) -> None:
    global _worker,_worker_key,_worker_generation
    with _lock:
        if _worker is not ws:
            return
        _worker=None
        _worker_key=None
        _worker_generation+=1
        for attempt in _attempts.values():
            if attempt["status"] in ("sealed","running","requires_verification"):
                attempt["status"]="failed"
                attempt["reason"]="CHROME_WORKER_DISCONNECTED"


class Unlock(BaseModel):
    management_secret:str=Field(min_length=1,max_length=512)


@router.post("/unlock")
def unlock(body:Unlock,request:Request):
    owner=_owner(request,True)
    expected=os.environ.get("CONSOLE_TOKEN","")
    if len(expected)<24 or not hmac.compare_digest(
        body.management_secret.encode(),expected.encode()):
        raise HTTPException(403,"HITEL 관리 권한을 확인할 수 없습니다.")
    global _owner_access,_owner_access_until
    with _lock:
        if (_owner_access is not None and _owner_access!=owner
                and _owner_access_until>_timestamp()):
            raise HTTPException(423,"다른 관리자 브라우저에서 Chrome 로그인을 진행하고 있습니다.")
        _owner_access=owner
        _owner_access_until=_timestamp()+15*60
    return {"authorized":True,"expiresInSeconds":900}


@router.get("/challenge")
def challenge(request:Request):
    owner=_admin(request)
    global _bootstrap_until
    with _lock:
        _expire()
        if _worker is None or _worker_key is None:
            _bootstrap_until=_timestamp()+5*60
            return {"ready":False,"workerStartupRequested":True}
        if any(a["owner"]==owner and a["status"] in
               ("sealed","running","requires_verification") for a in _attempts.values()):
            raise HTTPException(409,"이미 로그인 요청을 진행하고 있습니다.")
        nonce=secrets.token_urlsafe(24)
        _attempts[nonce]={
            "owner":owner,"created":_timestamp(),"generation":_worker_generation,
            "status":"challenge","reason":None,"account_id":None,"email":None,
        }
        return {"ready":True,"requestId":nonce,
                "workerPublicKey":_worker_key,"algorithm":"ECDH-P256-AES-256-GCM"}


class Envelope(BaseModel):
    request_id:str=Field(min_length=16,max_length=80)
    client_public_key:str=Field(min_length=70,max_length=256)
    nonce:str=Field(min_length=12,max_length=80)
    ciphertext:str=Field(min_length=24,max_length=16000)


@router.post("/submit")
async def submit(body:Envelope,request:Request):
    owner=_admin(request,True)
    with _lock:
        _expire()
        attempt=_attempts.get(body.request_id)
        if (attempt is None or attempt["owner"]!=owner or
                attempt["status"]!="challenge" or
                attempt["generation"]!=_worker_generation or _worker is None):
            raise HTTPException(409,"Chrome 로그인 요청이 만료되었거나 작업자가 변경되었습니다.")
        if len(body.ciphertext)>16000:
            raise HTTPException(422,"암호화한 요청이 너무 큽니다.")
        attempt["status"]="sealed"
        worker=_worker
        packet={
            "type":"auth.login.request","request_id":body.request_id,
            "client_public_key":body.client_public_key,
            "nonce":body.nonce,"ciphertext":body.ciphertext,
        }
    try:
        await worker.send_json(packet)
    except Exception:
        with _lock:
            attempt["status"]="failed"
            attempt["reason"]="CHROME_WORKER_DISCONNECTED"
        raise HTTPException(503,"Chrome 작업자 연결이 종료되었습니다.")
    return {"accepted":True,"requestId":body.request_id,"status":"sealed"}


@router.get("/status/{request_id}")
def status(request_id:str,request:Request):
    owner=_admin(request)
    with _lock:
        _expire()
        attempt=_attempts.get(request_id)
        if not attempt or attempt["owner"]!=owner:
            raise HTTPException(404,"로그인 요청을 찾을 수 없습니다.")
        return {"status":attempt["status"],"reason":attempt["reason"],
                "accountId":attempt["account_id"],"verifiedEmail":attempt["email"]}


@router.post("/recheck/{request_id}")
async def recheck(request_id:str,request:Request):
    owner=_admin(request,True)
    with _lock:
        attempt=_attempts.get(request_id)
        if not attempt or attempt["owner"]!=owner:
            raise HTTPException(404)
        if attempt["status"]!="requires_verification" or _worker is None:
            raise HTTPException(409,"추가 인증을 확인할 수 있는 상태가 아닙니다.")
        if attempt["generation"]!=_worker_generation:
            raise HTTPException(409,"Chrome 실행 세션이 변경되었습니다.")
        worker=_worker
    await worker.send_json({"type":"auth.login.recheck","request_id":request_id})
    return {"requested":True}


def _verify_result_email(email:object) -> str:
    if not isinstance(email,str) or len(email)>254:
        raise ValueError("LOGIN_EMAIL_INVALID")
    value=email.strip().casefold()
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+",value):
        raise ValueError("LOGIN_EMAIL_INVALID")
    return value


def receive_result(ws,msg:dict):
    """Only signed GitHub Chrome worker calls this from authenticated socket."""
    request_id=msg.get("request_id")
    if not isinstance(request_id,str):
        return
    status=msg.get("status")
    allowed={"running","verified","failed","requires_verification"}
    if status not in allowed:
        return
    with _lock:
        _expire()
        attempt=_attempts.get(request_id)
        if not attempt or _worker is not ws or attempt["generation"]!=_worker_generation:
            return
        if attempt["status"] in ("verified","failed"):
            return
        if status=="verified":
            # The worker independently read the real ChatGPT HTTPS session
            # after the Google/OpenAI website completed its login flow.
            try:
                email=_verify_result_email(msg.get("verified_email"))
            except ValueError:
                attempt["status"]="failed"
                attempt["reason"]="LIVE_CHATGPT_EMAIL_NOT_VERIFIED"
                return
            owner=attempt["owner"]
            now=api_v1.clock()
            with web_chat._storage_lock:
                with api_v1.connection() as c:
                    existing=c.execute(
                        "SELECT id FROM hitel_verified_chatgpt_accounts "
                        "WHERE browser_owner=? AND issuer=? AND client_id=? AND subject=?",
                        (owner,SESSION_ISSUER,SESSION_CLIENT,
                         hashlib.sha256(email.encode()).hexdigest())
                    ).fetchone()
                    if not existing:
                        count=c.execute("SELECT count(*) FROM hitel_verified_chatgpt_accounts "
                                        "WHERE browser_owner=?",(owner,)).fetchone()[0]
                        if count>=2:
                            attempt["status"]="failed"
                            attempt["reason"]="ACCOUNT_LIMIT_REACHED"
                            return
                    aid=existing["id"] if existing else "oai_"+secrets.token_hex(16)
                    c.execute("UPDATE hitel_verified_chatgpt_accounts SET active=0 "
                              "WHERE browser_owner=?",(owner,))
                    c.execute(
                        "INSERT INTO hitel_verified_chatgpt_accounts "
                        "(id,browser_owner,issuer,client_id,subject,email,display_name,active,verified_at) "
                        "VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET "
                        "email=excluded.email,display_name=excluded.display_name,"
                        "active=1,verified_at=excluded.verified_at",
                        (aid,owner,SESSION_ISSUER,SESSION_CLIENT,
                         hashlib.sha256(email.encode()).hexdigest(),
                         email,email,1,now),
                    )
            attempt["account_id"]=aid
            attempt["email"]=email
            attempt["status"]="verified"
            attempt["reason"]=None
        else:
            attempt["status"]=status
            code=msg.get("reason")
            attempt["reason"]=(code if code in {
                "GOOGLE_ADDITIONAL_VERIFICATION_REQUIRED",
                "GOOGLE_LOGIN_PAGE_UNAVAILABLE",
                "GOOGLE_LOGIN_NOT_AUTHENTICATED",
                "GOOGLE_LOGIN_WRONG_ACCOUNT",
                "GOOGLE_CREDENTIALS_REJECTED",
                "CHROME_LOGIN_UNEXPECTED",
            } else "CHROME_LOGIN_UNVERIFIED") if status!="running" else None
