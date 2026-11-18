"""Pair an existing GitHub-registered ChatGPT Chrome session to a browser owner.

The browser owner receives a one-use challenge with same-origin cookie + CSRF.
Only a pinned GitHub Actions OIDC workflow may redeem it AFTER comparing the
actual HTTPS ChatGPT session email to the encrypted account registry. This is
NOT OpenAI OAuth and is labeled as an independent browser-session attestation.
No ChatGPT/Google cookies, passwords or Github bearer tokens cross to browser.
"""
from __future__ import annotations
import hashlib
import re
import secrets
from typing import Annotated
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel,Field

import api_v1
import web_chat
from gh_oidc import verify_pairing_identity

browser_router=APIRouter(prefix="/web/api/integrations/pairing",
    tags=["HITEL GitHub profile browser pairing"])
worker_router=APIRouter(prefix="/integrations/v1/registration",
    tags=["signed GitHub account enrollment"])
ISSUER="urn:hitel:chatgpt:github-actions-verified-browser"
CLIENT_ID="hitel-signed-github-chrome-account-1"
PAIR_ID=re.compile(r"^hitelpair_[A-Za-z0-9_-]{40,80}$")
ACTIVATION_MAX_MS=15*60*1000

with api_v1.connection() as db:
    db.execute("""CREATE TABLE IF NOT EXISTS hitel_account_pairing(
      digest TEXT PRIMARY KEY,
      owner_hash TEXT NOT NULL,
      user_id TEXT NOT NULL,
      created_at INTEGER NOT NULL,
      expires_at INTEGER NOT NULL,
      redeemed_at INTEGER
    )""")
    db.execute("""CREATE INDEX IF NOT EXISTS idx_hitel_pairing_owner
      ON hitel_account_pairing(owner_hash,created_at)""")


def _browser(request:Request,mutation=False):
    raw=web_chat._owner(request,mutation)
    owner=web_chat._owner_hash(raw)
    uid=web_chat._actor(request,mutation)
    with api_v1.connection() as db:
        ok=db.execute(
            "SELECT 1 FROM web_trial_profiles WHERE owner_hash=? "
            "AND user_id=? AND is_active=1 LIMIT 1",
            (owner,uid)).fetchone()
    if not ok:raise HTTPException(403,"Active HITEL browser profile required")
    return owner,uid


def _oidc(authorization: Annotated[str|None,Header()]=None):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401,"Signed GitHub Actions pairing workflow required")
    if not verify_pairing_identity(authorization[7:]):
        raise HTTPException(403,"Invalid GitHub Actions workflow identity")
    return True


class Redeem(BaseModel):
    pairing_code:str=Field(min_length=49,max_length=90)
    verified_session_email:str=Field(min_length=4,max_length=254)


@browser_router.post("/request",status_code=201)
def request_pairing(request:Request):
    owner,uid=_browser(request,mutation=True)
    now=api_v1.clock()
    secret="hitelpair_"+secrets.token_urlsafe(36)
    digest=hashlib.sha256(secret.encode()).hexdigest()
    with api_v1.connection() as db:
        count=db.execute("SELECT COUNT(*) FROM hitel_account_pairing "
           "WHERE owner_hash=? AND created_at>?",(owner,now-86400000)).fetchone()[0]
        if count>=5:raise HTTPException(429,"Daily pairing challenge limit reached")
        db.execute(
            "UPDATE hitel_account_pairing SET expires_at=? "
            "WHERE owner_hash=? AND redeemed_at IS NULL",
            (now,owner))
        db.execute(
            "INSERT INTO hitel_account_pairing VALUES(?,?,?,?,?,NULL)",
            (digest,owner,uid,now,now+ACTIVATION_MAX_MS))
    return {"pairing_code":secret,"expires_in_seconds":900,
            "instruction":"Run owner-controlled GitHub Actions pairing workflow; code shown once",
            "scope":"This proves registered Chrome login; it is not OpenAI OAuth"}


@browser_router.get("/status")
def pairing_status(request:Request):
    owner,uid=_browser(request)
    with api_v1.connection() as db:
        a=db.execute("""SELECT id,active,verified_at FROM
           hitel_verified_chatgpt_accounts
           WHERE browser_owner=? AND issuer=? AND client_id=?
           ORDER BY verified_at DESC LIMIT 2""",(owner,ISSUER,CLIENT_ID)).fetchall()
    return {"paired_accounts":[{"account_id":row["id"],
                 "active":bool(row["active"]),
                 "verified_at":row["verified_at"]}
                for row in a],
            "ready_to_issue_key":any(row["active"] for row in a),
            "method":"signed GitHub Actions + encrypted registry + live ChatGPT browser session"}


@worker_router.post("/pair",status_code=201)
def redeem_pairing(data:Redeem,verified=Depends(_oidc)):
    if not PAIR_ID.fullmatch(data.pairing_code):
        raise HTTPException(422,"Invalid pairing challenge")
    email=data.verified_session_email.strip().casefold()
    if len(email)>254 or not re.fullmatch(r"[^@\s]{1,100}@[^@\s]{1,180}",email):
        raise HTTPException(422,"Invalid verified session email")
    digest=hashlib.sha256(data.pairing_code.encode()).hexdigest()
    now=api_v1.clock()
    with api_v1.connection() as db:
        p=db.execute("SELECT * FROM hitel_account_pairing "
             "WHERE digest=? AND redeemed_at IS NULL AND expires_at>?",
             (digest,now)).fetchone()
        if not p:raise HTTPException(409,"Pairing challenge expired, reused, or unknown")
        active=db.execute("SELECT 1 FROM web_trial_profiles "
             "WHERE owner_hash=? AND user_id=? AND is_active=1",
             (p["owner_hash"],p["user_id"])).fetchone()
        if not active:raise HTTPException(409,"Browser owner switched profile")
        subject=hashlib.sha256(email.encode()).hexdigest()
        old=db.execute("""SELECT id FROM hitel_verified_chatgpt_accounts
           WHERE browser_owner=? AND issuer=? AND client_id=? AND subject=?
           LIMIT 1""",
           (p["owner_hash"],ISSUER,CLIENT_ID,subject)).fetchone()
        if not old:
            n=db.execute("SELECT COUNT(*) FROM hitel_verified_chatgpt_accounts "
                 "WHERE browser_owner=?",(p["owner_hash"],)).fetchone()[0]
            if n>=2:raise HTTPException(409,"Maximum two verified accounts per browser owner")
        aid=old["id"] if old else "oai_"+secrets.token_hex(16)
        db.execute("UPDATE hitel_verified_chatgpt_accounts SET active=0 "
                   "WHERE browser_owner=?",(p["owner_hash"],))
        db.execute("""INSERT INTO hitel_verified_chatgpt_accounts
           (id,browser_owner,issuer,client_id,subject,email,display_name,active,verified_at)
           VALUES(?,?,?,?,?,?,?,?,?)
           ON CONFLICT(id) DO UPDATE SET active=1,verified_at=excluded.verified_at,
           email=excluded.email""",
           (aid,p["owner_hash"],ISSUER,CLIENT_ID,subject,email,
            "GitHub Chrome 검증 계정",1,now))
        db.execute(
            "UPDATE hitel_account_pairing SET redeemed_at=? WHERE digest=? "
            "AND redeemed_at IS NULL",(now,digest))
    # Email never appears in the public status API, browser status or logs.
    return {"account_id":aid,"paired":True,
            "verification_method":"signed Github Actions and matching live ChatGPT session",
            "can_issue_browser_integration_key":True}
