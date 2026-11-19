"""Read-only, live HITEL and Scribd operations monitoring.

Public dashboard intentionally exposes only synthetic/public HITEL test
job identifiers, status and timing, never question/response text, login keys,
Chrome cookies, profile emails, private rooms or runner credentials.
Fast-changing Railway state is read on every request. Public GitHub Actions
run metadata is refreshed at most every 80 seconds per process to stay
within public API limits.
"""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.request

from fastapi import APIRouter

import api_v1
import integration_public
import worker_autostart

router = APIRouter(prefix="/integrations/v1/public", tags=["public monitoring"])
GH_REPOS = ("lyonbegin/procureflow", "lyonbegin/hitel-scribd-runner")
PILOT_RUN = 44438675220
PILOT_EVIDENCE = (
    "https://github.com/lyonbegin/hitel-scribd-runner/actions/runs/"
    + str(PILOT_RUN)
)
ORIGINAL_TOTAL = 18109
CACHE_TTL_SECONDS = 80
_CACHE_LOCK = threading.Lock()
_GH_CACHE: dict = {"at": 0, "runs": [], "error": "not_loaded", "last_success": None}


def _is_relevant(name: str, repo: str) -> bool:
    if repo == "lyonbegin/procureflow":
        return any(q in name for q in (
            "HITEL - Start Chrome API worker",
            "HITEL public named rooms",
            "HITEL programmatic API contract",
        ))
    return any(q in name for q in (
        "HITEL real Scribd 20-title",
        "HITEL 18109 AI classification",
        "HITEL 18109 named room runner",
        "HITEL named rooms real conversation",
        "HITEL 18109 named room",
    ))


def _fetch_run_list(repo: str) -> list[dict]:
    url = f"https://api.github.com/repos/{repo}/actions/runs?per_page=35"
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "HITEL-Public-ReadOnly-Monitor/1",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    # Existing Railway token is used only for the repository to which it
    # was granted. It never reaches the browser or the API response.
    if repo == "lyonbegin/procureflow":
        token = os.environ.get("HITEL_GITHUB_ACTIONS_TOKEN", "")
        if token:
            headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=7) as response:
        doc = json.load(response)
    runs = doc.get("workflow_runs")
    if not isinstance(runs, list):
        raise ValueError("github_response_missing_runs")
    out = []
    for item in runs:
        name = item.get("name", "")
        if not isinstance(name, str) or not _is_relevant(name, repo):
            continue
        run_id = item.get("id")
        if not isinstance(run_id, int):
            continue
        out.append({
            "repository": repo,
            "name": name[:115],
            "id": run_id,
            "url": f"https://github.com/{repo}/actions/runs/{run_id}",
            "status": item.get("status", "unknown"),
            "conclusion": item.get("conclusion"),
            "created_at": item.get("created_at"),
            "updated_at": item.get("updated_at"),
        })
        if len(out) >= 12:
            break
    return out


def github_run_snapshot() -> dict:
    now = time.monotonic()
    with _CACHE_LOCK:
        if _GH_CACHE["at"] and now - _GH_CACHE["at"] < CACHE_TTL_SECONDS:
            return {
                "checked_at": _GH_CACHE["last_success"],
                "runs": list(_GH_CACHE["runs"]),
                "error": _GH_CACHE["error"],
                "cache_seconds": CACHE_TTL_SECONDS,
            }
        _GH_CACHE["at"] = now
        collected: list[dict] = []
        errors: list[str] = []
        for repo in GH_REPOS:
            try:
                collected.extend(_fetch_run_list(repo))
            except Exception as exc:
                # No arbitrary HTTP exception bodies, GitHub response details,
                # token values or credential configuration are exposed.
                errors.append(repo.split("/")[1] + ":" + type(exc).__name__)
        if collected:
            _GH_CACHE["runs"] = collected
            _GH_CACHE["last_success"] = api_v1.clock()
        _GH_CACHE["error"] = ", ".join(errors) if errors else None
        return {
            "checked_at": _GH_CACHE["last_success"],
            "runs": list(_GH_CACHE["runs"]),
            "error": _GH_CACHE["error"],
            "cache_seconds": CACHE_TTL_SECONDS,
        }


@router.get("/monitor")
def public_monitor_snapshot():
    from app import active_job_id, web2api_device, web2api_last_seen_monotonic

    now = api_v1.clock()
    uid = integration_public.USER_ID
    statuses = ("queued", "running", "completed", "failed")
    with api_v1.connection() as db:
        counted = db.execute(
            "SELECT status, COUNT(*) AS n FROM jobs "
            "WHERE user_id=? AND account_id IS NULL GROUP BY status",
            (uid,),
        ).fetchall()
        counts = {s: 0 for s in statuses}
        for row in counted:
            if row["status"] in counts:
                counts[row["status"]] = row["n"]
        recent = db.execute(
            """SELECT j.id, j.room_id, r.title AS room_name,
                      j.status, j.stage, j.created_at, j.updated_at
               FROM jobs j JOIN rooms r
               ON r.id=j.room_id AND r.user_id=j.user_id
               WHERE j.user_id=? AND j.account_id IS NULL
               ORDER BY j.created_at DESC, j.id DESC LIMIT 24""",
            (uid,),
        ).fetchall()
        room_rows = db.execute(
            """SELECT r.id, r.title, r.chatgpt_url,
                    COUNT(j.id) AS total,
                    COALESCE(SUM(CASE WHEN j.status='completed' THEN 1 ELSE 0 END),0) AS completed,
                    COALESCE(SUM(CASE WHEN j.status='failed' THEN 1 ELSE 0 END),0) AS failed,
                    COALESCE(SUM(CASE WHEN j.status IN ('queued','running') THEN 1 ELSE 0 END),0) AS pending,
                    MAX(j.updated_at) AS last_activity
               FROM rooms r
               LEFT JOIN jobs j ON j.room_id=r.id AND j.user_id=r.user_id
               WHERE r.user_id=? AND r.status='active'
               GROUP BY r.id
               ORDER BY COALESCE(MAX(j.updated_at),r.updated_at) DESC
               LIMIT 35""",
            (uid,),
        ).fetchall()
        today_rows = db.execute(
            "SELECT status,COUNT(*) AS n FROM jobs "
            "WHERE user_id=? AND account_id IS NULL AND created_at>=? GROUP BY status",
            (uid, now - 24*60*60*1000),
        ).fetchall()
    last24 = {s:0 for s in statuses}
    for row in today_rows:
        if row["status"] in last24:
            last24[row["status"]] = row["n"]
    gh = github_run_snapshot()
    pilot = next(
        (item for item in gh["runs"]
         if item["repository"] == "lyonbegin/hitel-scribd-runner"
         and item["id"] == PILOT_RUN),
        None,
    )
    # The named pilot has a real 20/20 checkpoint and a success record.
    # Do not equate pilot samples with full-corpus completed rows.
    if not pilot:
        pilot_status = "previously_verified"
    elif pilot.get("conclusion") == "success":
        pilot_status = "verified"
    else:
        pilot_status = "unverified"
    connected = web2api_device is not None
    age = (
        round(max(0.0, time.monotonic()-web2api_last_seen_monotonic),1)
        if connected and web2api_last_seen_monotonic > 0
        else None
    )
    recent_items = [
        {
            "job_id": row["id"],
            "room_id": row["room_id"],
            "room_name": row["room_name"],
            "status": row["status"],
            "stage": row["stage"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        } for row in recent
    ]
    room_items = [
        {
            "room_id": row["id"],
            "room_name": row["title"],
            "conversation_linked": bool(row["chatgpt_url"]),
            "total": row["total"],
            "completed": row["completed"],
            "failed": row["failed"],
            "pending": row["pending"],
            "last_activity": row["last_activity"],
        } for row in room_rows
    ]
    return {
        "observed_at": now,
        "scope": "public_HITEL_text_jobs_and_GitHub_Action_runs",
        "worker": {
            "connected": connected,
            "heartbeat_age_seconds": age,
            "active_job_id": active_job_id,
            "auto_start": worker_autostart.read_status(connected=connected),
        },
        "jobs": {
            "counts": {**counts, "total": sum(counts.values())},
            "last_24h": {**last24, "total": sum(last24.values())},
            "recent": recent_items,
        },
        "rooms": room_items,
        "github": gh,
        "scribd": {
            "original_total": ORIGINAL_TOTAL,
            "pilot_verified_rows": 20 if pilot_status != "unverified" else None,
            "pilot_status": pilot_status,
            "pilot_run_url": PILOT_EVIDENCE,
            "full_corpus_verified_rows": None,
            "full_corpus_status": "not_independently_verified",
            "full_corpus_note": "20-title pilot is not 18,109-row production completion.",
        },
    }
