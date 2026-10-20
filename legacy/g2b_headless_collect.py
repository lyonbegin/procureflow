#!/usr/bin/env python3
"""G2B production collector: launches Chrome itself (no CDP port 9333).

Run inside existing ProcureFlow folder to use its existing g2b.sqlite3, or set --db.
This collector does not submit bids or interact with suppliers.
"""
from __future__ import annotations
import argparse
import datetime as dt
import json
import os
import sqlite3
import sys
import time
import traceback
from pathlib import Path
import g2b_prod_bridge as bridge
import g2b_prod_nav as nav

KST = dt.timezone(dt.timedelta(hours=9))
HERE = Path(__file__).resolve().parent

def now(): return dt.datetime.now(KST).isoformat(timespec='seconds')

def month_shift(date, n):
    y = date.year + (date.month - 1 + n)//12
    m = (date.month - 1 + n)%12 + 1
    return f'{y:04d}{m:02d}'

def init_db(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path, timeout=30) as db:
        db.execute('PRAGMA busy_timeout=30000')
        db.execute('PRAGMA journal_mode=WAL')
        db.executescript('''
CREATE TABLE IF NOT EXISTS oder_requests (
 request_no TEXT PRIMARY KEY,
 title TEXT NOT NULL DEFAULT '',
 agency TEXT NOT NULL DEFAULT '',
 category TEXT NOT NULL DEFAULT '',
 budget INTEGER NOT NULL DEFAULT 0,
 procurement TEXT NOT NULL DEFAULT '',
 contract_method TEXT NOT NULL DEFAULT '',
 request_date TEXT NOT NULL DEFAULT '',
 order_month TEXT NOT NULL DEFAULT '',
 bid_linked INTEGER NOT NULL DEFAULT 0,
 spec_linked INTEGER NOT NULL DEFAULT 0,
 raw_json TEXT NOT NULL DEFAULT '{}',
 source_url TEXT NOT NULL DEFAULT 'https://www.g2b.go.kr/',
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_oderreq_date ON oder_requests(request_date);
CREATE INDEX IF NOT EXISTS idx_oderreq_category ON oder_requests(category);
''')

def snapshot(db_file):
    with sqlite3.connect(db_file, timeout=30) as con:
        total = con.execute('SELECT COUNT(*) FROM oder_requests').fetchone()[0]
        cats = con.execute('SELECT category,COUNT(*) FROM oder_requests GROUP BY category').fetchall()
    return dict(total=total, by_category={k:v for k,v in cats})

def merge_captured_snapshot(db_file):
    """Merge 57 genuinely captured G2B rows from user-supplied 2026-10-19 JSON.

    They are explicitly historical. Never count them as live collection.
    """
    seed=HERE/'g2b_real_sample_20261019.sqlite3'
    if not seed.exists():
        return 0
    fields=('request_no','title','agency','category','budget','procurement','contract_method',
            'request_date','order_month','bid_linked','spec_linked','raw_json','source_url',
            'created_at','updated_at')
    clause=','.join(fields)
    placeholder=','.join('?' for _ in fields)
    with sqlite3.connect(seed, timeout=30) as inp:
        rows=inp.execute('SELECT '+clause+' FROM oder_requests').fetchall()
    added=0
    with sqlite3.connect(db_file, timeout=30) as out:
        for row in rows:
            cur=out.execute('INSERT INTO oder_requests ('+clause+') VALUES ('+placeholder+') '
                            'ON CONFLICT(request_no) DO NOTHING',row)
            added+=cur.rowcount
    return added

class Writer:
    def __init__(self, path):
        self.path=path
        self.calls=0
        self.stats={'added':0, 'skipped':0, 'filtered':0, 'updated':0}
        self.bad_categories={}
    def __call__(self, response, source):
        added=skipped=filtered=0
        stamp=now()
        with sqlite3.connect(self.path, timeout=30) as db:
            db.execute('PRAGMA busy_timeout=30000')
            for item in response['items']:
                code=str(item.get('category_code') or '').strip()
                if code not in bridge.ALLOWED_CATEGORIES:
                    filtered+=1
                    self.bad_categories[code]=self.bad_categories.get(code,0)+1
                    continue
                # The code, not free-text category label, identifies the product type.
                cat='물품' if code=='01' else '일반용역'
                if not item.get('request_no'):
                    filtered+=1
                    continue
                cur=db.execute('''INSERT INTO oder_requests
(request_no,title,agency,category,budget,procurement,contract_method,
 request_date,order_month,bid_linked,spec_linked,raw_json,created_at,updated_at)
VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(request_no) DO NOTHING''',
                   (item['request_no'],item['title'],item['agency'],cat,item['budget'],
                    item['procurement'],item['contract'],item['request_date'],item['order_month'],
                    int(item['bid_linked']),int(item['spec_linked']),item['raw_json'],stamp,stamp))
                if cur.rowcount==1:added+=1
                else:skipped+=1
        self.calls+=1
        self.stats['added']+=added
        self.stats['skipped']+=skipped
        self.stats['filtered']+=filtered
        return dict(added=added,updated=0,skipped=skipped,filtered=filtered)

def run(args):
    db_file=Path(args.db).expanduser().resolve()
    init_db(db_file)
    initial_snapshot=snapshot(db_file)
    historical_added=0 if args.no_seed else merge_captured_snapshot(db_file)
    today=dt.datetime.now(KST).date()
    beginning=today-dt.timedelta(days=args.days)
    start=args.start or beginning.strftime('%Y%m%d')
    end=args.end or today.strftime('%Y%m%d')
    order_start=args.order_start or month_shift(today,-2)
    order_end=args.order_end or month_shift(today,12)
    # Fail on invalid filters before browser launch.
    validated=bridge.normalize_search_filters(start,end,order_start,order_end,args.biz_name)
    before=snapshot(db_file)
    report={
       'version':'G2B_HEADLESS_PRODUCTION_V13_1',
       'started_at':now(), 'status':'starting',
       'headless':not args.show, 'remote_debugging_9333':False,
       'database':str(db_file),
       'search':{**validated,'page_size':100,'page_limit':args.pages},
       'before':before,'initial_before_historical_merge':initial_snapshot,
       'historical_20261019_added':historical_added, 'errors':[],
    }
    report_path=Path(args.report).expanduser().resolve()
    report_path.parent.mkdir(parents=True,exist_ok=True)
    def dump():
        report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
    writer=Writer(db_file)
    monitor=bridge.Monitor(writer)
    # Independent private profile: does not use remote debugging and cannot disturb user Chrome.
    profile_path=Path(args.profile).expanduser().resolve()
    os.environ['G2B_HEADLESS_PROFILE']=str(profile_path)
    os.environ['G2B_SHOW_BROWSER']='1' if args.show else '0'
    dump()
    print(f'[START] {now()} | browser={"visible" if args.show else "headless"} (no 9333)',flush=True)
    print(f'[DATABASE] {db_file} | prior={initial_snapshot["total"]:,} historical_20261019_added={historical_added:,} | starting_live={before["total"]:,}',flush=True)
    print(f'[FILTER] {start}~{end} | business types=01 03 | 100 rows/page | cap={args.pages}',flush=True)
    print('[INFO] Opening G2B -> 발주 -> 발주목록 -> 검색, then replaying real POST XHR.',flush=True)
    start_clock=time.monotonic()
    deadline=start_clock+args.max_seconds
    last_show=time.monotonic()-30
    finished=False
    try:
        monitor.collect(page_limit=args.pages,start_date=start,end_date=end,order_start=order_start,
                        order_end=order_end,biz_name=args.biz_name)
        last_state=None
        while time.monotonic()<deadline:
            status=monitor.status()
            message=status.get('message') or ''
            last_state=status
            if time.monotonic()-last_show>=args.progress_seconds:
                print(f'[PROGRESS] {now()} | page={status.get("batch_done",0)}/{status.get("batch_goal",0)}'
                      f' | new={status.get("batch_added",0)} duplicates={status.get("batch_skipped",0)}'
                      f' | {message[:150]}',flush=True)
                last_show=time.monotonic()
                report['progress']=status
                dump()
            if (time.monotonic()-start_clock>100 and not status.get('xhr_ready')
                and not status.get('batch_active')):
                report['errors'].append('100초 동안 유효한 나라장터 POST XHR을 확보하지 못했습니다: '+message[:300])
                break
            if message.startswith('수집 종료:') and not status.get('batch_active'):
                finished=True
                break
            navigation_status=status.get('auto_navigation') or {}
            if navigation_status.get('ok') is False and navigation_status.get('stage') in ('root_dom_not_found','submenu_dom_not_found','search_form_not_found','xhr_not_captured'):
                # Navigation can automatically retry; allow time before breaking.
                if not status.get('queued') and not status.get('xhr_ready') and time.monotonic()+15 < deadline:
                    if time.monotonic()-last_show >= 10:
                        print('[NAV] '+str(navigation_status)[:250],flush=True)
            if not status.get('running') and not status.get('batch_active'):
                report['errors'].append('브라우저 감시 프로세스가 종료됐습니다: '+message)
                break
            time.sleep(0.5)
        if not finished and time.monotonic()>=deadline:
            report['errors'].append('제한시간 초과')
        status=monitor.status()
        report['monitor']=status
        report['navigation_trace']=list(nav.LAST_TRACE)[-70:]
        report['collector_save_stats']=writer.stats
        report['save_calls']=writer.calls
        report['bad_category_codes']=writer.bad_categories
        report['after']=snapshot(db_file)
        report['finished_at']=now()
        good=finished and status.get('batch_complete') and not status.get('failed_pages')
        report['status']='completed' if good else 'incomplete'
        report['db_delta']=report['after']['total']-before['total']
        if finished and not status.get('batch_complete'):
            report['errors'].append('페이지 한도/서버 응답 종료/실패 페이지 등의 이유로 전체완료 검증 불가')
        dump()
        print('[RESULT]',report['status'].upper(),flush=True)
        print('[STATS] DB pre='+str(before['total'])+' post='+str(report['after']['total'])+
             ' delta='+str(report['db_delta'])+' pages='+str(status.get('batch_done'))+
             ' added='+str(status.get('batch_added'))+
             ' skipped='+str(status.get('batch_skipped'))+
             ' failed='+str(len(status.get('failed_pages') or [])),flush=True)
        print('[OUTPUT]',report_path,flush=True)
        return 0 if good else 2
    except KeyboardInterrupt:
        report['status']='interrupted'
        return 130
    except Exception as exc:
        report['status']='exception'
        report['errors'].append(type(exc).__name__+': '+str(exc))
        print('[ERROR]',type(exc).__name__,str(exc),flush=True)
        return 2
    finally:
        monitor.stop()
        report['finished_at']=now()
        report.setdefault('after',snapshot(db_file))
        report.setdefault('navigation_trace',list(nav.LAST_TRACE)[-70:])
        dump()

def parser():
    p=argparse.ArgumentParser(description='G2B real POST XHR headless collector, no 9333')
    p.add_argument('--db',default=str(HERE/'g2b.sqlite3'))
    p.add_argument('--report',default=str(HERE/'g2b_collection_report.json'))
    p.add_argument('--profile',default=str(HERE/'g2b_headless_profile'))
    p.add_argument('--show',action='store_true',help='Show the otherwise identical Chrome browser')
    p.add_argument('--days',type=int,default=30,help='Lookback days for default dynamic dates')
    p.add_argument('--start',help='YYYYMMDD or YYYY-MM-DD')
    p.add_argument('--end',help='YYYYMMDD or YYYY-MM-DD')
    p.add_argument('--order-start',help='YYYYMM')
    p.add_argument('--order-end',help='YYYYMM')
    p.add_argument('--biz-name',default='')
    p.add_argument('--pages',type=int,default=1000)
    p.add_argument('--no-seed',action='store_true', help='Do not merge the 57 rows from historical user-supplied JSON')
    p.add_argument('--max-seconds',type=int,default=2400)
    p.add_argument('--progress-seconds',type=int,default=8)
    return p

if __name__=='__main__':
    args=parser().parse_args()
    if not (1<=args.pages<=10000 and 1<=args.days<=3650 and args.max_seconds>=10):
        print('[ERROR] Invalid pages, days or max-seconds.',file=sys.stderr)
        raise SystemExit(2)
    raise SystemExit(run(args))
