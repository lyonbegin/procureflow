"""Verified OpenAI account links for HITEL browser sessions.

This intentionally does NOT reuse or expose the GitHub Chrome worker's cookies,
nor does an OpenID identity grant authorization to automate ChatGPT web. Official
Sign in with ChatGPT on remotely hosted websites requires an approved OAuth client.
"""
import asyncio
import base64
import hashlib
import os
import secrets
import time
from urllib.parse import urlencode, urlsplit

import httpx
import jwt
from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
import api_v1
import web_chat

router = APIRouter(prefix="/web/api/chatgpt", tags=["official-chatgpt-identity"])
FLOW_COOKIE = "hitel_chatgpt_oauth_flow"
ISSUER = "https://auth.openai.com"
DISCOVERY = ISSUER + "/.well-known/openid-configuration"
CLIENT_ID = (os.getenv("OPENAI_SIWC_CLIENT_ID") or "").strip()
CLIENT_SECRET = (os.getenv("OPENAI_SIWC_CLIENT_SECRET") or "").strip()
REDIRECT_URI = (os.getenv("OPENAI_SIWC_REDIRECT_URI") or "").strip()
PROD_CALLBACK = ("https://chatgpt-relay-web-production.up.railway.app"
                 "/web/api/chatgpt/callback")
MAX_LINKS = 2

with api_v1.connection() as _db:
    _db.execute("""CREATE TABLE IF NOT EXISTS hitel_verified_chatgpt_accounts(
        id TEXT PRIMARY KEY,
        browser_owner TEXT NOT NULL,
        issuer TEXT NOT NULL,
        client_id TEXT NOT NULL,
        subject TEXT NOT NULL,
        email TEXT,
        display_name TEXT,
        active INTEGER NOT NULL DEFAULT 0,
        verified_at INTEGER NOT NULL,
        UNIQUE(browser_owner,issuer,client_id,subject)
    )""")
    _db.execute("""CREATE TABLE IF NOT EXISTS hitel_chatgpt_oauth_flows(
        state_digest TEXT PRIMARY KEY,
        browser_owner TEXT NOT NULL,
        verifier TEXT NOT NULL,
        nonce TEXT NOT NULL,
        flow_digest TEXT NOT NULL,
        expires_at INTEGER NOT NULL
    )""")
    _db.execute("CREATE INDEX IF NOT EXISTS idx_hitel_chatgpt_owner ON hitel_verified_chatgpt_accounts(browser_owner)")

def _enabled():
    return (bool(CLIENT_ID and REDIRECT_URI == PROD_CALLBACK
                 and CLIENT_ID.startswith("oaiapp_")))

def _owner(request: Request, modify=False):
    raw = web_chat._owner(request, modify)
    return web_chat._owner_hash(raw)

def _url_safe_bytes(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")

def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

async def _oidc():
    async with httpx.AsyncClient(timeout=12) as client:
        response = await client.get(DISCOVERY)
        response.raise_for_status()
        config = response.json()
    if config.get("issuer") != ISSUER:
        raise HTTPException(503,"OpenAI 인증 제공자 식별을 확인할 수 없습니다.")
    for key in ("authorization_endpoint","token_endpoint","jwks_uri"):
        u = urlsplit(config.get(key) or "")
        if u.scheme != "https" or u.hostname != "auth.openai.com":
            raise HTTPException(503,"OpenAI 인증 제공자 주소가 유효하지 않습니다.")
    return config

def _public_account(row):
    return {"id":row["id"],"name":row["display_name"] or "ChatGPT 계정",
            "email":row["email"],"active":bool(row["active"]),
            "identityVerified":True,"canRunWeb2APIAsThisAccount":False}

@router.get("/accounts")
def list_accounts(request: Request):
    owner = _owner(request)
    with api_v1.connection() as db:
        records = db.execute(
            "SELECT id,display_name,email,active FROM hitel_verified_chatgpt_accounts "
            "WHERE browser_owner=? ORDER BY active DESC,verified_at DESC", (owner,)
        ).fetchall()
    return {"accounts":[_public_account(r) for r in records],
            "connected":bool(records),"oauthAvailable":_enabled(),
            "officialLoginRequired":not bool(records),
            "executionAccountBound":False,
            "provider":"OpenAI verified OIDC; not Google account registration",
            "message":("공식 ChatGPT 인증을 시작할 수 있습니다."
                       if _enabled() else
                       "이 서버에는 승인된 ChatGPT 로그인 클라이언트가 아직 설정되지 않았습니다.")}

@router.get("/login")
async def start_login(request: Request):
    owner = _owner(request)
    if not _enabled():
        raise HTTPException(503,
            "HITEL에 승인된 Sign in with ChatGPT OAuth 클라이언트가 설정되지 않았습니다. "
            "기존 ChatGPT 로그인 쿠키·암호를 이 사이트에 입력하지 마십시오.")
    config = await _oidc()
    state = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    nonce = secrets.token_urlsafe(32)
    flow = secrets.token_urlsafe(32)
    now = int(time.time())
    with api_v1.connection() as db:
        db.execute("DELETE FROM hitel_chatgpt_oauth_flows WHERE expires_at<?",(now,))
        db.execute(
            "INSERT INTO hitel_chatgpt_oauth_flows VALUES(?,?,?,?,?,?)",
            (_digest(state),owner,verifier,nonce,_digest(flow),now+600)
        )
    query = urlencode({
        "client_id":CLIENT_ID, "response_type":"code",
        "redirect_uri":REDIRECT_URI, "scope":"openid profile email",
        "state":state,"nonce":nonce,
        "code_challenge":_url_safe_bytes(hashlib.sha256(verifier.encode()).digest()),
        "code_challenge_method":"S256"
    })
    result = RedirectResponse(config["authorization_endpoint"]+"?"+query,status_code=302)
    result.set_cookie(FLOW_COOKIE,flow,httponly=True,secure=True,
                      samesite="lax",max_age=600,path="/web/api/chatgpt")
    result.headers["Cache-Control"]="no-store"
    return result

@router.get("/callback")
async def complete_login(request: Request, code: str = "", state: str = "", error: str = ""):
    # Cross-site OpenAI -> HITEL redirects cannot carry the Strict browser
    # session cookie. Bind callback to the short-lived SameSite=Lax OAuth
    # transaction cookie and the one-time server-side state instead.
    flow = request.cookies.get(FLOW_COOKIE) or ""
    if not state or not flow or len(state)>256 or len(flow)>256:
        raise HTTPException(403,"ChatGPT 로그인 상태 확인에 실패했습니다.")
    with api_v1.connection() as db:
        pending = db.execute(
            "SELECT * FROM hitel_chatgpt_oauth_flows WHERE state_digest=?",(_digest(state),)
        ).fetchone()
        # Atomically consume one-time transaction even if downstream exchange fails.
        db.execute("DELETE FROM hitel_chatgpt_oauth_flows WHERE state_digest=?",(_digest(state),))
    if (not pending or pending["expires_at"] < int(time.time())
            or not secrets.compare_digest(pending["flow_digest"],_digest(flow))):
        raise HTTPException(403,"ChatGPT 로그인 요청이 만료되었거나 다른 브라우저의 요청입니다.")
    owner = pending["browser_owner"]
    if error:
        return RedirectResponse("/?chatgpt-auth=cancelled",status_code=303)
    if not code or not _enabled():
        raise HTTPException(403,"승인된 OpenAI 클라이언트 및 인증 코드가 필요합니다.")
    config = await _oidc()
    data = {"grant_type":"authorization_code","client_id":CLIENT_ID,
            "code":code,"redirect_uri":REDIRECT_URI,
            "code_verifier":pending["verifier"]}
    if CLIENT_SECRET:
        data["client_secret"] = CLIENT_SECRET
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(config["token_endpoint"],data=data)
        response.raise_for_status()
        token=response.json().get("id_token")
    if not token:
        raise HTTPException(502,"OpenAI 인증 응답에 신원 확인 토큰이 없습니다.")

    def validate():
        key=jwt.PyJWKClient(config["jwks_uri"]).get_signing_key_from_jwt(token)
        return jwt.decode(token,key.key,algorithms=["RS256"],audience=CLIENT_ID,
                          issuer=ISSUER,options={"require":["exp","iat","iss","aud","sub"]})
    claims=await asyncio.to_thread(validate)
    if not secrets.compare_digest(str(claims.get("nonce") or ""),pending["nonce"]):
        raise HTTPException(403,"OpenAI 인증 nonce 확인에 실패했습니다.")
    subject=claims["sub"]
    name=str(claims.get("name") or "ChatGPT 계정")[:100]
    email=str(claims.get("email") or "")[:254] if claims.get("email_verified") is True else ""
    now=int(time.time()*1000)
    with web_chat._storage_lock:
        with api_v1.connection() as db:
            old=db.execute(
                "SELECT id FROM hitel_verified_chatgpt_accounts "
                "WHERE browser_owner=? AND issuer=? AND client_id=? AND subject=?",
                (owner,ISSUER,CLIENT_ID,subject)
            ).fetchone()
            if not old:
                n=db.execute("SELECT count(*) FROM hitel_verified_chatgpt_accounts "
                             "WHERE browser_owner=?",(owner,)).fetchone()[0]
                if n>=MAX_LINKS:
                    raise HTTPException(409,"최대 2개의 ChatGPT 인증 계정을 연결할 수 있습니다.")
            account_id=old["id"] if old else "oai_"+secrets.token_hex(16)
            db.execute("UPDATE hitel_verified_chatgpt_accounts SET active=0 WHERE browser_owner=?",(owner,))
            db.execute(
                "INSERT INTO hitel_verified_chatgpt_accounts "
                "(id,browser_owner,issuer,client_id,subject,email,display_name,active,verified_at) "
                "VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET "
                "email=excluded.email,display_name=excluded.display_name,"
                "active=1,verified_at=excluded.verified_at",
                (account_id,owner,ISSUER,CLIENT_ID,subject,email,name,1,now)
            )
    result=RedirectResponse("/?chatgpt-auth=verified",status_code=303)
    result.delete_cookie(FLOW_COOKIE,path="/web/api/chatgpt",secure=True,samesite="lax")
    result.headers["Cache-Control"]="no-store"
    return result

@router.post("/accounts/{account_id}/select")
def choose_account(account_id: str, request: Request):
    owner=_owner(request,True)
    with web_chat._storage_lock:
        with api_v1.connection() as db:
            row=db.execute(
                "SELECT id FROM hitel_verified_chatgpt_accounts "
                "WHERE browser_owner=? AND id=?", (owner,account_id)
            ).fetchone()
            if not row:raise HTTPException(404,"인증된 ChatGPT 계정이 없습니다.")
            db.execute("UPDATE hitel_verified_chatgpt_accounts SET active=0 WHERE browser_owner=?",(owner,))
            db.execute("UPDATE hitel_verified_chatgpt_accounts SET active=1 WHERE id=? AND browser_owner=?",
                       (account_id,owner))
    return {"selected":True,"canRunWeb2APIAsThisAccount":False}

@router.delete("/accounts/{account_id}")
def unlink_account(account_id: str, request: Request):
    owner=_owner(request,True)
    with web_chat._storage_lock:
        with api_v1.connection() as db:
            n=db.execute("DELETE FROM hitel_verified_chatgpt_accounts "
                         "WHERE id=? AND browser_owner=?", (account_id,owner)).rowcount
            if n<1:raise HTTPException(404,"인증된 ChatGPT 계정이 없습니다.")
            active=db.execute("SELECT id FROM hitel_verified_chatgpt_accounts "
                              "WHERE browser_owner=? AND active=1",(owner,)).fetchone()
            if not active:
                db.execute("UPDATE hitel_verified_chatgpt_accounts SET active=1 "
                           "WHERE id=(SELECT id FROM hitel_verified_chatgpt_accounts "
                           "WHERE browser_owner=? ORDER BY verified_at DESC LIMIT 1)",(owner,))
    return {"disconnected":True,"chatgptAccountDeleted":False}
