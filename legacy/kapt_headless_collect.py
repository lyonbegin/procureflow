#!/usr/bin/env python3
"""K-apt live Chrome (headless by default) bid collector, no 9333/CDP attach.

Uses the V12 K-apt real filter URL and HTML table definitions and the same SQLite
external_tenders tables as ProcureFlow. Does not create synthetic tender entries.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import shutil
import sqlite3
import sys
import traceback
from pathlib import Path
from urllib.parse import urlsplit

import kapt_filters
import multi_sources as ms

HERE = Path(__file__).resolve().parent
KST = dt.timezone(dt.timedelta(hours=9))


def timestamp():
    return dt.datetime.now(KST).isoformat(timespec='seconds')


def db_totals(db):
    ms.init_db(db)
    rows = db.execute("SELECT category,COUNT(*) FROM external_tenders WHERE source='kapt' GROUP BY category").fetchall()
    return {'total': sum(int(r[1]) for r in rows), 'by_category': {r[0]: r[1] for r in rows}}


def write_report(path, info):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(info, ensure_ascii=False, indent=2, default=str), encoding='utf-8')


def load_config(db, args):
    if args.config:
        cfg = json.loads(Path(args.config).read_text(encoding='utf-8-sig'))
    elif args.defaults:
        cfg = kapt_filters.default_config()
    else:
        cfg = kapt_filters.load_config(db)  # Same saved filters as V12 UI.
    if args.days is not None:
        cfg['dateRolling'] = False
        today = dt.datetime.now(KST).date()
        cfg['dateStart'] = (today - dt.timedelta(days=args.days)).isoformat()
        cfg['dateEnd'] = today.isoformat()
    if args.categories:
        cfg['categories'] = args.categories.split(',')
    cfg['pageSelect'] = 100
    return kapt_filters.validate_filters(cfg)


def launch_context(playwright, profile, show):
    profile.mkdir(parents=True, exist_ok=True)
    options = dict(user_data_dir=str(profile), headless=not show,
                   accept_downloads=False, locale='ko-KR',
                   viewport={'width': 1450, 'height': 950},
                   timezone_id='Asia/Seoul',
                   args=['--no-first-run', '--no-default-browser-check'])
    try:
        return playwright.chromium.launch_persistent_context(channel='chrome', **options)
    except Exception as chrome_exc:
        other = shutil.which('chromium') or shutil.which('chromium-browser')
        if not other:
            raise RuntimeError('로컬 Chrome 실행 실패: ' + str(chrome_exc)) from chrome_exc
        return playwright.chromium.launch_persistent_context(executable_path=other, **options)


def collect_pages(page, db, cfg, page_limit, report, on_progress=None):
    """Shared real-site + locally mocked browser test collection logic."""
    sources = []
    total_checked = total_new = 0
    total_pages = 0
    capped_categories=[]
    headers = []
    for kind in cfg['categories']:
        expected_type, label = kapt_filters.KIND_CODES[kind]
        sub_type = cfg['subtypes'].get(kind, '')
        previous_keys = None
        for number in range(1, page_limit + 1):
            url = ms.kapt_url(kind, number, config=cfg)
            report['current'] = {'category': label, 'page': number, 'url': url}
            report['last_attempt_url'] = url
            print(f'[FETCH] {label} page={number} | {urlsplit(url).path}', flush=True)
            response = page.goto(url, wait_until='domcontentloaded', timeout=30000)
            if response and response.status >= 400:
                raise RuntimeError(f'K-apt 검색 페이지 HTTP {response.status}: {url}')
            page.locator('#tblBidList').wait_for(state='attached', timeout=15000)
            page.locator('#code_classify_type_2').wait_for(state='attached', timeout=10000)
            actual_type = page.locator('#code_classify_type_2').input_value()
            if actual_type != expected_type:
                raise RuntimeError(f'K-apt 분류 설정이 사이트에서 적용되지 않음: {label}; expected={expected_type}, actual={actual_type}')
            if sub_type:
                actual_sub = page.locator('#code_classify_type_3').input_value()
                if actual_sub != sub_type:
                    raise RuntimeError(f'K-apt 하위분류 설정이 적용되지 않음: {label}; expected={sub_type}, actual={actual_sub}')
            rows, headers = ms.kapt_extract(page, label, url)
            if not rows:
                table_text = page.locator('#tblBidList').inner_text()
                if re.search(r'검색결과가 없습니다|자료가 없습니다|조회된.*없습니다|검색 결과가 없습니다', table_text):
                    print(f'[END] {label} page={number} explicitly empty', flush=True)
                    break
                if number > 1:
                    print(f'[END] {label} page={number} empty after previous pages', flush=True)
                    break
                raise RuntimeError(f'{label} 첫 페이지에서 공고 dataid를 발견하지 못함. DOM 구조 확인 필요.')
            ids = tuple(x.get('external_id') for x in rows)
            if previous_keys == ids:
                raise RuntimeError(f'{label} {number}페이지 내용이 직전 페이지와 동일합니다. pageNo가 무시됐을 가능성이 있습니다.')
            previous_keys = ids
            if len(ids) != len(set(ids)):
                raise RuntimeError(f'{label} {number}페이지 내 dataid 중복: 데이터 구조 오류')
            out = ms.save_rows(db, 'kapt', rows)
            checked, new = out['accepted'], out['added']
            if checked != len(rows):
                raise RuntimeError(f'파싱한 행 {len(rows)}개 중 정규화 {checked}개: 누락 확인 필요')
            total_checked += checked
            total_new += new
            total_pages += 1
            item = {'category': label, 'kind':kind, 'page':number,'checked':checked,
                    'new':new, 'duplicates':checked-new,'first_id':ids[0], 'last_id':ids[-1]}
            sources.append(item)
            report['pages'] = sources
            report['progress'] = {'checked':total_checked, 'new':total_new,
                                  'duplicates':total_checked-total_new, 'pages':total_pages}
            report['database_after_last_commit'] = db_totals(db)
            if on_progress:
                on_progress()
            print(f'[PROGRESS] {label} {number}페이지 검사 {checked}건, 신규 {new}건 | '
                  f'전체 신규 {total_new}, 중복 {total_checked-total_new}', flush=True)
            if len(rows) < cfg['pageSelect']:
                break
            if number == page_limit:
                capped_categories.append(label)
    return {'capped_categories':capped_categories,'pages':total_pages,'checked':total_checked,'new':total_new,
            'duplicates':total_checked-total_new,'headers':headers,'details':sources}


def run(args):
    db_path = Path(args.db).expanduser().resolve()
    profile = Path(args.profile).expanduser().resolve()
    report_file = Path(args.report).expanduser().resolve()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    report = {'version':'KAPT_HEADLESS_PRODUCTION_V14','started_at':timestamp(),
              'status':'starting','browser':'installed Chrome (Playwright)',
              'headless':not args.show,'remote_debugging_9333':False,
              'database':str(db_path),'profile':str(profile),'pages':[], 'errors':[]}
    page = None
    context = None
    with sqlite3.connect(db_path, timeout=30) as db:
        db.execute('PRAGMA busy_timeout=30000')
        db.execute('PRAGMA journal_mode=WAL')
        ms.init_db(db)
        cfg = load_config(db, args)
        report['filters'] = cfg
        report['before'] = db_totals(db)
    write_report(report_file, report)
    print('[START] K-apt Headless Chrome (no port 9333)',flush=True)
    print(f'[DATABASE] {db_path} prior={report["before"]["total"]}',flush=True)
    print(f'[FILTER] {cfg["dateStart"]}~{cfg["dateEnd"]} | '+', '.join(cfg['categories'])+
          f' | rows/page={cfg["pageSelect"]} | max pages/category={args.pages}', flush=True)
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as playwright:
            context = launch_context(playwright, profile, args.show)
            page = context.new_page()
            page.set_default_timeout(15000)
            trace_urls=[]
            def observe(response):
                if urlsplit(response.url).hostname == 'www.k-apt.go.kr':
                    path=urlsplit(response.url).path
                    if path not in trace_urls and len(trace_urls)<40:
                        trace_urls.append(path)
            page.on('response',observe)
            report['status']='running'
            write_report(report_file,report)
            with sqlite3.connect(db_path, timeout=30) as db:
                db.execute('PRAGMA busy_timeout=30000')
                detail = collect_pages(page, db, cfg, args.pages, report,
                                       on_progress=lambda:write_report(report_file,report))
                report['summary'] = detail
                report['after'] = db_totals(db)
                report['db_delta'] = report['after']['total'] - report['before']['total']
                if report['db_delta'] != detail['new']:
                    raise RuntimeError('DB 실제 증가 건수와 신규 저장 건수가 다릅니다.')
                report['source_response_paths'] = trace_urls
                audit_status='page_limit_reached' if detail['capped_categories'] else 'completed'
                db.execute('INSERT INTO external_source_audit(source,checked_at,result,message,url,source_response_paths,detected_headers) VALUES (?,?,?,?,?,?,?)',
                    ('kapt',timestamp(),audit_status,f'Headless: {detail["checked"]} checked, {detail["new"]} new',page.url,
                     json.dumps(trace_urls,ensure_ascii=False),json.dumps(detail['headers'],ensure_ascii=False)))
                db.commit()
            report['status']='page_limit_reached' if detail['capped_categories'] else 'completed'
            print('[RESULT] '+report['status'].upper()+' | checked={checked} new={new} dup={duplicates} DB={db_count}'.format(
                **detail, db_count=report['after']['total']),flush=True)
            return 0
    except KeyboardInterrupt:
        report['status']='interrupted'
        print('[RESULT] INTERRUPTED | previous committed pages preserved',flush=True)
        return 130
    except Exception as exc:
        report['status']='partial' if report.get('progress',{}).get('pages') else 'failed'
        msg=f'{type(exc).__name__}: {exc}'
        report['errors'].append(msg)
        print('[ERROR]',msg,flush=True)
        if page is not None:
            try:
                png=report_file.with_name('kapt_failure.png')
                page.screenshot(path=str(png),full_page=True, timeout=4000)
                report['failure_screenshot']=str(png)
            except Exception:pass
        return 2
    finally:
        try:
            if context is not None:context.close()
        except Exception:pass
        try:
            with sqlite3.connect(db_path, timeout=15) as db:
                ms.init_db(db)
                report['after']=db_totals(db)
        except Exception as exc:
            report['errors'].append(f'final DB snapshot: {exc}')
        report['finished_at']=timestamp()
        write_report(report_file,report)
        print('[OUTPUT]',report_file,flush=True)


def parser():
    p=argparse.ArgumentParser(description='K-apt exact-URL Headless Chrome collector, no 9333')
    p.add_argument('--db',default=str(HERE/'g2b.sqlite3'))
    p.add_argument('--report',default=str(HERE/'kapt_collection_report.json'))
    p.add_argument('--profile',default=str(HERE/'kapt_headless_profile'))
    p.add_argument('--show',action='store_true')
    p.add_argument('--pages',type=int,default=20,help='Maximum pages per selected category (default 20)')
    p.add_argument('--days',type=int,default=None,help='Override saved date filters with last N days')
    p.add_argument('--categories',default='',help='Comma-separated goods,service,construction,other')
    p.add_argument('--config',default='',help='User-supplied K-apt filters JSON')
    p.add_argument('--defaults',action='store_true',help='Ignore saved filters; use goods/service defaults')
    return p

if __name__=='__main__':
    args=parser().parse_args()
    if not 1<=args.pages<=10000 or (args.days is not None and not 1<=args.days<=3650):
        print('잘못된 페이지 수/기간입니다.',file=sys.stderr)
        raise SystemExit(2)
    raise SystemExit(run(args))
