"""One-shot, fixed-text ChatGPT relay E2E verification using a signed GitHub runner.

This is never an external customer's chat API: only a pinned main-branch
GitHub Actions workflow can create or read QA jobs. A successful result proves
the live server->worker->ChatGPT->server path, NOT account-bound API key issue.
"""
from __future__ import annotations

import re
import secrets
from typing import Annotated
from fastapi import APIRouter, Depends, Header, HTTPException

import api_v1
from gh_oidc import verify_bridge_qa_identity

router=APIRouter(prefix="/integrations/v1/qa/bridge",tags=["internal signed QA"])
PROBE_ID=re.compile(r"^job_[a-f0-9]{32}$")
QA_USER="usr_browser_hitel_signed_bridge_qa"

with api_v1.connection() as c:
    c.execute("""CREATE TABLE IF NOT EXISTS hitel_bridge_qa_jobs(
        job_id TEXT PRIMARY KEY,
        marker TEXT NOT NULL,
        created_at INTEGER NOT NULL
    )""")


def oidc(authorization: Annotated[str | None,Header()] = None):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401,"Signed GitHub Actions OIDC required")
    if not verify_bridge_qa_identity(authorization[7:]):
        raise HTTPException(403,"Untrusted GitHub Actions workflow identity")
    return True


@router.post("/once",status_code=201)
async def start_one_probe(verified=Depends(oidc)):
    """Generate a fixed synthetic prompt; caller cannot choose any text."""
    from app import web2api_device
    if web2api_device is None:
        # Keep probe fully honest: only enqueue after real WebSocket auth.
        raise HTTPException(503,"GitHub Chrome worker not connected")
    now=api_v1.clock()
    with api_v1.connection() as c:
        count=c.execute(
            "SELECT COUNT(*) FROM hitel_bridge_qa_jobs WHERE created_at>?",
            (now-86400000,)).fetchone()[0]
        if count>=3:
            raise HTTPException(429,"Three real bridge QA probes per day")
        running=c.execute(
            "SELECT 1 FROM jobs WHERE user_id=? AND status IN ('queued','running') LIMIT 1",
            (QA_USER,)).fetchone()
        if running:
            raise HTTPException(409,"Previous bridge QA job is incomplete")
        c.execute(
            "INSERT OR IGNORE INTO users(id,name,api_key_hash,created_at) VALUES(?,?,?,?)",
            (QA_USER,"Signed bridge QA only","disabled",now))
        room_id="room_"+api_v1.new_id()
        marker="HITEL_BRIDGE_QA_"+secrets.token_hex(8).upper()
        prompt="Connection QA only. Reply with EXACTLY the following token, with no other text: "+marker
        c.execute(
            "INSERT INTO rooms (id,user_id,title,android_state,created_at,updated_at)"
            " VALUES(?,?,?,?,?,?)",
            (room_id,QA_USER,"One-shot signed API bridge QA","uncreated",now,now))
        job_id=api_v1.store_job(c,QA_USER,room_id,"chat.send",prompt,[])
        c.execute(
            "INSERT INTO hitel_bridge_qa_jobs(job_id,marker,created_at) VALUES(?,?,?)",
            (job_id,marker,now))
    if api_v1.on_new_job:
        await api_v1.on_new_job()
    return {"job_id":job_id,"status":"queued","expected_marker":marker,
            "scope":"signed workflow QA only; no customer key issued"}


@router.get("/jobs/{job_id}")
def get_qa_result(job_id: str,verified=Depends(oidc)):
    if not PROBE_ID.fullmatch(job_id):
        raise HTTPException(404,"Unknown bridge job")
    with api_v1.connection() as c:
        p=c.execute("SELECT marker FROM hitel_bridge_qa_jobs WHERE job_id=?",
                    (job_id,)).fetchone()
        r=c.execute("SELECT status,stage,error,result_text,room_id FROM jobs "
                    "WHERE id=? AND user_id=?",(job_id,QA_USER)).fetchone()
        if p is None or r is None:
            raise HTTPException(404,"Unknown bridge job")
        room=c.execute("SELECT chatgpt_url FROM rooms WHERE id=? AND user_id=?",
                       (r["room_id"],QA_USER)).fetchone()
    answer_matches=(r["status"]=="completed"
                    and isinstance(r["result_text"],str)
                    and r["result_text"].strip()==p["marker"])
    url_verified=bool(room and isinstance(room["chatgpt_url"],str)
                      and room["chatgpt_url"].startswith("https://chatgpt.com/c/"))
    return {"job_id":job_id,"status":r["status"],"stage":r["stage"],
            "reply_matches_expected_marker":answer_matches,
            "conversation_url_verified":url_verified,
            "end_to_end_pass":bool(answer_matches and url_verified),
            "error_type":(r["error"] or "")[:120] if r["status"]=="failed" else None,
            "scope":"signed QA only; not general integration account-bound chat"}
