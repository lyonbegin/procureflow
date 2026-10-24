"""Periodic genuine K-apt public goods/services notice refresh.

Independent of the G2B bid-result scheduler and procurement-request collector.
Queue actual existing V14 headless collector; never pretend queued = refreshed.
Postgres transaction advisory lock prevents simultaneous Railway workers duplicating jobs.
"""
import json
import logging

LOCK_ID = 2401024
MARKER = "kapt:schedule:recent_public_goods_services"
CADENCE_SQL = "interval '30 minutes'"

def tick(session):
    with session() as db:
        held=db.execute("SELECT pg_try_advisory_xact_lock(%s) AS ok",(LOCK_ID,)).fetchone()
        if not held["ok"]:
            return {"state":"locked"}
        last=db.execute("SELECT updated_at FROM procureflow.settings WHERE key=%s",(MARKER,)).fetchone()
        if last:
            too_soon=db.execute(
                "SELECT %s::timestamptz > now() - interval '30 minutes' AS too_soon",
                (last["updated_at"],)).fetchone()
            if too_soon["too_soon"]:
                return {"state":"interval"}
        active=db.execute("""
            SELECT id,state FROM procureflow.jobs
            WHERE source='kapt' AND state IN ('queued','running')
            ORDER BY id DESC LIMIT 1
        """).fetchone()
        if active:
            return {"state":"already_queued","job_id":active["id"]}
        config={"days":7,"pages":2,"categories":"both",
                "scheduler_kind":"recent_public_tender_notices",
                "scheduler_id":MARKER}
        jid=db.execute("""
            INSERT INTO procureflow.jobs(source,config,message)
            VALUES ('kapt',%s::jsonb,'Scheduled K-apt public goods/service notice refresh')
            RETURNING id
        """,(json.dumps(config,ensure_ascii=False),)).fetchone()["id"]
        db.execute("""
            INSERT INTO procureflow.settings(key,value)
            VALUES (%s,%s::jsonb)
            ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value,updated_at=now()
        """,(MARKER,json.dumps({"job_id":jid,"kind":"recent_public_tender_notices",
                                  "cadence_minutes":30,"days":7,"pages":2})))
        logging.info("PROCUREFLOW_KAPT_RECENT_NOTICE_REFRESH_QUEUED job=%s",jid)
        return {"state":"queued","job_id":jid}
