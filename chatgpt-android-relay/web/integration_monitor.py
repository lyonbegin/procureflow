"""HITEL cross-service, read-only operational monitoring.

This endpoint aggregates every HITEL public API client and every named room.
Clients may optionally identify service_id at room creation or chat submission.
Older calls remain compatible and are shown as "unassigned".

The public payload never includes chat question/answer content, secret tokens,
personal ChatGPT conversation URLs, email addresses, private room titles, or
internal worker credentials. Authenticated API jobs appear only as aggregate
counts. Live Railway job snapshots are fresh; GitHub workflow metadata is
cached for 75 seconds, with partial failures explicitly marked.
"""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.request

from fastapi import APIRouter

import api_v1
import integration_public
import worker_autostart

router = APIRouter(prefix="/integrations/v1/public", tags=["HITEL cross-service operations"])
_REPOS=("lyonbegin/procureflow","lyonbegin/hitel-scribd-runner")
_CACHE_TTL=75
_CACHE_LOCK=threading.Lock()
_CACHE={"last_attempt":0.0,"updated_ms":None,"runs":[],"error":None}
_STATUS={"queued","running","completed","failed"}

def _github_runs(repo: str) -> list[dict]:
    url=f"https://api.github.com/repos/{repo}/actions/runs?per_page=50"
    headers={
        "User-Agent":"HITEL-Shared-API-Monitor/1.0",
        "Accept":"application/vnd.github+json",
        "X-GitHub-Api-Version":"2022-11-28",
    }
    if repo=="lyonbegin/procureflow":
        token=os.environ.get("HITEL_GITHUB_ACTIONS_TOKEN","")
        if token:
            headers["Authorization"]="Bearer "+token
    req=urllib.request.Request(url,headers=headers)
    with urllib.request.urlopen(req,timeout=7) as resp:
        doc=json.load(resp)
    raw=doc.get("workflow_runs")
    if not isinstance(raw,list):
        raise ValueError("unexpected_github_schema")
    matches=[]
    for item in raw:
        name=str(item.get("name") or "")
        if not ("hitel" in name.casefold() or "chatgpt" in name.casefold()):
            continue
        run_id=item.get("id")
        if not isinstance(run_id,int):
            continue
        matches.append({
            "id":run_id,
            "repository":repo,
            "name":name[:120],
            "status":item.get("status"),
            "conclusion":item.get("conclusion"),
            "created_at":item.get("created_at"),
            "updated_at":item.get("updated_at"),
            "url":f"https://github.com/{repo}/actions/runs/{run_id}",
        })
        if len(matches)>=18:
            break
    return matches


def github_snapshot() -> dict:
    now=time.monotonic()
    with _CACHE_LOCK:
        if _CACHE["last_attempt"] and now-_CACHE["last_attempt"]<_CACHE_TTL:
            return {"checked_at":_CACHE["updated_ms"],
                    "runs":list(_CACHE["runs"]),
                    "error":_CACHE["error"],
                    "refresh_interval_seconds":_CACHE_TTL}
        _CACHE["last_attempt"]=now
        all_runs=[]
        errors=[]
        for repo in _REPOS:
            try:
                all_runs.extend(_github_runs(repo))
            except Exception as exc:
                # Only a safe exception type is returned; never a response
                # body or a header that could contain GitHub credentials.
                errors.append(repo.split("/")[1]+":"+type(exc).__name__)
        if all_runs:
            _CACHE["runs"]=sorted(all_runs,
                                  key=lambda x:x.get("created_at") or "",
                                  reverse=True)[:35]
            _CACHE["updated_ms"]=api_v1.clock()
        _CACHE["error"]=", ".join(errors) if errors else None
        return {"checked_at":_CACHE["updated_ms"],
                "runs":list(_CACHE["runs"]),
                "error":_CACHE["error"],
                "refresh_interval_seconds":_CACHE_TTL}


def _status_counts(rows:list) -> dict:
    d={s:0 for s in sorted(_STATUS)}
    for item in rows:
        status=item["status"]
        if status in d:
            d[status]+=item["n"]
    d["total"]=sum(d.values())
    return d


@router.get("/monitor")
def cross_service_monitor():
    from app import active_job_id,web2api_device,web2api_last_seen_monotonic
    observed=api_v1.clock()
    since=observed-86400000
    pub=integration_public.USER_ID
    with api_v1.connection() as db:
        # The account-bound integration is counted without exposing any
        # owner identity, room name, URL, message text or individual job.
        global_jobs=db.execute("""SELECT
          CASE WHEN user_id=? AND account_id IS NULL THEN 'public'
               WHEN account_id IS NOT NULL THEN 'account_bound'
               ELSE 'legacy_other' END AS channel,
          status, COUNT(*) AS n
          FROM jobs WHERE action='chat.send'
          GROUP BY channel,status""",(pub,)).fetchall()
        global_24h=db.execute("""SELECT
          CASE WHEN user_id=? AND account_id IS NULL THEN 'public'
               WHEN account_id IS NOT NULL THEN 'account_bound'
               ELSE 'legacy_other' END AS channel,
          status, COUNT(*) AS n
          FROM jobs WHERE action='chat.send' AND created_at>=?
          GROUP BY channel,status""",(pub,since)).fetchall()
        # New namespaced clients are associated with room_id. Existing
        # clients have no service id and remain explicitly "unassigned".
        public_jobs=db.execute("""SELECT j.status,COUNT(*) AS n
            FROM jobs j WHERE j.user_id=? AND j.account_id IS NULL
              AND j.action='chat.send'
            GROUP BY j.status""",(pub,)).fetchall()
        recent=db.execute("""SELECT j.id,j.room_id,r.title AS room_name,
               sr.service_id,j.status,j.stage,j.created_at,j.updated_at
               FROM jobs j
               JOIN rooms r ON r.id=j.room_id
               LEFT JOIN hitel_public_room_services sr ON sr.room_id=r.id
               WHERE j.user_id=? AND j.account_id IS NULL
                 AND j.action='chat.send'
               ORDER BY j.created_at DESC,j.id DESC LIMIT 40""",
               (pub,)).fetchall()
        rooms=db.execute("""SELECT r.id,r.title,r.chatgpt_url,r.updated_at,
                sr.service_id,
                COUNT(j.id) AS total,
                COALESCE(SUM(CASE WHEN j.status='completed' THEN 1 ELSE 0 END),0) AS completed,
                COALESCE(SUM(CASE WHEN j.status='failed' THEN 1 ELSE 0 END),0) AS failed,
                COALESCE(SUM(CASE WHEN j.status='queued' THEN 1 ELSE 0 END),0) AS queued,
                COALESCE(SUM(CASE WHEN j.status='running' THEN 1 ELSE 0 END),0) AS running,
                MAX(j.updated_at) AS last_job_at
                FROM rooms r
                LEFT JOIN hitel_public_room_services sr ON sr.room_id=r.id
                LEFT JOIN jobs j ON j.room_id=r.id AND j.user_id=r.user_id
                  AND j.action='chat.send'
                WHERE r.user_id=? AND r.status='active'
                GROUP BY r.id
                ORDER BY COALESCE(MAX(j.updated_at),r.updated_at) DESC LIMIT 150""",
                (pub,)).fetchall()
        recent_error_groups=db.execute("""SELECT stage,COUNT(*) AS n
            FROM jobs WHERE user_id=? AND account_id IS NULL
             AND action='chat.send' AND status='failed'
             AND created_at>=?
            GROUP BY stage ORDER BY n DESC LIMIT 10""",(pub,since)).fetchall()
    by_channel={}
    by_channel_24h={}
    for rows,dest in ((global_jobs,by_channel),(global_24h,by_channel_24h)):
        for channel in ("public","account_bound","legacy_other"):
            subset=[row for row in rows if row["channel"]==channel]
            dest[channel]=_status_counts(subset)
    program_map={}
    for r in rooms:
        service=r["service_id"] or "미지정"
        if service not in program_map:
            program_map[service]={
                "service_id":service,"room_count":0,
                "total":0,"completed":0,"failed":0,
                "queued":0,"running":0,"last_activity":None,
            }
        p=program_map[service]
        p["room_count"]+=1
        for s in ("total","completed","failed","queued","running"):
            p[s]+=int(r[s])
        latest=r["last_job_at"] or r["updated_at"]
        p["last_activity"]=max(p["last_activity"] or 0, latest or 0)
    room_items=[{
        "room_id":r["id"],
        "room_name":r["title"],
        "service_id":r["service_id"] or "미지정",
        "conversation_linked":bool(r["chatgpt_url"]),
        "total":r["total"],"completed":r["completed"],
        "failed":r["failed"],"queued":r["queued"],
        "running":r["running"],
        "last_activity":r["last_job_at"] or r["updated_at"],
    } for r in rooms]
    github=github_snapshot()
    online=web2api_device is not None
    heartbeat_age=(round(max(0,time.monotonic()-web2api_last_seen_monotonic),1)
                   if online and web2api_last_seen_monotonic else None)
    return {
      "observed_at":observed,
      "scope":"all_HITEL_public_named_rooms_plus_anonymized_account_bound",
      "monitor_version":"2.0",
      "worker":{
        "connected":online,
        "heartbeat_age_seconds":heartbeat_age,
        "active_job_id":active_job_id if active_job_id and
           any(r["id"]==active_job_id for r in recent) else None,
        "auto_start":worker_autostart.read_status(connected=online),
      },
      "jobs":{
        "total_by_channel":by_channel,
        "last24h_by_channel":by_channel_24h,
        "public_counts":_status_counts(public_jobs),
        "recent":[{
            "job_id":r["id"],"room_id":r["room_id"],
            "room_name":r["room_name"],
            "service_id":r["service_id"] or "미지정",
            "status":r["status"],"stage":r["stage"],
            "created_at":r["created_at"],
            "updated_at":r["updated_at"],
        } for r in recent],
        "recent_error_stages":[{
            "stage":r["stage"],"count":r["n"]
        } for r in recent_error_groups],
      },
      "programs":sorted(program_map.values(),
                        key=lambda x:x["last_activity"] or 0,reverse=True),
      "rooms":room_items,
      "github":github,
      "notes":{
        "program_tagging":"Provide optional service_id in POST /public/rooms or /public/chat.",
        "untagged_programs":"미지정 groups existing clients which did not send service_id.",
        "account_bound_privacy":"Authenticated integrations are counted globally only; no private room names or messages.",
        "content_privacy":"Messages, credentials and ChatGPT URLs are never returned.",
        "github_data":"GitHub Actions metadata is cached. This does not imply every external program has a GitHub workflow.",
      },
    }
