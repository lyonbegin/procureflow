"""Task-isolated GitHub Chrome Web2API transport (additive v2).

Legacy /ws, prewarmed Scribd rooms, and the existing dispatch state remain
untouched. Every task gets one independently OIDC-attested GitHub-hosted
Chrome process, and a fenced, task-bound WebSocket; no worker may take a job
from another task. The database survives Railway process restarts.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
from dataclasses import dataclass, field

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

import api_v1
import integration_public as public
import long_job_events
from gh_oidc import verify_isolated_worker_identity

router = APIRouter(tags=["HITEL independent task Chrome workers"])
TASK_PATTERN = re.compile(r"^[a-z][a-z0-9-]{2,47}$")
VALID_TASKS = ("stock-a", "stock-tv", "scribd-18109")
MAX_REPLY_BYTES = 2_000_000
WORKER_STALE_SECONDS = 75

# Railway SQLite is persistent; the socket objects themselves are process local.
with api_v1.connection() as db:
    db.execute("""CREATE TABLE IF NOT EXISTS hitel_isolated_tasks (
        task_id TEXT PRIMARY KEY,
        workflow TEXT NOT NULL,
        worker_run_id INTEGER,
        generation INTEGER NOT NULL DEFAULT 0,
        heartbeat_at INTEGER,
        created_at INTEGER NOT NULL,
        updated_at INTEGER NOT NULL
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS hitel_isolated_job_map (
        job_id TEXT PRIMARY KEY,
        task_id TEXT NOT NULL,
        room_id TEXT NOT NULL,
        created_at INTEGER NOT NULL,
        FOREIGN KEY(task_id) REFERENCES hitel_isolated_tasks(task_id)
    )""")
    db.execute("""CREATE INDEX IF NOT EXISTS idx_hitel_isolated_jobs
        ON hitel_isolated_job_map(task_id,created_at)""")
    for name in VALID_TASKS:
        now=api_v1.clock()
        db.execute("""INSERT OR IGNORE INTO hitel_isolated_tasks
            (task_id,workflow,created_at,updated_at) VALUES(?,?,?,?)""",
            (name,"hitel-isolated-chrome-worker.yml",now,now))


@dataclass
class Session:
    ws: WebSocket
    run_id: int
    generation: int
    heartbeat: float = field(default_factory=time.monotonic)
    bootstrapped: bool = False
    active: dict[str,str] = field(default_factory=dict)  # job_id -> room_id
    preflight: set[str] = field(default_factory=set)


sessions: dict[str,Session] = {}
lock=asyncio.Lock()


class TaskChat(BaseModel):
    request_id: str = Field(min_length=16,max_length=128)
    room_name: str = Field(min_length=1,max_length=130)
    text: str = Field(min_length=1,max_length=24000)


def normalized_task(task_id: str) -> str:
    if not TASK_PATTERN.fullmatch(task_id) or task_id not in VALID_TASKS:
        raise HTTPException(404,"Unknown isolated task")
    return task_id


def task_room(task_id: str, room: str) -> str:
    safe=" ".join(room.split())
    if (not safe or len(safe)>130
            or any(ord(x)<32 for x in safe)):
        raise HTTPException(422,"Invalid task room")
    return "HITEL-ISOLATED-"+task_id.upper()+"-"+safe


def task_health(task_id: str) -> dict:
    session=sessions.get(task_id)
    live=bool(session and session.bootstrapped and
              time.monotonic()-session.heartbeat<=WORKER_STALE_SECONDS)
    with api_v1.connection() as db:
        row=db.execute("""SELECT generation,worker_run_id,heartbeat_at
            FROM hitel_isolated_tasks WHERE task_id=?""",(task_id,)).fetchone()
        queued=db.execute("""SELECT COUNT(*) FROM jobs j
            JOIN hitel_isolated_job_map m ON m.job_id=j.id
            WHERE m.task_id=? AND j.status='queued'""",(task_id,)).fetchone()[0]
        active=db.execute("""SELECT COUNT(*) FROM jobs j
            JOIN hitel_isolated_job_map m ON m.job_id=j.id
            WHERE m.task_id=? AND j.status='running'""",(task_id,)).fetchone()[0]
    return {
        "task_id":task_id,"worker_connected":live,
        "worker_heartbeat_recent":live,"worker_bootstrap_ready":live,
        "worker_available_for_new_job":live,"worker_active_jobs_count":active,
        "queued_jobs_count":queued,
        "generation":row["generation"],
        "worker_run_id":session.run_id if live else None,
    }


@router.get("/integrations/v1/public/isolated/tasks/pending")
def pending_task_counts():
    """Only counts; safe for the GitHub five-minute task scheduler to query."""
    return {"tasks":[task_health(t) for t in VALID_TASKS]}


@router.get("/integrations/v1/public/isolated/tasks/{task_id}/status")
def isolated_task_status(task_id: str):
    return task_health(normalized_task(task_id))


@router.post("/integrations/v1/public/isolated/tasks/{task_id}/chat",status_code=202)
async def isolated_chat(task_id: str, payload: TaskChat):
    """Public research-channel equivalent of /public/chat, but task fenced.

    The immutable request_id remains readable via the existing /public/requests
    and /public/jobs endpoints. No legacy worker can take a mapped task job.
    """
    task_id=normalized_task(task_id)
    if not public.REQUEST_ID.fullmatch(payload.request_id):
        raise HTTPException(422,"Invalid immutable request ID")
    text=payload.text.strip()
    if not text or any(ord(c)<32 and c not in "\r\n\t" for c in text):
        raise HTTPException(422,"Empty or invalid text")
    name=task_room(task_id,payload.room_name)
    with public.LOCK, api_v1.connection() as db:
        db.execute("BEGIN IMMEDIATE")
        old=db.execute("""SELECT p.fingerprint,p.job_id,j.room_id,m.task_id
            FROM hitel_public_link_requests p
            JOIN jobs j ON j.id=p.job_id
            LEFT JOIN hitel_isolated_job_map m ON m.job_id=j.id
            WHERE p.request_id=?""",(payload.request_id,)).fetchone()
        if old:
            if old["task_id"]!=task_id:
                raise HTTPException(409,"Request belongs to another worker task")
            room=db.execute("SELECT title FROM rooms WHERE id=?",
                            (old["room_id"],)).fetchone()
            fingerprint=hashlib.sha256(json.dumps(
                {"room_id":old["room_id"],"text":text},
                ensure_ascii=False,sort_keys=True,separators=(",",":")
            ).encode("utf-8")).hexdigest()
            if not room or room["title"]!=name or fingerprint!=old["fingerprint"]:
                raise HTTPException(409,"Immutable request scope changed")
            return {"accepted":True,"replayed":True,"task_id":task_id,
                    "request_id":payload.request_id,
                    "job_id":old["job_id"],"room_id":old["room_id"]}
        room,_=public._open_named_room(db,name)
        rid=room["id"]
        existing=db.execute("""SELECT DISTINCT m.task_id
            FROM hitel_isolated_job_map m WHERE m.room_id=?""",(rid,)).fetchall()
        if any(x["task_id"]!=task_id for x in existing):
            raise HTTPException(409,"Room belongs to another task")
        pending=db.execute("""SELECT 1 FROM jobs WHERE room_id=? AND
            status IN ('queued','running','stalled','unknown') LIMIT 1""",
            (rid,)).fetchone()
        if pending:
            raise HTTPException(409,"Previous question in this room unresolved")
        jid=api_v1.store_job(db,public.USER_ID,rid,"chat.send",text,[],
                             account_id=None)
        now=api_v1.clock()
        db.execute("""INSERT INTO hitel_isolated_job_map
            (job_id,task_id,room_id,created_at) VALUES(?,?,?,?)""",
            (jid,task_id,rid,now))
        db.execute("""INSERT INTO messages
            (id,user_id,room_id,job_id,role,text,created_at)
            VALUES(?,?,?,?,?,?,?)""",("msg_"+api_v1.new_id(),
             public.USER_ID,rid,jid,"user",text,now))
        digest=hashlib.sha256(json.dumps({"room_id":rid,"text":text},
                 ensure_ascii=False,sort_keys=True,separators=(",",":")
            ).encode("utf-8")).hexdigest()
        db.execute("""INSERT INTO hitel_public_link_requests
            (request_id,fingerprint,job_id,created_at)
            VALUES(?,?,?,?)""",(payload.request_id,digest,jid,now))
    await dispatch_task(task_id)
    return {"accepted":True,"replayed":False,"task_id":task_id,
            "request_id":payload.request_id,"job_id":jid,"room_id":rid,
            "worker_connected":task_health(task_id)["worker_connected"],
            "status":"queued"}


async def dispatch_task(task_id: str):
    session=sessions.get(task_id)
    if not session or not session.bootstrapped or (
            time.monotonic()-session.heartbeat>WORKER_STALE_SECONDS):
        return
    async with lock:
        # Claim filters are atomically enforced by existing DB code; a
        # legacy /ws worker must never consume a task-mapped job.
        while True:
            job=api_v1.claim_next_job(
                only_user_id=public.USER_ID,allow_account_bound=True,
                web_text_only=True,task_id=task_id)
            if job is None:
                return
            jid=job["id"]
            session.active[jid]=job["room_id"]
            try:
                await session.ws.send_json({"type":"job","job":job})
                long_job_events.observe(jid,"worker_dispatched")
            except Exception:
                api_v1.update_job(jid,status="unknown",
                    stage="isolated_worker_transport_interrupted",
                    error="Task worker disconnect; delivery not verified")
                long_job_events.observe(jid,"worker_transport_interrupted",
                    error_code="WORKER_CONNECTION_LOST",error_stage="dispatch")
                session.active.pop(jid,None)
                return


def active_matches(task_id, session, jid, rid):
    return (sessions.get(task_id) is session and isinstance(jid,str)
            and session.active.get(jid)==rid)


async def handle_report(task_id: str, session: Session, msg: dict):
    kind=msg.get("type")
    jid=msg.get("job_id")
    rid=msg.get("room_id")
    if not active_matches(task_id,session,jid,rid):
        return
    if kind=="job.preflight":
        # Account-bound research tasks are not silently converted to guest
        # jobs. A separate verified account gate must be added to enable one.
        await session.ws.send_json({"type":"job.preflight.denied",
                                    "job_id":jid,"room_id":rid})
        return
    if kind in ("job.received","job.progress"):
        stage=str(msg.get("stage",kind))[:100]
        api_v1.update_job(jid,stage=stage)
        long_job_events.observe(
            jid,"worker_received" if kind=="job.received" else stage,
            send_confirmed=stage=="web2api_send_ui_acknowledged",
            reply_observed=stage in ("web2api_assistant_seen",
                                   "web2api_turn_completed",
                                   "web2api_adapter_reply_parsed"))
        return
    if kind=="job.uncertain":
        api_v1.update_job(jid,status="unknown",
            stage="upstream_delivery_unknown",
            error=str(msg.get("reason","Unknown upstream delivery"))[:100])
        long_job_events.observe(jid,"upstream_delivery_unknown",
            error_code="UPSTREAM_DELIVERY_UNKNOWN",error_stage="connection")
    elif kind in ("job.result","job.error"):
        # Scope through both the authoritative task-job mapping and the
        # DB running status, not just the untrusted worker packet.
        with api_v1.connection() as db:
            scoped=db.execute("""SELECT j.action,j.status FROM jobs j
                JOIN hitel_isolated_job_map m ON m.job_id=j.id
                WHERE j.id=? AND j.room_id=? AND m.task_id=?""",
                (jid,rid,task_id)).fetchone()
        valid=bool(kind=="job.result" and scoped
                   and scoped["status"]=="running"
                   and scoped["action"]=="chat.send"
                   and msg.get("verified") is True
                   and msg.get("stage")=="assistant_reply_stable"
                   and isinstance(msg.get("result_text"),str)
                   and 0<len(msg["result_text"].encode("utf-8"))<=MAX_REPLY_BYTES
                   and isinstance(msg.get("chatgpt_url"),str))
        committed=False
        if valid:
            committed=api_v1.complete_web2api_job(
                jid,rid,msg["result_text"],msg["chatgpt_url"])
        if committed:
            long_job_events.observe(jid,"assistant_reply_verified",
                                    send_confirmed=True,reply_observed=True)
            await session.ws.send_json(
                {"type":"job.committed","job_id":jid,
                 "room_id":rid,"verified":True})
        else:
            api_v1.update_job(jid,status="unknown"
                if kind=="job.result" else "failed",
                stage="isolated_unverified_result",
                error="Worker result failed scoped identity or stage check")
            long_job_events.observe(jid,"worker_reported_failure",
                error_code="ISOLATED_UNVERIFIED_RESULT",
                error_stage="scope")
    else:
        return
    session.active.pop(jid,None)
    await dispatch_task(task_id)


@router.websocket("/ws/task/{task_id}")
async def isolated_socket(ws: WebSocket,task_id: str):
    if task_id not in VALID_TASKS:
        await ws.close(code=1008)
        return
    await ws.accept()
    session=None
    try:
        auth=json.loads(await asyncio.wait_for(ws.receive_text(),timeout=12))
        if (not isinstance(auth,dict)
            or auth.get("role")!="web2api"
            or auth.get("task_id")!=task_id
            or auth.get("hitel_protocol_version")!=4):
            await ws.close(code=1008)
            return
        claims=await asyncio.to_thread(verify_isolated_worker_identity,
                                     auth.get("oidc_token"))
        if claims is None:
            await ws.close(code=1008)
            return
        run_id=int(claims["run_id"])
        async with lock:
            current=sessions.get(task_id)
            if current and current.active:
                # The old browser might have already typed a prompt. Reject
                # overlapping workers; do not replace/close a live sender.
                await ws.close(code=1008)
                return
            with api_v1.connection() as db:
                db.execute("BEGIN IMMEDIATE")
                row=db.execute("""SELECT generation FROM hitel_isolated_tasks
                    WHERE task_id=?""",(task_id,)).fetchone()
                if not row:
                    await ws.close(code=1008)
                    return
                generation=int(row["generation"])+1
                db.execute("""UPDATE hitel_isolated_tasks
                    SET generation=?,worker_run_id=?,heartbeat_at=?,updated_at=?
                    WHERE task_id=?""",(generation,run_id,
                                         api_v1.clock(),api_v1.clock(),task_id))
            session=Session(ws,run_id,generation)
            sessions[task_id]=session
            if current and current.ws is not ws:
                await current.ws.close(code=1001)
        await ws.send_json({"type":"auth.ok","role":"web2api",
                            "task_id":task_id,"generation":session.generation})
        await ws.send_json({"type":"room.bootstrap","rooms":[]})
        while True:
            msg=json.loads(await ws.receive_text())
            if not isinstance(msg,dict) or sessions.get(task_id) is not session:
                continue
            kind=msg.get("type")
            session.heartbeat=time.monotonic()
            with api_v1.connection() as db:
                db.execute("""UPDATE hitel_isolated_tasks
                    SET heartbeat_at=?,updated_at=?
                    WHERE task_id=? AND generation=?""",
                    (api_v1.clock(),api_v1.clock(),task_id,session.generation))
            if kind=="worker.heartbeat":
                for jid in tuple(session.active):
                    long_job_events.heartbeat(jid)
            elif kind=="room.bootstrap.done":
                if msg.get("ready_rooms")!=[]:
                    await ws.close(code=1008)
                    break
                session.bootstrapped=True
                await dispatch_task(task_id)
            elif kind in ("job.preflight","job.received","job.progress",
                          "job.result","job.error","job.uncertain"):
                await handle_report(task_id,session,msg)
            elif kind=="ping":
                await ws.send_json({"type":"pong"})
    except (WebSocketDisconnect,asyncio.TimeoutError):
        pass
    except (ValueError,TypeError,KeyError) as exc:
        print("[isolated-worker] rejected malformed packet",type(exc).__name__,
              flush=True)
    finally:
        if session and sessions.get(task_id) is session:
            sessions.pop(task_id,None)
            for jid in tuple(session.active):
                api_v1.update_job(jid,status="unknown",
                    stage="isolated_worker_connection_lost",
                    error="Task Chrome disconnected; delivery unknown")
                long_job_events.observe(jid,"worker_connection_lost",
                    error_code="WORKER_CONNECTION_LOST",error_stage="connection")
            # Never touch the legacy worker, other task sockets, or their
            # Chromium profiles when a single task's worker goes away.
