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
        row=db.execute("SELECT id,source,config FROM procureflow.jobs WHERE state='queued' AND source NOT IN ('market_daangn','market_kmong','market_soomgo') ORDER BY id FOR UPDATE SKIP LOCKED LIMIT 1").fetchone()
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
    with session() as db:db.execute("UPDATE procureflow.jobs SET state=%s,message=%s,last_error=%s,finished_at=now() WHERE id=%s AND state='running'",(state,message[:500],message[:1000] if state in ('failed','completed_partial') else '',jid))

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
        monitor=result.get('monitor') or {}
        # V13.1 reports INCOMPLETE for an intentional --pages cap, even when
        # every requested page was saved. Keep its original behavior and
        # interpret that report correctly here in the Railway adapter only.
        expected_limit=(source=='g2b' and result_status=='incomplete' and
                        int(monitor.get('batch_done') or 0)>=pages and count>0 and
                        not (monitor.get('failed_pages') or []))
        if rc==0 or expected_limit:
            label='requested page cap reached' if expected_limit else result_status
            done(jid,'completed',f'Original {source} done; SQLite {count}, pgvector newly added {added}; {label}')
        else:
            last=error_text or latest
            done(jid,'failed',f'Original {source} exit={rc}; {last}')
        update(jid,checked=count,added=added,duplicates=count-added,current_page=current_page)
        logging.info('JOB %s DONE exit=%s imported=%s added=%s status=%s',jid,rc,count,added,result_status)

def create_one_time_smoke_jobs():
    if os.getenv('RUN_SMOKE_TESTS')!='1':return
    with session() as db:
        marker='v13-v14-original-railway-smoke-20261020-v2'
        inserted=db.execute("INSERT INTO procureflow.settings(key,value) VALUES (%s,%s::jsonb) ON CONFLICT(key) DO NOTHING RETURNING key",(marker,'{"status":"queued"}')).fetchone()
        if not inserted:
            logging.info('One-time original smoke jobs already queued previously')
            return
        for source in ('g2b','kapt'):
            config={'days':2,'pages':1,'categories':'both'}
            jid=db.execute("INSERT INTO procureflow.jobs(source,config,message) VALUES (%s,%s::jsonb,%s) RETURNING id",(source,json.dumps(config,ensure_ascii=False),'Automatic original V13.1/V14 Railway smoke test')).fetchone()['id']
            logging.info('SMOKE QUEUED job=%s source=%s',jid,source)

def enqueue_scenario_validation():
    """One-time real UI-equivalent end-to-end runs after code deployment."""
    if os.getenv('RUN_SMOKE_TESTS')!='1': return
    test_cases=[
      ('g2b_smoke','g2b',{'days':2,'pages':1,'categories':'both'}),
      ('kapt_goods','kapt',{'days':2,'pages':1,'categories':'goods'}),
      ('kapt_service','kapt',{'days':2,'pages':1,'categories':'service'}),
      ('kapt_repeat','kapt',{'days':2,'pages':1,'categories':'both'}),
    ]
    with session() as db:
        marker='real-scenario-validation-20261020-v1'
        claimed=db.execute("INSERT INTO procureflow.settings(key,value) VALUES (%s,%s::jsonb) ON CONFLICT(key) DO NOTHING RETURNING key",(marker,'{"test":"original-collector-ui-equivalent"}')).fetchone()
        if not claimed:
            logging.info('Scenario validation already queued')
            return
        for name,source,config in test_cases:
            config['test_scenario']=name
            jid=db.execute("INSERT INTO procureflow.jobs(source,config,message) VALUES (%s,%s::jsonb,%s) RETURNING id",(source,json.dumps(config),f'Auto validation {name}')).fetchone()['id']
            logging.info('TEST SCENARIO QUEUED job=%s scenario=%s',jid,name)

def main():
    base=Path(__file__).resolve().parent / "legacy"
    if not (base / "g2b_headless_collect.py").is_file() or not (base / "kapt_headless_collect.py").is_file():
        raise RuntimeError("Original V13.1/V14 collector source missing")
    initialize()
    with session() as db:
        db.execute("UPDATE procureflow.jobs SET state='failed',message='Worker restarted' WHERE state='running'")
        db.execute("UPDATE procureflow.jobs SET state='cancelled',message='Excluded from ProcureFlow scope',finished_at=now() WHERE source IN ('market_daangn','market_kmong','market_soomgo') AND state='queued'")
    logging.info('ORIGINAL V13.1/V14 worker ready; no port 9333')
    if os.getenv('RUN_SMOKE_TESTS')=='1':
        # Wait for Railway's old worker replica to drain before enqueuing a
        # new job; otherwise the old replica may take the job and be SIGTERMed.
        logging.info('Waiting 20 seconds for previous Railway replica to drain')
        time.sleep(20)
        create_one_time_smoke_jobs()
        enqueue_scenario_validation()
        with session() as db:
            mark='v14-kapt-retry-after-railway-drain-20261020-v2'
            inserted=db.execute("INSERT INTO procureflow.settings(key,value) VALUES (%s,%s::jsonb) ON CONFLICT(key) DO NOTHING RETURNING key",(mark,'{"purpose":"stable-kapt-smoke"}')).fetchone()
            if inserted:
                jid=db.execute("INSERT INTO procureflow.jobs(source,config,message) VALUES ('kapt',%s::jsonb,%s) RETURNING id",(json.dumps({'days':2,'pages':1,'categories':'both'}),'Stable V14 original K-apt smoke test')).fetchone()['id']
                logging.info('STABLE KAPT SMOKE QUEUED job=%s',jid)
    if os.getenv('RUN_SITE_PROBES')=='1':
        with session() as db:
            claimed=db.execute("INSERT INTO procureflow.settings(key,value) VALUES (%s,%s::jsonb) ON CONFLICT(key) DO NOTHING RETURNING key",('site-probe-batch-20261020-v2-wishket-paths','{"state":"started"}')).fetchone()
        if claimed:
            import site_probe
            try:site_probe.run()
            except Exception:logging.exception('Headless site reconnaissance batch failed')
    if os.getenv('RUN_WISHKET_SMOKE')=='1':
        with session() as db:
            marker='wishket-smoke-v2-20261020'
            claimed=db.execute("INSERT INTO procureflow.settings(key,value) VALUES (%s,%s::jsonb) ON CONFLICT(key) DO NOTHING RETURNING key",(marker,'{"started":true}')).fetchone()
            if claimed:
                for kind in ('projects','partners','portfolios'):
                    cfg={'kind':kind,'pages':1,'limit':6}
                    jid=db.execute("INSERT INTO procureflow.jobs(source,config,message) VALUES ('wishket',%s::jsonb,%s) RETURNING id",(json.dumps(cfg),f'Wishket smoke {kind}')).fetchone()['id']
                    logging.info('WISHKET_SMOKE_QUEUED job=%s kind=%s',jid,kind)
    # One-time reconnaissance of newly requested private sources.
    with session() as db:
        claim=db.execute("INSERT INTO procureflow.settings(key,value) VALUES (%s,%s::jsonb) ON CONFLICT(key) DO NOTHING RETURNING key",
            ('market-recon-v4-20261021','{"state":"started"}')).fetchone()
    if claim:
        import market_probe
        try:market_probe.run(names=('freemoa_projects','freemoa_portfolios'))
        except Exception:logging.exception('MARKET_PROBE_BATCH_FAILED')
    # One-time Kmong Enterprise end-to-end smoke test. Actual detail records
    # are saved using the real kmong.com /enterprise/requests/<number> ID.
    # A unique database marker prevents duplicate bootstrap jobs on restarts.
    with session() as db:
        kmong_marker='kmong-enterprise-live-smoke-20261022-v2'
        claim=db.execute(
            "INSERT INTO procureflow.settings(key,value) VALUES (%s,%s::jsonb) "
            "ON CONFLICT(key) DO NOTHING RETURNING key",
            (kmong_marker,'{"state":"queued","scope":"IT project details"}')
        ).fetchone()
        if claim:
            cfg={"source":"kmong_enterprise","pages":1,"limit":10,
                 "test":"kmong-enterprise-live-smoke-20261022-v2"}
            jid=db.execute(
                "INSERT INTO procureflow.jobs(source,config,message) "
                "VALUES ('market_kmong_enterprise',%s::jsonb,%s) RETURNING id",
                (json.dumps(cfg),"Kmong Enterprise live: first 10 full project details")
            ).fetchone()["id"]
            logging.info("KMONG_ENTERPRISE_SMOKE_QUEUED job=%s",jid)
    # One-time Work24 read-only public recruitment leads smoke (no API credentials).
    # Previous obsolete work24 smoke records are not used; run a fresh job
    # with versioned marker to provide explicit detail-ID/database evidence.
    with session() as db:
        work24_marker='work24-search-terms-smoke-20261023-v2'
        claim=db.execute(
            "INSERT INTO procureflow.settings(key,value) VALUES (%s,%s::jsonb) "
            "ON CONFLICT(key) DO NOTHING RETURNING key",
            (work24_marker,'{"state":"queued","origin":"work24_public"}')
        ).fetchone()
        if claim:
            cfg={"source":"work24","pages":1,"limit":12,
                 "queries":["미화","경비","시설관리","배송","개발","청소"],
                 "test":"work24-search-terms-smoke-20261023-v2"}
            jid=db.execute(
                "INSERT INTO procureflow.jobs(source,config,message) "
                "VALUES ('market_work24',%s::jsonb,%s) RETURNING id",
                (json.dumps(cfg),"Work24 original recruitment IDs: first 10 public detail pages")
            ).fetchone()["id"]
            logging.info("WORK24_SMOKE_QUEUED job=%s",jid)
    # Verify the Railway-secret-backed login on a fresh worker deployment.
    # A separate marker prevents repeated jobs if Railway restarts replicas.
    with session() as db:
        marker="work24-three-sector-verified-search-20261023-v7"
        claim=db.execute(
            "INSERT INTO procureflow.settings(key,value) VALUES (%s,%s::jsonb) "
            "ON CONFLICT(key) DO NOTHING RETURNING key",
            (marker,'{"state":"queued","purpose":"login and public detail smoke"}')
        ).fetchone()
        if claim:
            cfg={"source":"work24","pages":1,"limit":12,
                 "queries":["미화","경비","개발"],
                 "test":marker}
            jid=db.execute(
                "INSERT INTO procureflow.jobs(source,config,message) "
                "VALUES ('market_work24',%s::jsonb,%s) RETURNING id",
                (json.dumps(cfg,ensure_ascii=False),"Work24 Railway env credential login smoke")
            ).fetchone()["id"]
            logging.info("WORK24_LOGIN_SMOKE_QUEUED job=%s",jid)
    # One-time end-to-end execution of all new adapters (bounded public pages).
    with session() as db:
        claimed=db.execute("INSERT INTO procureflow.settings(key,value) VALUES (%s,%s::jsonb) ON CONFLICT(key) DO NOTHING RETURNING key",
            ('market-smoke-v3-20261021','{"state":"queued"}')).fetchone()
        if claimed:
            for site in ('freemoa','freemoa_partners','freemoa_portfolios','wanted_gigs'):
                cfg={'source':site,'pages':2,'limit':4,'test':'market-smoke-v3'}
                jid=db.execute("INSERT INTO procureflow.jobs(source,config,message) VALUES (%s,%s::jsonb,%s) RETURNING id",
                    ('market_'+site,json.dumps(cfg),f'Initial {site} real public-source test')).fetchone()['id']
                logging.info('MARKET_SMOKE_QUEUED job=%s source=%s',jid,site)
    # One-time public G2B opening page verification, no service key.
    # These are publicly observed real bid identifiers, not procurement
    # announcements, and the test is read-only.
    with session() as db:
        marker="g2b-opening-verified-dedup-20261023-v10"
        claimed=db.execute(
            "INSERT INTO procureflow.settings(key,value) VALUES (%s,%s::jsonb) "
            "ON CONFLICT(key) DO NOTHING RETURNING key",
            (marker,'{"status":"queued","source":"public_g2b_web"}')
        ).fetchone()
        if claimed:
            cfg={"pages":2,"days":3,
                 "categories":["goods","service"],
                 "kinds":["opening","award"],"test":marker}
            jid=db.execute(
                "INSERT INTO procureflow.jobs(source,config,message) "
                "VALUES ('g2b_bid_results',%s::jsonb,%s) RETURNING id",
                (json.dumps(cfg,ensure_ascii=False),
                 "G2B public WebSquare opening result smoke test")
            ).fetchone()["id"]
            logging.info("G2B_BID_WEB_SMOKE_QUEUED job=%s",jid)
    while not STOP:
        try:
            job=get_next_job()
            if job:
                try:
                    if job['source']=='g2b_bid_results':
                        import g2b_bid_collector
                        cfg=job.get('config') or {}
                        result=g2b_bid_collector.collect(
                            days=cfg.get('days',7),pages=cfg.get('pages',1),
                            categories=cfg.get('categories') or ['goods','service'],
                            kinds=cfg.get('kinds') or ['award','opening'],
                            bid_numbers=cfg.get('bid_numbers') or None)
                        update(job['id'],checked=result['examined'],added=result['new'],
                               duplicates=result['saved']-result['new'],
                               message=json.dumps(result,ensure_ascii=False)[:450])
                        job_state=('completed' if result['status']=='collected'
                                   else 'completed_partial' if result['status']=='partial'
                                   else 'failed')
                        done(job['id'],job_state,json.dumps(result,ensure_ascii=False))
                        logging.info('G2B_BID_JOB_RESULT %s',json.dumps(result,ensure_ascii=False)[:3500])
                    elif job['source']=='wishket':
                        import wishket_collector
                        cfg=job.get('config') or {}
                        result=wishket_collector.collect(kind=cfg.get('kind','portfolios'),pages=cfg.get('pages',2),limit=cfg.get('limit',30))
                        update(job['id'],checked=result['saved'],added=result['saved'],message=json.dumps(result,ensure_ascii=False)[:450])
                        done(job['id'],'completed' if not result['errors'] else 'failed',json.dumps(result,ensure_ascii=False))
                        logging.info('WISHKET_JOB_RESULT %s',json.dumps(result,ensure_ascii=False))
                    elif job['source'].startswith('market_'):
                        import market_collector
                        cfg=job.get('config') or {}
                        site=job['source'][len('market_'):]
                        result=market_collector.run(site,pages=cfg.get('pages',1),limit=cfg.get('limit',8),queries=cfg.get('queries'))
                        with session() as db:
                            db.execute("""INSERT INTO procureflow.settings(key,value) VALUES (%s,%s::jsonb)
                                ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value,updated_at=now()""",
                                ('market-result:'+site,json.dumps(result,ensure_ascii=False)))
                        update(job['id'],checked=result['examined'],added=result['new'],
                            duplicates=result['saved']-result['new'],
                            message=json.dumps(result,ensure_ascii=False)[:450])
                        done(job['id'],'completed' if result['status']=='collected' else 'failed',json.dumps(result,ensure_ascii=False))
                        logging.info('MARKET_JOB_RESULT %s',json.dumps(result,ensure_ascii=False)[:3000])
                    else:run_job(job,base)
                except Exception as exc:
                    logging.exception('Job error');done(job['id'],'failed',type(exc).__name__+': '+str(exc))
            else:time.sleep(3)
        except Exception:logging.exception('Worker loop');time.sleep(5)
if __name__=='__main__':main()
