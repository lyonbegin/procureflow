"""Railway background worker. Same Railway project/database, no Chrome port 9333."""
import logging,os,signal,time,traceback
from db import initialize,session
from collectors import g2b,kapt
logging.basicConfig(level=logging.INFO,format="%(asctime)s %(levelname)s %(message)s")
STOP=False
def shutdown(*_):
    global STOP
    STOP=True
signal.signal(signal.SIGTERM,shutdown)
signal.signal(signal.SIGINT,shutdown)
def get_next_job():
    with session() as db:
        row=db.execute("""SELECT id,source,config FROM procureflow.jobs
         WHERE state='queued' ORDER BY id ASC FOR UPDATE SKIP LOCKED LIMIT 1""").fetchone()
        if row:
            db.execute("""UPDATE procureflow.jobs SET state='running',started_at=now(),
            message='Launching independent Headless Chromium' WHERE id=%s""",(row["id"],))
        return row
def finish(jid,state,message):
    with session() as db:
        db.execute("""UPDATE procureflow.jobs SET state=%s,finished_at=now(),
        message=%s,last_error=CASE WHEN %s='failed' THEN %s ELSE last_error END
        WHERE id=%s AND state='running'""",(state,message[:500],state,message[:1500],jid))
def work():
    while not STOP:
        job=None
        try:
            job=get_next_job()
            if job:
                logging.info("job=%s source=%s started",job['id'],job['source'])
                try:
                    action={'g2b':g2b,'kapt':kapt}[job['source']]
                    result=action(job['id'],job.get('config') or {})
                    finish(job['id'],'completed' if result is not None else 'cancelled',
                           str(result or 'Cancelled'))
                    logging.info("job=%s done %s",job['id'],result)
                except Exception as e:
                    message=type(e).__name__+': '+str(e)
                    logging.exception("job=%s failed",job['id'])
                    finish(job['id'],'failed',message)
            else:time.sleep(4)
        except Exception:
            logging.exception("worker: DB connection / processing error")
            time.sleep(10)
if __name__=="__main__":
    initialize()
    with session() as con:
        con.execute("""UPDATE procureflow.jobs SET state='failed',
        message='Worker restarted before completion',last_error='Worker restarted',
        finished_at=now() WHERE state='running'""")
    logging.info("ProcureFlow Headless worker online, no remote debugging port")
    work()
