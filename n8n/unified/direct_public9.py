"""In-process one-click nine-stage G2B preparation, NO collector/Worker daemon.

Only a browser-initiated, exact one-tender operation; uses existing operational
PostgreSQL for durable step/run IDs and review DOCX.  Never queues jobs or starts
Chrome, Playwright, official G2B crawling, bidding, signatures or participation.
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
from pathlib import Path

from db import session
from g2b_public_workflow import read_actual_job, latest_actual_job
from procurement_auto_test import approved_filter, CASE, DETAIL, FLOW

LOCK=threading.Lock()
_active_job: int|None=None
log=logging.getLogger("unified.public9")

def _ready():
    if os.environ.get("PROCUREFLOW_DIRECT_PUBLIC9_ENABLED","0")!="1":
        raise RuntimeError("DIRECT_9_STAGE_DISABLED_IN_RAILWAY")
    if not os.environ.get("DATABASE_URL"):
        raise RuntimeError("DIRECT_9_STAGE_REQUIRES_DATABASE_URL")

def _saved_filter(sid,db_path,fixture_path):
    with sqlite3.connect(db_path,timeout=8) as db:
        row=db.execute("SELECT payload FROM snapshots WHERE sid=? AND path=?",(sid,FLOW)).fetchone()
    doc=json.loads(row[0]) if row else json.loads(fixture_path(FLOW).read_text())
    return approved_filter(doc)

def start(sid,db_path,fixture_path,payload):
    """Directly run selected tender only; one active run per service/DB."""
    global _active_job
    if type(payload) is not dict or payload!={"bid_no":CASE,"detail10":DETAIL}:
        raise ValueError("ONLY_PINNED_SELECTED_TENDER_ALLOWED")
    _ready()
    f=_saved_filter(sid,db_path,fixture_path)
    config={"bid_no":CASE,"detail10":DETAIL,"start":f["start"],
            "end":f["end"],"agency":f["agency"]}
    with LOCK:
        if _active_job is not None:
            raise ValueError("DIRECT_NINE_STAGE_RUN_ALREADY_ACTIVE")
        with session() as con:
            running=con.execute("""SELECT id FROM procureflow.jobs
                  WHERE source='g2b_public_direct' AND state='running'
                  AND started_at > now()-interval '30 minutes' LIMIT 1""").fetchone()
            if running:
                raise ValueError("DIRECT_NINE_STAGE_DB_RUN_ALREADY_ACTIVE")
            row=con.execute("""INSERT INTO procureflow.jobs
                  (source,state,config,message,started_at)
                  VALUES ('g2b_public_direct','running',%s::jsonb,
                          'Studio direct nine-stage preparation: NO Worker',
                          now()) RETURNING id""",(json.dumps(config),)).fetchone()
            job_id=int(row["id"])
        _active_job=job_id
        thread=threading.Thread(target=_execute,args=(job_id,config),
                                name="procureflow-direct-9",daemon=True)
        try:thread.start()
        except BaseException:
            _active_job=None
            with session() as con:
                con.execute("""UPDATE procureflow.jobs SET state='failed',
                   last_error='DIRECT_EXECUTION_THREAD_START_FAILED',finished_at=now()
                   WHERE id=%s AND source='g2b_public_direct'""",(job_id,))
            raise
    return {"job_id":job_id,"job_state":"running","source":"unified_inprocess_public9",
            "actual_stages_recorded":0,"case_bid_no":CASE,
            "worker_executed":False,"automatic_collection_started":False,
            "bid_submitted":False,"electronic_signature":False}

def _execute(job_id,config):
    global _active_job
    try:
        from g2b_public_workflow import run_actual_public_case
        outcome=run_actual_public_case(job_id,config,read_only_history=True,
                                        job_source="g2b_public_direct")
        state="failed" if outcome["errors"] else "completed_partial"
        with session() as con:
            con.execute("""UPDATE procureflow.jobs SET state=%s,checked=%s,
                message=%s,last_error=%s,finished_at=now()
                WHERE id=%s AND source='g2b_public_direct'""",
                (state,int(outcome["actual_worker_stages"]),
                 json.dumps({"status":outcome["status"],
                             "stages":outcome["actual_worker_stages"],
                             "source":"unified_inprocess_public9",
                             "draft_generated":outcome["draft_generated"],
                             "bid_submitted":False},ensure_ascii=False)[:500],
                 "ONE_OR_MORE_STAGES_FAILED" if outcome["errors"] else "",job_id))
        log.info("DIRECT_9_STAGE_DONE job_id=%s state=%s stages=%s",
                 job_id,state,outcome["actual_worker_stages"])
    except Exception as exc:
        log.exception("DIRECT_9_STAGE_FAILED job_id=%s",job_id)
        try:
            with session() as con:
                con.execute("""UPDATE procureflow.jobs
                     SET state='failed',last_error=%s,finished_at=now()
                     WHERE id=%s AND source='g2b_public_direct'""",
                    (type(exc).__name__+":"+str(exc)[:320],job_id))
        except Exception:log.exception("DIRECT_9_STAGE_JOB_FAILURE_LOG_UNAVAILABLE")
    finally:
        with LOCK:
            if _active_job==job_id:_active_job=None

def job(job_id):
    _ready()
    result=read_actual_job(int(job_id))
    if result.get("execution_source")!="unified_direct":
        raise ValueError("NOT_A_DIRECT_NINE_STAGE_RUN")
    return {**result,"worker_executed":False,
            "automatic_collection_started":False,"bid_submitted":False}

def latest():
    _ready()
    result=latest_actual_job()
    if result.get("execution_source")!="unified_direct":
        return {"job_state":"not_run","last_job_id":None,
                "case_bid_no":CASE,"actual_stages_recorded":0,
                "worker_executed":False,"bid_submitted":False}
    return {**result,"worker_executed":False,
            "automatic_collection_started":False,"bid_submitted":False}
