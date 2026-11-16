"""Public, credential-free locator for the private GitHub Actions login screen.

The GitHub Actions job publishes ONLY a temporary password-protected tunnel URL.
No account passwords, Chrome access codes or session artifacts enter this API.
"""
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter
from fastapi.responses import FileResponse

router=APIRouter()
ROOT=Path(__file__).resolve().parent
WORKFLOW_URL=(
 "https://github.com/lyonbegin/procureflow/actions/workflows/"
 "hitel-two-account-manual-login.yml"
)
API_ROOT="https://api.github.com/repos/lyonbegin/procureflow"
RUNS_URL=API_ROOT+"/actions/workflows/hitel-two-account-manual-login.yml/runs?per_page=5"
_context="hitel-two-manual-chrome-logins"
_cache_lock=threading.Lock()
_cache={"until":0.0,"value":{"ready":False,"workflowUrl":WORKFLOW_URL}}
_FRESH=48*60


def verified_link(status:dict,now:datetime|None=None) -> str|None:
    """Only fresh GH commit statuses for our private /grant login control."""
    if status.get("context")!=_context or status.get("state")!="pending":
        return None
    value=status.get("target_url")
    if not isinstance(value,str) or len(value)>256:
        return None
    url=urlsplit(value)
    if (url.scheme!="https" or
        not isinstance(url.hostname,str) or
        not re.fullmatch(r"[a-z0-9-]+\.trycloudflare\.com",url.hostname) or
        url.path!="/grant" or url.port not in (None,443) or
        url.username or url.password or url.query or url.fragment):
        return None
    try:
        created=datetime.fromisoformat(status["created_at"].replace("Z","+00:00"))
    except (KeyError,TypeError,AttributeError,ValueError):
        return None
    current=now or datetime.now(timezone.utc)
    if created>current or (current-created).total_seconds()>_FRESH:
        return None
    return value


@router.get("/remote-login")
def remote_login_page():
    return FileResponse(
        ROOT/"static"/"remote_login.html",media_type="text/html",
        headers={"Cache-Control":"no-store","X-Content-Type-Options":"nosniff",
                 "Referrer-Policy":"no-referrer",
                 "Content-Security-Policy":
                   "default-src 'self'; script-src 'self' 'unsafe-inline'; "
                   "style-src 'self' 'unsafe-inline'; connect-src 'self'; "
                   "frame-ancestors 'none'; object-src 'none'"}
    )


@router.get("/web/api/remote-login/status")
def remote_login_status():
    with _cache_lock:
        if _cache["until"]>time.monotonic():
            return dict(_cache["value"])
    payload={"ready":False,"workflowUrl":WORKFLOW_URL}
    try:
        with httpx.Client(timeout=7,headers={"Accept":"application/vnd.github+json",
                    "User-Agent":"HITEL-two-profile-login-screen"}) as client:
            response=client.get(RUNS_URL)
            response.raise_for_status()
            runs=response.json().get("workflow_runs",[])
            # The current branch may have advanced AFTER the temporary
            # authenticated Chrome session started. Query the actual active
            # workflow's head SHA, not the tip of main.
            for run in runs[:5]:
                if run.get("status") != "in_progress":
                    continue
                sha=run.get("head_sha")
                if not isinstance(sha,str) or not re.fullmatch(r"[0-9a-f]{40}",sha):
                    continue
                status_response=client.get(API_ROOT+"/commits/"+sha+"/status")
                status_response.raise_for_status()
                for entry in status_response.json().get("statuses",[]):
                    if entry.get("context")==_context:
                        valid=verified_link(entry)
                        if valid:
                            payload["ready"]=True
                            payload["remoteUrl"]=valid
                        break
                if payload["ready"]:
                    break
    except (httpx.HTTPError,ValueError,TypeError,AttributeError):
        payload["statusUnavailable"]=True
    with _cache_lock:
        _cache["value"]=payload
        _cache["until"]=time.monotonic()+20
    return dict(payload)
