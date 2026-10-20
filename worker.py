"""Run byte-exact V13.1/V14 collector subprocess, sync local SQLite into Railway Postgres."""
import os,signal,sys,time,logging,subprocess,tempfile,json,shutil,threading,re,socket,ssl
from pathlib import Path
from db import session,initialize
from legacy_import import sync
logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s')
STOP=False
signal.signal(signal.SIGTERM,lambda *_:globals().__setitem__('STOP',True))
signal.signal(signal.SIGINT,lambda *_:globals().__setitem__('STOP',True))

def get_next_job():
    with session() as db:
        row=db.execute("SELECT id,source,config FROM procureflow.jobs WHERE state='queued' ORDER BY id FOR UPDATE SKIP LOCKED LIMIT 1").fetchone()
        if row:db.execute("UPDATE procureflow.jobs SET state='running',started_at=now(),message='Starting original V13.1/V14 collector' WHERE id=%s",(row['id'],))
        return row

def update(jid,**kwargs):
    keys={'current_page','checked','added','duplicates','message','last_error','state'}
    kwargs={k:v for k,v in kwargs.items() if k in keys}
    if not kwargs:return
    sql=','.join(f'{k}=%s' for k in kwargs)
    with session() as con:con.execute(f'UPDATE procureflow.jobs SET {sql} WHERE id=%s',(*kwargs.values(),jid))

def status(jid):
    with session() as db:return db.execute('SELECT state FROM procureflow.jobs WHERE id=%s',(jid,)).fetchone()

def done(jid,state,message):
    with session() as db:db.execute("UPDATE procureflow.jobs SET state=%s,message=%s,last_error=%s,finished_at=now() WHERE id=%s AND state='running'",(state,message[:500],message[:1000] if state=='failed' else '',jid))

def transport_probe(host):
    """Diagnose Railway outbound TCP/TLS separately from original browser collection."""
    started=time.monotonic()
    try:
        with socket.create_connection((host,443),timeout=7) as tcp:
            tcp.settimeout(7)
            t=time.monotonic()-started
            with ssl.create_default_context().wrap_socket(tcp,server_hostname=host) as secure:
                return f"Transport probe {host}: TCP={t:.2f}s TLS={time.monotonic()-started:.2f}s protocol={secure.version()}"
    except Exception as exc:
        return f"Transport probe {host}: {type(exc).__name__} after {time.monotonic()-started:.1f}s: {str(exc)[:150]}"

def run_job(job,base):
    jid,source,config=job['id'],job['source'],job.get('config') or {}
    probe=transport_probe("www.g2b.go.kr" if source=="g2b" else "www.k-apt.go.kr")
    logging.info('[network] %s',probe)
    update(jid,message=probe)
    days=max(1,min(365,int(config.get('days',30))))
    pages=max(1,min(500,int(config.get('pages',2))))
    # only use original executables; do not call rewritten collectors.py
    filename='g2b_headless_collect.py' if source=='g2b' else 'kapt_headless_collect.py'
    with tempfile.TemporaryDirectory(prefix='pf-legacy-') as work:
        root=Path(work);db=root/'legacy.sqlite3';report=root/'report.json';profile=root/'chrome-profile'
        args=[sys.executable,'-u',str(base/filename),'--db',str(db),'--report',str(report),
              '--profile',str(profile),'--days',str(days),'--pages',str(pages)]
        if source=='g2b':args+=['--no-seed','--progress-seconds','3','--max-seconds',str(min(3600,max(180,pages*25+100)))]
        else:
            cat=config.get('categories','both')
            val={'both':'goods,service','goods':'goods','service':'service'}.get(cat,'goods,service')
            args+=['--defaults','--categories',val]
        logging.info('JOB %s ORIGINAL %s args=%s',jid,filename,[x if x!=str(db) else '<sqlite scratch>' for x in args[3:]])
        process=subprocess.Popen(args,cwd=str(base),stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
                                 bufsize=1,text=True,encoding='utf-8',errors='replace',env={**os.environ,'PYTHONUNBUFFERED':'1'})
        messages=[];linequeue=[];lock=threading.Lock()
        def reader():
            try:
                for line in process.stdout:
                    line=line.strip()
                    with lock:linequeue.append(line)
                    logging.info('[original/%s] %s',source,line[:600])
            except Exception:logging.exception('reader failed')
        thread=threading.Thread(target=reader,daemon=True);thread.start()
        offset=0;count=0;added=0;current_page=0;latest='Starting original collector';started=time.monotonic()
        while process.poll() is None or thread.is_alive():
            time.sleep(1)
            with lock:
                lines=list(linequeue);linequeue.clear()
            for line in lines:
                if line:
                    latest=line[:300];messages.append(line)
                    if len(messages)>15:messages=messages[-15:]
                    if line.startswith('[PROGRESS]'):
                        m=re.search(r'page=(\d+)',line)
                        if m:current_page=max(current_page,int(m.group(1)))
                    if source=='kapt' and line.startswith('[PROGRESS]'):
                        current_page+=1
            try:
                offset,n,m=sync(source,db,offset);count+=n;added+=m
                update(jid,current_page=current_page,checked=count,added=added,
                        duplicates=count-added,message=latest)
            except Exception as exc:
                logging.exception('SQLite -> pgvector import error')
                latest='DB sync error: '+type(exc).__name__+': '+str(exc)
                update(jid,last_error=latest,message=latest)
            if STOP or status(jid).get('state')=='cancelled':
                process.terminate()
                try:process.wait(timeout=5)
                except subprocess.TimeoutExpired:process.kill()
                break
            if time.monotonic()-started>3800:
                process.kill();latest='Original subprocess exceeded maximum runtime';break
        thread.join(timeout=4)
        for _ in range(3):
            try:offset,n,m=sync(source,db,offset);count+=n;added+=m;break
            except Exception:time.sleep(1)
        result={}
        if report.exists():
            try:result=json.loads(report.read_text(encoding='utf-8'))
            except Exception:pass
        result_status=result.get('status','')
        error_text='; '.join(result.get('errors') or [])
        try:state=status(jid)['state']
        except Exception:state='running'
        if state=='cancelled':return
        rc=process.poll()
        if rc==0:
            done(jid,'completed',f'Original {source} done; SQLite {count}, pgvector newly added {added}; {result_status}')
        else:
            last=error_text or latest
            done(jid,'failed',f'Original {source} exit={rc}; {last}')
        update(jid,checked=count,added=added,duplicates=count-added,current_page=current_page)
        logging.info('JOB %s DONE exit=%s imported=%s added=%s status=%s',jid,rc,count,added,result_status)

def main():
    base=Path(__file__).resolve().parent / "legacy"
    if not (base / "g2b_headless_collect.py").is_file() or not (base / "kapt_headless_collect.py").is_file():
        raise RuntimeError("Original V13.1/V14 collector source missing")
    initialize()
    with session() as db:db.execute("UPDATE procureflow.jobs SET state='failed',message='Worker restarted' WHERE state='running'")
    logging.info('ORIGINAL V13.1/V14 worker ready; no port 9333')
    while not STOP:
        try:
            job=get_next_job()
            if job:
                try:run_job(job,base)
                except Exception as exc:
                    logging.exception('Job error');done(job['id'],'failed',type(exc).__name__+': '+str(exc))
            else:time.sleep(3)
        except Exception:logging.exception('Worker loop');time.sleep(5)
if __name__=='__main__':main()
