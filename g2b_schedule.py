"""PostgreSQL-backed bounded G2B periodic refresh and historical backfill.

The existing Railway Worker owns this scheduler (no new service or secrets).
Every one-day history cursor has a stable date + page; it is advanced only
when a completed real crawl reports coverage. Failure leaves cursor in place.
"""
from datetime import datetime,date,timedelta
import json
import logging
import os
from g2b_date_windows import KST

SOURCES={"opening":"g2b_bid_results","award":"g2b_final_awards"}
PREFIX="g2b:schedule:"
# Conservative defaults keep public WebSquare traffic bounded.
REFRESH_HOURS=6
BACKFILL_MINUTES=20
EARLIEST=date.fromisoformat(os.getenv("G2B_BACKFILL_EARLIEST","2024-01-01"))


def config(kind,mode,cursor=None,now=None):
    now=now or datetime.now(KST)
    today=now.date()
    if mode=="recent":
        start=today-timedelta(days=2 if kind=="opening" else 7)
        end=today
        page=1
    else:
        cursor=cursor or {}
        first=today-timedelta(days=8)
        start=date.fromisoformat(cursor.get("cursor_date") or first.isoformat())
        end=start
        page=max(1,int(cursor.get("cursor_page") or 1))
    cfg={"days":(end-start).days or 1,
         "start_date":start.isoformat(),"end_date":end.isoformat(),
         "page_start":page,"pages":2}
    if kind=="award":
        cfg["limit"]=40
    else:
        cfg["categories"]=["goods","service"]
        cfg["kinds"]=["opening","award"]
    return cfg


def next_backfill_cursor(job_config,result):
    """Keep scanning pages of same day until the last result page is short."""
    start=date.fromisoformat(job_config["start_date"])
    if result.get("has_more"):
        return {"cursor_date":start.isoformat(),
                "cursor_page":max(1,int(result.get("last_page") or
                                        job_config["page_start"])+1)}
    return {"cursor_date":(start-timedelta(days=1)).isoformat(),
            "cursor_page":1}


def _read(con,key):
    row=con.execute("SELECT value FROM procureflow.settings WHERE key=%s",(key,)).fetchone()
    return row["value"] if row else {}


def _write(con,key,value):
    con.execute("""INSERT INTO procureflow.settings(key,value)
                   VALUES (%s,%s::jsonb)
                   ON CONFLICT(key) DO UPDATE SET value=excluded.value,
                                                  updated_at=now()""",
                (key,json.dumps(value,ensure_ascii=False)))


def tick(session,now=None):
    """Schedule at most one bounded job and do not steal a busy worker.

    PostgreSQL advisory transaction lock prevents duplicate enqueues on
    simultaneous Worker replicas. Recorded last_queued makes deployment
    restarts safe.
    """
    now=now or datetime.now(KST)
    if os.getenv("G2B_AUTO_COLLECT","1")!="1":
        return None
    with session() as db:
        claimed=db.execute(
            "SELECT pg_try_advisory_xact_lock(20261023,7311) AS claimed").fetchone()
        if not claimed["claimed"]:return None
        # Reconcile a verified successful crawl whose Worker state was
        # incorrectly overwritten by an overlapping Railway deployment.
        # A missing finished_at plus a persisted collected checkpoint is
        # required, so legitimate failed jobs stay failed.
        repaired=db.execute("""
            UPDATE procureflow.jobs j
            SET state='completed',finished_at=s.updated_at,
                message='Recovered from verified successful G2B scheduler checkpoint',
                last_error=''
            FROM procureflow.settings s
            WHERE s.key LIKE 'g2b:schedule:%'
              AND j.id=(s.value->>'last_job')::bigint
              AND j.state='failed' AND j.finished_at IS NULL
              AND s.value->>'last_state' IN ('collected','empty')
            RETURNING j.id
        """).fetchall()
        if repaired:
            logging.info("G2B_SCHEDULER_RECONCILED jobs=%s",
                         [x["id"] for x in repaired])
        active=db.execute("""
           SELECT id FROM procureflow.jobs
           WHERE source IN ('g2b_bid_results','g2b_final_awards')
             AND state IN ('queued','running')
           LIMIT 1
        """).fetchone()
        if active:return None
        # Recent refresh first when due; history sources rotate by interval.
        options=[]
        for mode in ("recent","backfill"):
            for kind in ("opening","award"):
                key=PREFIX+mode+":"+kind
                state=_read(db,key)
                hours=REFRESH_HOURS if mode=="recent" else BACKFILL_MINUTES/60
                last=state.get("last_queued")
                if last:
                    try:
                        lag=(now-datetime.fromisoformat(last)).total_seconds()
                    except (ValueError,TypeError):lag=999999
                    if lag<hours*3600:
                        continue
                if mode=="backfill":
                    cursor=state
                    first=(now.date()-timedelta(days=8))
                    cursor_day=date.fromisoformat(cursor.get("cursor_date") or
                                                 first.isoformat())
                    if cursor_day<EARLIEST:continue
                cfg=config(kind,mode,state,now)
                options.append((mode,kind,key,cfg,state))
        if not options:return None
        # Recent has priority once due; backfill prefers the least-recently
        # scheduled type, so opening cannot starve awards.
        options.sort(key=lambda x:(
            0 if x[0]=="recent" else 1,
            x[4].get("last_queued") or "1970-01-01T00:00:00+09:00"))
        mode,kind,key,cfg,state=options[0]
        cfg.update({"scheduler_key":key,"scheduler_mode":mode,"scheduler_kind":kind})
        jid=db.execute("""
            INSERT INTO procureflow.jobs(source,config,message)
            VALUES (%s,%s::jsonb,%s) RETURNING id
        """,(SOURCES[kind],json.dumps(cfg),f"G2B scheduled {mode} {kind} web collection")
        ).fetchone()["id"]
        _write(db,key,{**state,"last_queued":now.isoformat(),
                       "last_job":jid,"last_state":"queued"})
        logging.info("G2B_SCHEDULED job=%s mode=%s kind=%s dates=%s..%s page=%s",
                     jid,mode,kind,cfg["start_date"],cfg["end_date"],cfg["page_start"])
        return jid


def finished(session,job,result,now=None):
    """Advance only a completed job that owns the currently tracked marker."""
    cfg=job.get("config") or {}
    key=cfg.get("scheduler_key")
    if not key or not key.startswith(PREFIX):return
    now=now or datetime.now(KST)
    ok=result.get("status") in ("collected","empty")
    with session() as db:
        state=_read(db,key)
        if state.get("last_job")!=job["id"]:
            logging.warning("G2B_SCHEDULER_STALE job=%s expected=%s",job["id"],state.get("last_job"))
            return
        state["last_finished"]=now.isoformat()
        state["last_state"]=result.get("status","error")
        state["last_saved"]=int(result.get("saved") or 0)
        state["last_new"]=int(result.get("new") or 0)
        state["last_errors"]=(result.get("errors") or [])[:3]
        if ok and cfg.get("scheduler_mode")=="backfill":
            state.update(next_backfill_cursor(cfg,result))
        _write(db,key,state)
        logging.info("G2B_SCHEDULE_RESULT job=%s result=%s backfill_cursor=%s page=%s",
                     job["id"],result.get("status"),state.get("cursor_date"),
                     state.get("cursor_page"))


def status(session):
    with session() as db:
        rows=db.execute("""
            SELECT key,value,updated_at
            FROM procureflow.settings
            WHERE key LIKE %s ORDER BY key
        """,(PREFIX+"%",)).fetchall()
    return [{"key":r["key"],"state":r["value"],"updated_at":r["updated_at"]}
            for r in rows]
