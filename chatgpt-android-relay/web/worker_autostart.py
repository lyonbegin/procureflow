"""Event-driven, authenticated GitHub Chrome worker autostart.

A verified HITEL Bearer-chat request queues an account-pinned job. When Chrome
is unavailable the Railway process uses GitHub's official workflow_dispatch API,
never an unauthenticated public workflow trigger. A SQLite lease on the mounted
Railway volume prevents parallel HTTP requests/restart monitors from launching
duplicate runs. A short local supervisor retries failures with backoff and
recovers queued jobs after Railway restarts. It does NOT re-send any job that
was already delivered to ChatGPT.

Provision exactly one credentials path in the Railway SERVICE environment:
- Preferred: HITEL_GITHUB_APP_ID, HITEL_GITHUB_APP_INSTALLATION_ID,
  HITEL_GITHUB_APP_PRIVATE_KEY, with Actions:write on lyonbegin/procureflow
- Alternative: HITEL_GITHUB_ACTIONS_TOKEN, scoped Actions:write to that repo

Never print tokens or include tokens in responses. No GitHub scheduled actions.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sqlite3
import time
import urllib.error
import urllib.request

import jwt

import api_v1

OWNER="lyonbegin"
REPO="procureflow"
WORKFLOW="hitel-integration-bridge-live-qa.yml"
API="https://api.github.com"
MAX_HTTP_SECONDS=16
LEASE_MS=120_000
DISPATCH_COOLDOWN_MS=300_000
RECONNECT_GRACE_MS=100_000

with api_v1.connection() as _conn:
    _conn.execute("""CREATE TABLE IF NOT EXISTS hitel_chrome_autostart (
      id INTEGER PRIMARY KEY CHECK (id=1),
      status TEXT NOT NULL DEFAULT 'idle',
      dispatch_count INTEGER NOT NULL DEFAULT 0,
      failures INTEGER NOT NULL DEFAULT 0,
      next_attempt_at INTEGER NOT NULL DEFAULT 0,
      lock_until INTEGER NOT NULL DEFAULT 0,
      last_attempt_at INTEGER,
      last_connected_at INTEGER,
      last_failure TEXT
    )""")
    _conn.execute("""INSERT OR IGNORE INTO hitel_chrome_autostart
      (id,status) VALUES(1,'idle')""")


def configured() -> bool:
    app_vars=all(os.environ.get(k) for k in (
        "HITEL_GITHUB_APP_ID",
        "HITEL_GITHUB_APP_INSTALLATION_ID",
        "HITEL_GITHUB_APP_PRIVATE_KEY",
    ))
    token=bool(os.environ.get("HITEL_GITHUB_ACTIONS_TOKEN"))
    return bool(app_vars or token)


def _request(path: str, token: str, *, payload: dict | None=None,
             method: str="POST") -> tuple[int,dict]:
    if not path.startswith("/") or "//" in path or "?" in path:
        raise ValueError("INVALID_FIXED_GITHUB_PATH")
    data=json.dumps(payload,separators=(",",":")).encode() if payload is not None else None
    req=urllib.request.Request(API+path,data=data,method=method,headers={
        "Authorization":"Bearer "+token,
        "Accept":"application/vnd.github+json",
        "X-GitHub-Api-Version":"2022-11-28",
        "Content-Type":"application/json",
        "User-Agent":"HITEL-Chrome-Worker-Autostart",
    })
    try:
        with urllib.request.urlopen(req,timeout=MAX_HTTP_SECONDS) as response:
            raw=response.read(4096)
            try:body=json.loads(raw) if raw else {}
            except (ValueError,UnicodeDecodeError):body={}
            return response.status,body
    except urllib.error.HTTPError as exc:
        # Never read GitHub's response body: it may contain sensitive metadata.
        raise RuntimeError("GITHUB_HTTP_"+str(exc.code)) from None
    except (urllib.error.URLError,TimeoutError,OSError):
        raise RuntimeError("GITHUB_NETWORK_UNAVAILABLE") from None


def _installation_token() -> str:
    app_id=os.environ["HITEL_GITHUB_APP_ID"].strip()
    install=os.environ["HITEL_GITHUB_APP_INSTALLATION_ID"].strip()
    pem=os.environ["HITEL_GITHUB_APP_PRIVATE_KEY"].replace("\\n","\n")
    if not re.fullmatch(r"[0-9]{1,24}",app_id) or not re.fullmatch(r"[0-9]{1,24}",install):
        raise RuntimeError("GITHUB_APP_ID_INVALID")
    now=int(time.time())
    app_jwt=jwt.encode({"iat":now-60,"exp":now+540,"iss":app_id},
                       pem,algorithm="RS256")
    status,data=_request("/app/installations/"+install+"/access_tokens",
                         app_jwt,payload={"repositories":[REPO],
                                         "permissions":{"actions":"write"}})
    token=data.get("token")
    if status!=201 or not isinstance(token,str) or len(token)<20:
        raise RuntimeError("GITHUB_APP_TOKEN_NOT_ISSUED")
    return token


def _dispatch_once(token: str) -> None:
    code,_=_request(
        "/repos/"+OWNER+"/"+REPO+"/actions/workflows/"+WORKFLOW+"/dispatches",
        token,payload={"ref":"main","inputs":{
            "operation":"worker_only","run_minutes":"240","pairing_code":""
        }})
    # GitHub's 2026-03-10 API docs specify 200 with run metadata;
    # older workflow_dispatch responses can still be 204 No Content.
    if code not in (200,201,204):
        raise RuntimeError("GITHUB_DISPATCH_UNCONFIRMED")


def _dispatch_with_fallback() -> str:
    """Try GitHub App, then a separately configured fine-grained token."""
    errors=[]
    if all(os.environ.get(k) for k in (
        "HITEL_GITHUB_APP_ID","HITEL_GITHUB_APP_INSTALLATION_ID",
        "HITEL_GITHUB_APP_PRIVATE_KEY",
    )):
        try:
            _dispatch_once(_installation_token())
            return "github_app"
        except Exception as exc:
            errors.append(type(exc).__name__ if not isinstance(exc,RuntimeError)
                          else str(exc)[:55])
    token=os.environ.get("HITEL_GITHUB_ACTIONS_TOKEN","").strip()
    if token:
        try:
            _dispatch_once(token)
            return "fine_grained_token"
        except Exception as exc:
            errors.append(type(exc).__name__ if not isinstance(exc,RuntimeError)
                          else str(exc)[:55])
    raise RuntimeError(errors[-1] if errors else "NO_DISPATCH_CREDENTIAL_CONFIGURED")


def pending_count() -> int:
    """Count both verified private and explicitly isolated public-link jobs."""
    public_uid="usr_browser_hitel_public_link"
    with api_v1.connection() as c:
        if os.environ.get("PUBLIC_SMOKE_ONLY","")=="1":
            row=c.execute(
                "SELECT COUNT(*) FROM jobs WHERE status='queued' AND "
                "((account_id IS NOT NULL AND user_id LIKE 'usr_browser_%') "
                "OR (user_id=? AND account_id IS NULL))",
                (public_uid,)
            ).fetchone()
        else:
            row=c.execute(
                "SELECT COUNT(*) FROM jobs WHERE status='queued' AND "
                "(account_id IS NOT NULL OR (user_id=? AND account_id IS NULL))",
                (public_uid,)
            ).fetchone()
        return int(row[0])


def read_status(*,connected:bool) -> dict:
    with api_v1.connection() as c:
        row=dict(c.execute("SELECT * FROM hitel_chrome_autostart WHERE id=1").fetchone())
    now=api_v1.clock()
    return {
        "worker_connected":bool(connected),
        "auto_start_supported":True,
        "auto_start_configured":configured(),
        "launch_status":"connected" if connected else row["status"],
        "last_failure_class":row["last_failure"],
        "launch_attempts":row["dispatch_count"],
        "next_attempt_delay_seconds":max(0,(row["next_attempt_at"]-now)//1000),
        "pending_verified_chat_jobs":pending_count(),
        "trigger":"authenticated chat submission or local recovery supervisor",
        "github_workflow":"lyonbegin/procureflow/"+WORKFLOW,
        "schedule_enabled":False,
    }


def worker_connected() -> None:
    now=api_v1.clock()
    with api_v1.connection() as c:
        c.execute("""UPDATE hitel_chrome_autostart SET status='connected',
                     failures=0,lock_until=0,last_failure=NULL,
                     next_attempt_at=?,
                     last_connected_at=? WHERE id=1""",
                  (now+RECONNECT_GRACE_MS,now))


def worker_disconnected() -> None:
    with api_v1.connection() as c:
        c.execute("""UPDATE hitel_chrome_autostart SET status='offline'
                     WHERE id=1""")


async def ensure_started(*,reason:str="pending_verified_chat",connected:bool=False) -> dict:
    """Trigger at most one workflow dispatch per durable lease/cooldown window.

    Only callers that have verified account-bound pending jobs can launch.
    Never claim that a GitHub 204 means Chrome actually connected.
    """
    if connected:
        return {"status":"connected"}
    if not configured():
        return {"status":"not_configured"}
    if pending_count()==0:
        return {"status":"nothing_to_process"}
    now=api_v1.clock()
    with api_v1.connection() as c:
        c.execute("BEGIN IMMEDIATE")
        row=c.execute("SELECT * FROM hitel_chrome_autostart WHERE id=1").fetchone()
        if row["lock_until"]>now or row["next_attempt_at"]>now:
            return {"status":"awaiting_start_or_retry"}
        c.execute("""UPDATE hitel_chrome_autostart
                     SET status='starting', lock_until=?,
                         last_attempt_at=? WHERE id=1""",
                  (now+LEASE_MS,now))
    try:
        method=await asyncio.to_thread(_dispatch_with_fallback)
    except Exception as exc:
        # Two attempts can race across a process restart; the SQL lease is
        # still the authority. Never leak token or exception URL.
        classification=str(exc)[:55] if isinstance(exc,RuntimeError) else type(exc).__name__
        now=api_v1.clock()
        with api_v1.connection() as c:
            old=c.execute("SELECT failures FROM hitel_chrome_autostart WHERE id=1").fetchone()
            failures=int(old[0])+1
            delay=min(300_000,15_000*(2**min(failures-1,5)))
            c.execute("""UPDATE hitel_chrome_autostart
                         SET status='dispatch_failed',failures=?,
                             next_attempt_at=?,lock_until=0,last_failure=?
                         WHERE id=1""",
                      (failures,now+delay,classification))
        print("[hitel-worker-autostart] failed class="+classification,flush=True)
        return {"status":"dispatch_failed","retry_in_seconds":delay//1000}
    else:
        now=api_v1.clock()
        with api_v1.connection() as c:
            c.execute("""UPDATE hitel_chrome_autostart
                         SET status='requested',dispatch_count=dispatch_count+1,
                             failures=0,last_failure=NULL,
                             next_attempt_at=?,lock_until=0 WHERE id=1""",
                      (now+DISPATCH_COOLDOWN_MS,))
        print("[hitel-worker-autostart] GitHub launch accepted method="+method,flush=True)
        return {"status":"launch_requested","mode":method}


async def monitor_connected(*,check_connected,close_stale,interval:int=15):
    """Local Railway supervisor, not a GitHub Actions scheduled workflow."""
    while True:
        try:
            connected=bool(check_connected())
            if connected:
                await close_stale()
            elif configured() and pending_count()>0:
                await ensure_started(reason="recovery_supervisor",connected=False)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            print("[hitel-worker-autostart] watchdog exception="+type(exc).__name__,flush=True)
        await asyncio.sleep(max(5,interval))


def reserve_signed_runner_fallback(*,connected:bool) -> bool:
    """One GitHub-hosted worker can self-dispatch its successor if work remains.

    The caller must be an OIDC-verified run of the *exact* pinned workflow.
    Uses the same durable SQLite lease as Railway's direct dispatcher. The
    next run is created with the job-scoped GITHUB_TOKEN, not a public URL.
    """
    if connected or pending_count()==0:
        return False
    now=api_v1.clock()
    with api_v1.connection() as c:
        c.execute("BEGIN IMMEDIATE")
        row=c.execute("SELECT next_attempt_at,lock_until "
                      "FROM hitel_chrome_autostart WHERE id=1").fetchone()
        if row["next_attempt_at"]>now or row["lock_until"]>now:
            return False
        c.execute("""UPDATE hitel_chrome_autostart
                     SET status='github_fallback_reserved',
                         next_attempt_at=?,lock_until=? WHERE id=1""",
                  (now+DISPATCH_COOLDOWN_MS,now+LEASE_MS))
    return True
