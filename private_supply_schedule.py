"""Durable incremental public portfolio and partner collection, in the existing Worker.

No guessing login-gated profile content. Each collection source has its own
PostgreSQL cursor, last result, and bounded recurrence. Jobs survive redeploys.
"""
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from db import session

KST=timezone(timedelta(hours=9))
PREFIX="private:schedule:"
SOURCES={
    "wishket_portfolios":{"source":"wishket","cfg":{"kind":"portfolios","pages":2,"limit":36},"initial_page":3},
    "freemoa_partners":{"source":"market_freemoa_partners","cfg":{"pages":1,"limit":12},"initial_page":2},
    "freemoa_portfolios":{"source":"market_freemoa_portfolios","cfg":{"pages":1,"limit":12},"initial_page":2},
}
CHECK_INTERVAL_MINUTES=30
CYCLE_REFRESH_HOURS=12


def _read(db,key):
    row=db.execute("SELECT value FROM procureflow.settings WHERE key=%s",(key,)).fetchone()
    return row["value"] if row else {}


def _write(db,key,value):
    db.execute("""INSERT INTO procureflow.settings(key,value)
                  VALUES (%s,%s::jsonb)
                  ON CONFLICT(key) DO UPDATE
                  SET value=excluded.value,updated_at=now()""",
               (key,json.dumps(value,ensure_ascii=False)))


def tick():
    if os.getenv("PRIVATE_SUPPLY_AUTO_COLLECT","1")!="1":
        return None
    now=datetime.now(KST)
    with session() as db:
        lock=db.execute("SELECT pg_try_advisory_xact_lock(20261024,8102) AS ok").fetchone()
        if not lock["ok"]:return None
        source_ids=tuple(x["source"] for x in SOURCES.values())
        # A manual scrape should not cause parallel execution against the
        # same public provider; do not block on unrelated government jobs.
        busy=db.execute("""
            SELECT id FROM procureflow.jobs
            WHERE source IN (%s,%s,%s)
              AND (state='queued' OR
                   (state='running' AND started_at>now()-interval '90 minutes'))
            LIMIT 1
        """,source_ids).fetchone()
        if busy:return None
        options=[]
        for kind,site in SOURCES.items():
            key=PREFIX+kind
            state=_read(db,key)
            last=state.get("last_queued")
            if last:
                try:
                    lag=(now-datetime.fromisoformat(last)).total_seconds()
                except (ValueError,TypeError):lag=10**9
                min_secs=(CYCLE_REFRESH_HOURS*3600 if state.get("cycle_complete")
                          else CHECK_INTERVAL_MINUTES*60)
                if lag<min_secs:
                    continue
            options.append((last or "1970-01-01T00:00:00+09:00",kind,key,site,state))
        if not options:return None
        _,kind,key,site,state=min(options,key=lambda row:row[0])
        cursor=int(state.get("next_page") or site["initial_page"])
        cfg={**site["cfg"],"page_start":max(1,min(cursor,100000)),
             "schedule_key":key,"scheduled_at":now.isoformat()}
        jid=db.execute("""
            INSERT INTO procureflow.jobs(source,config,message)
            VALUES (%s,%s::jsonb,%s) RETURNING id
        """,(site["source"],json.dumps(cfg),
             "Public private-sector partner/portfolio incremental detail collection")
        ).fetchone()["id"]
        _write(db,key,{**state,"last_queued":now.isoformat(),
                       "last_job":jid,"last_state":"queued"})
        logging.info("PRIVATE_SUPPLY_SCHEDULED job=%s kind=%s page=%s",
                     jid,kind,cfg["page_start"])
        return jid


def finished(job,result):
    cfg=job.get("config") or {}
    key=cfg.get("schedule_key")
    if key not in (PREFIX+x for x in SOURCES):return
    now=datetime.now(KST)
    with session() as db:
        state=_read(db,key)
        if state.get("last_job")!=job["id"]:
            logging.warning("PRIVATE_SUPPLY_STALE_RESULT job=%s current=%s",
                            job["id"],state.get("last_job"))
            return
        good=result.get("status") in ("collected","empty","partial")
        errors=result.get("errors") or []
        saved=int(result.get("saved") or 0)
        successful=good and (saved>0 or not errors)
        first_page=int(cfg.get("page_start") or 1)
        last_page=int(result.get("last_page") or first_page)
        fp=result.get("page_fingerprint") or ""
        repeated=bool(fp and fp==state.get("last_fingerprint")
                      and first_page>1)
        has_more=bool(result.get("has_more")) and not repeated
        new_state={**state,"last_finished":now.isoformat(),
                   "last_state":result.get("status"),
                   "last_saved":saved,"last_new":int(result.get("new") or 0),
                   "last_errors":errors[:5],
                   "last_page":last_page,
                   "last_fingerprint":fp or state.get("last_fingerprint","")}
        if successful:
            new_state["cycle_complete"]=not has_more
            new_state["next_page"]=last_page+1 if has_more else 1
            if not has_more:new_state["cycle_completed_at"]=now.isoformat()
        else:
            new_state["cycle_complete"]=False
            new_state["next_page"]=first_page
        _write(db,key,new_state)
        logging.info("PRIVATE_SUPPLY_SCHEDULE_RESULT job=%s kind=%s saved=%s new=%s status=%s next_page=%s cycle_complete=%s",
                     job["id"],key.split(":")[-1],saved,new_state["last_new"],
                     new_state["last_state"],new_state["next_page"],
                     new_state["cycle_complete"])


def status():
    with session() as db:
        rows=db.execute("""SELECT key,value,updated_at FROM procureflow.settings
                           WHERE key LIKE %s ORDER BY key""",
                        (PREFIX+"%",)).fetchall()
    return {"enabled":os.getenv("PRIVATE_SUPPLY_AUTO_COLLECT","1")=="1",
            "check_interval_minutes":CHECK_INTERVAL_MINUTES,
            "cycle_refresh_hours":CYCLE_REFRESH_HOURS,
            "sources":[{"key":r["key"],"state":r["value"],
                        "updated_at":r["updated_at"]} for r in rows]}
