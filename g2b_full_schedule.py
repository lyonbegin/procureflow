"""Continuous, low-volume official G2B selected-case progress scheduler.

Schedules actual official tender discovery and monthly exact category history
ONLY when the authorized public data service key exists. Keeps one worker job
at a time, all work idempotent, no LLM and no bid submission.
"""
from __future__ import annotations
from datetime import datetime,timedelta,timezone
import json,logging
from g2b_official_notices import api_key

KEY="g2b:full:scheduled"
LOCK1,LOCK2=20261024,104

def tick(session):
    with session() as c:
        lock=c.execute("SELECT pg_try_advisory_xact_lock(%s,%s) AS ok",
                       (LOCK1,LOCK2)).fetchone()
        if not lock["ok"]:return {"status":"already_scheduling"}
        active=c.execute("""SELECT id FROM procureflow.jobs
              WHERE source='g2b_full_case' AND state IN ('running','queued')
              LIMIT 1""").fetchone()
        if active:return {"status":"job_active","job_id":active["id"]}
        row=c.execute("""SELECT value FROM procureflow.settings WHERE key=%s""",
                    (KEY,)).fetchone()
        state=row["value"] if row else {}
        now=datetime.now(timezone.utc)
        last=state.get("last_queued")
        if last:
            try:
                if (now-datetime.fromisoformat(last)).total_seconds()<300:
                    return {"status":"not_due"}
            except (ValueError,TypeError):pass
        waiting=c.execute("""SELECT count(*) AS n
             FROM procureflow.g2b_case_10yr_windows
             WHERE case_bid_no='R26BK01787028' AND status<>'completed'""").fetchone()["n"]
        recent=state.get("last_discovery")
        discovery_due=True
        if recent:
            try:
                discovery_due=(now-datetime.fromisoformat(recent))>=timedelta(hours=2)
            except (ValueError,TypeError):pass
        if not api_key():
            # Public code-validated index can progress without the DATA_GO_KR key,
            # but it does NOT mark the 121 official month windows as completed.
            public=c.execute("""SELECT value FROM procureflow.settings
               WHERE key='g2b:single:81111599:secondary_index_cursor'""").fetchone()
            public_state=public["value"] if public else {}
            if public_state.get("exhausted"):
                return {"status":"secondary_index_exhausted",
                        "official_ten_year_unverified":True}
            phase="ten_year"
            origin="secondary_category_fallback"
        else:
            phase="discover" if discovery_due else "ten_year" if waiting else "notice"
            origin="official_schedule"
        meta={"bid_no":"R26BK01787028","phase":phase,"origin":origin}
        job_id=c.execute("""INSERT INTO procureflow.jobs(source,config,message)
           VALUES ('g2b_full_case',%s::jsonb,%s) RETURNING id""",
           (json.dumps(meta),"Selected G2B 81111599 category automatic scheduler")).fetchone()["id"]
        state.update({"last_queued":now.isoformat(),"last_phase":phase,
                      "last_job":job_id})
        if phase=="discover":state["last_discovery"]=now.isoformat()
        c.execute("""INSERT INTO procureflow.settings(key,value)
            VALUES(%s,%s::jsonb) ON CONFLICT(key) DO UPDATE SET
              value=excluded.value,updated_at=now()""",
            (KEY,json.dumps(state)))
    logging.info("G2B_FULL_SCHEDULE job=%s phase=%s",job_id,phase)
    return {"status":"queued","job_id":job_id,"phase":phase}
