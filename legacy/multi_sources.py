"""K-apt standalone Headless Chrome collector; S2B legacy collection retained.

Uses real website DOM and observed K-apt GET parameters. K-apt never needs 9333.
S2B legacy implementation is unchanged; unknown layouts raise diagnostics.
"""
from __future__ import annotations

import hashlib
import json
import re
import threading
import os
import shutil
import time
import kapt_filters
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import urlsplit, urlencode

SITES = {
    'kapt': {'name': 'K-apt 공동주택', 'url': 'https://www.k-apt.go.kr/bid/bidList.do', 'hosts': ('k-apt.go.kr',)},
    's2b': {'name': 'S2B 학교장터', 'url': 'https://www.s2b.kr/', 'hosts': ('s2b.kr',)},
}
TZ = timezone(timedelta(hours=9))
LOCK = threading.Lock()
STATE = {key: {'status':'idle','message':'수집 전','saved':0,'scanned':0,'at':None,'stage':'idle'} for key in SITES}
SITE_ROWS_JS = r'''() => {
  const visible=e=>!!(e.getClientRects().length) && getComputedStyle(e).visibility!=='hidden';
  const norm=s=>(s||'').replace(/\s+/g,' ').trim();
  const result=[];
  for(const table of document.querySelectorAll('table')) {
    if(!visible(table)) continue;
    const trs=Array.from(table.querySelectorAll('tr')).filter(visible);
    if(trs.length<2)continue;
    let ths=Array.from(trs[0].querySelectorAll('th')).map(x=>norm(x.innerText));
    let headerIndex=0;
    if(!ths.length) {
      headerIndex=trs.findIndex(tr=>Array.from(tr.querySelectorAll('th')).length>=2);
      if(headerIndex<0)continue;
      ths=Array.from(trs[headerIndex].querySelectorAll('th')).map(x=>norm(x.innerText));
    }
    if(!ths.some(h=>/(공고|입찰|견적|발주|계약)/.test(h)))continue;
    for(const tr of trs.slice(headerIndex+1)) {
      const tds=Array.from(tr.children).filter(x=>x.matches('td'));
      if(tds.length<3) continue;
      const cells=tds.map(x=>norm(x.innerText));
      if(cells.every(x=>!x) || cells.some(x=>/정보가 존재하지 않습니다|검색 결과가 없습니다/.test(x)))continue;
      const anchor=tr.querySelector('a[href]:not([href^="javascript"])');
      const url=anchor?.href || location.href;
      result.push({headers:ths,cells,url,anchor:norm(anchor?.innerText||''),html_class:table.className||''});
    }
  }
  return result.slice(0,600);
}'''


def init_db(con):
    con.executescript('''
    CREATE TABLE IF NOT EXISTS external_tenders(
       id INTEGER PRIMARY KEY AUTOINCREMENT,
       source TEXT NOT NULL, external_id TEXT NOT NULL,
       title TEXT NOT NULL, category TEXT NOT NULL DEFAULT '미분류',
       agency TEXT NOT NULL DEFAULT '', notice_date TEXT NOT NULL DEFAULT '',
       deadline TEXT NOT NULL DEFAULT '', site_url TEXT NOT NULL DEFAULT '',
       status TEXT NOT NULL DEFAULT '', method TEXT NOT NULL DEFAULT '',
       raw_json TEXT NOT NULL DEFAULT '{}', first_seen TEXT NOT NULL,
       last_seen TEXT NOT NULL, UNIQUE(source,external_id)
    );
    CREATE INDEX IF NOT EXISTS idx_ext_tenders_deadline ON external_tenders(deadline);
    CREATE INDEX IF NOT EXISTS idx_ext_tenders_title ON external_tenders(title);
    CREATE INDEX IF NOT EXISTS idx_ext_tenders_source ON external_tenders(source);
    CREATE TABLE IF NOT EXISTS external_source_audit(
       id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT NOT NULL,
       checked_at TEXT NOT NULL, result TEXT NOT NULL, message TEXT NOT NULL,
       url TEXT NOT NULL DEFAULT '',
       source_response_paths TEXT NOT NULL DEFAULT '[]',
       detected_headers TEXT NOT NULL DEFAULT '[]'
    );
    ''')


def _time():
    return datetime.now(TZ).isoformat(timespec='seconds')


def _field(headers, cells, keys):
    for i, head in enumerate(headers):
        h=re.sub(r'\s','',str(head)).lower()
        if any(k in h for k in keys) and i<len(cells):
            return str(cells[i]).strip()
    return ''


def _classify(headers, cells, title):
    explicit=_field(headers,cells,('종류','업무구분','거래구분','입찰구분','계약구분','분류'))
    value=(explicit+' '+title).strip()
    if '공사' in explicit: return '공사'
    if '물품' in explicit or '구매' in explicit: return '물품'
    if '용역' in explicit or '서비스' in explicit: return '일반용역'
    if re.search(r'청소|미화|경비|시설관리|소독|방역|세탁|용역|유지보수|위탁|운송|물품구매|물품납품',value):
        return '일반용역' if not re.search(r'물품구매|물품납품',value) else '물품'
    if re.search(r'설치공사|보수공사|건설공사|방수공사',value): return '공사'
    if re.search(r'구입|납품|구매|장비|기자재|소모품',value): return '물품'
    return '미분류'  # Never invent an eligibility classification


def normalize_row(source,row):
    headers=row.get('headers') or []
    cells=row.get('cells') or []
    if len(cells)<3: return None
    title=_field(headers,cells,('공고명','입찰건명','입찰공고명','견적요청명','안내공고명','발주명','입찰명','사업명','품명','제목'))
    if not title: title=(row.get('anchor') or '').strip()
    if not title or title.lower() in ('상세보기','보기','첨부파일','입찰공고'):
        choices=[x for x in cells if len(x)>=9 and not re.fullmatch(r'\d{2,}',x) and not re.match(r'^\d{4}-\d{2}-\d{2}',x)]
        title=max(choices,key=len) if choices else ''
    if not title or len(title)<4: return None
    agency=_field(headers,cells,('단지명','발주기관','수요기관','기관명','학교명','계약기관'))
    num=str(row.get('external_id') or '').strip() or _field(headers,cells,('입찰번호','공고번호','견적요청번호','관리번호','번호','입찰공고번호'))
    date=_field(headers,cells,('공고일자','공고일','등록일','게시일','발주일','요청일'))
    deadline=_field(headers,cells,('입찰마감','마감일시','접수마감','견적마감','제출마감','마감일'))
    status=_field(headers,cells,('진행상태','상태','공고상태'))
    method=_field(headers,cells,('낙찰방법','입찰방법','계약방법'))
    if not num or re.fullmatch(r'\d{1,5}', num):
        # Row number is not a procurement notice ID. Derive a stable per-notice fingerprint.
        num='ROW-'+hashlib.sha256('|'.join((title,agency,date,deadline)).encode()).hexdigest()[:28]
    url=row.get('url') or SITES[source]['url']
    if not _allowed(url,source):url=SITES[source]['url']
    return {'source':source,'external_id':num[:150], 'title':title[:600],
            'category':row.get('category') if row.get('category') in ('물품','일반용역','공사','기타') else _classify(headers,cells,title), 'agency':agency[:250],
            'notice_date':date[:35], 'deadline':deadline[:35], 'site_url':url,
            'status':status[:50], 'method':method[:80], 'raw_json':json.dumps(row,ensure_ascii=False)}


def _allowed(url,source):
    try:
        p=urlsplit(url)
        return p.scheme in ('https','http') and any(p.hostname==h or p.hostname.endswith('.'+h) for h in SITES[source]['hosts'])
    except Exception:return False


def save_rows(con, source, rows):
    init_db(con)
    added=0; accepted=0
    for row in rows:
        record=normalize_row(source,row)
        if record is None:continue
        accepted+=1
        ts=_time()
        params=dict(record,ts=ts)
        # INSERT OR IGNORE would silently suppress NOT NULL/other data errors.
        # Ignore ONLY existing (source,external_id), not malformed records.
        cursor=con.execute('''INSERT INTO external_tenders
             (source,external_id,title,category,agency,notice_date,deadline,site_url,status,method,raw_json,first_seen,last_seen)
             VALUES (:source,:external_id,:title,:category,:agency,:notice_date,:deadline,:site_url,:status,:method,:raw_json,:ts,:ts)
             ON CONFLICT(source,external_id) DO NOTHING''',params)
        if cursor.rowcount==1:
            added+=1
        elif cursor.rowcount==0:
            if source=='kapt':
                # V10 may have stored an inferred category; update on explicit filter.
                updated=con.execute('''UPDATE external_tenders SET
                  title=:title,category=:category,agency=:agency,
                  notice_date=:notice_date,deadline=:deadline,site_url=:site_url,
                  status=:status,method=:method,raw_json=:raw_json,last_seen=:ts
                  WHERE source=:source AND external_id=:external_id''',params)
            else:
                updated=con.execute('''UPDATE external_tenders SET last_seen=:ts
                  WHERE source=:source AND external_id=:external_id''',params)
            if updated.rowcount!=1:
                raise RuntimeError('중복 공고 갱신 실패: '+source+'/'+record['external_id'])
        else:
            raise RuntimeError('공고 INSERT 처리 결과가 예상과 다릅니다: '+str(cursor.rowcount))
    con.commit()
    return {'accepted':accepted,'added':added}



def stored_stats(con):
    """Read the real g2b.sqlite3; not in-memory counters or HTTP results."""
    init_db(con)
    sites={source:{'stored':0,'categories':{'물품':0,'일반용역':0},'other':0}
           for source in SITES}
    for source,category,count in con.execute("""SELECT source,category,COUNT(*)
                          FROM external_tenders WHERE source IN ('kapt','s2b')
                          GROUP BY source,category""").fetchall():
        if source not in sites:
            continue
        data=sites[source]
        data['stored']+=count
        if category in data['categories']:
            data['categories'][category]+=count
        else:
            data['other']+=count
    return {'sites':sites,'total':sum(x['stored'] for x in sites.values())}

def search(con,source='',q='',limit=100,offset=0,category=''):
    init_db(con)
    sql=' FROM external_tenders WHERE 1=1'; params=[]
    if source in SITES:sql+=' AND source=?';params.append(source)
    elif not source:
        # Hide legacy D2B notices without deleting previously collected data.
        sql+=' AND source IN ('+','.join('?' for _ in SITES)+')'
        params.extend(SITES)
    if category in ('물품','일반용역'):
        sql+=' AND category=?';params.append(category)
    if q:
        sql+=' AND (title LIKE ? OR agency LIKE ? OR external_id LIKE ?)';params.extend(['%'+q+'%']*3)
    count=con.execute('SELECT COUNT(*)'+sql,params).fetchone()[0]
    data=con.execute('SELECT id,source,external_id,title,category,agency,notice_date,deadline,site_url,status,method,first_seen'+sql+' ORDER BY id DESC LIMIT ? OFFSET ?',(*params,max(1,min(int(limit),500)),max(0,int(offset)))).fetchall()
    return {'total':count,'items':[dict(r) for r in data]}


def info():
    with LOCK:return json.loads(json.dumps(STATE,ensure_ascii=False))


def _update(source,**kwargs):
    with LOCK:STATE[source].update(kwargs,at=_time())


def _click_text(page,names,timeout=2500):
    for name in names:
        for f in page.frames:
            for selector in ('a','button','[role=button]','input[type=button]','input[type=submit]'):
                try:
                    loc=f.locator(selector).filter(has_text=re.compile('^\\s*'+re.escape(name)+'\\s*$'))
                    if selector.startswith('input'):
                        loc=f.locator(selector+'[value="'+name+'"]')
                    for i in range(min(loc.count(),6)):
                        e=loc.nth(i)
                        if e.is_visible() and e.is_enabled():
                            e.click(timeout=timeout)
                            page.wait_for_timeout(600)
                            return True
                except Exception:pass
    return False


def _navigate_menu(page, source):
    if source=='kapt':return 'direct_public_list'
    # S2B official guide: 견적요청 and 안내공고 are buying demand.
    steps=[('1인수의 견적요청','1인수의(견적요청)','견적요청'),('견적서 접수목록','견적요청서 접수목록','접수목록')]
    walked=[]
    for options in steps:
        if _click_text(page,options):walked.append('/'.join(options))
        else:break
    return ' > '.join(walked) if walked else 'navigation_not_found'


def _rows(page):
    result=[]
    for f in page.frames:
        try:
            for row in f.evaluate(SITE_ROWS_JS):
                if row.get('headers') and row.get('cells'):result.append(row)
        except Exception:pass
    return result


def _next_page(page,page_index):
    # Opt in only when a pagination control exists. Never click arbitrary numeric content.
    selectors=(f'.pagination a:text-is("{page_index+1}")',f'.paging a:text-is("{page_index+1}")',
               f'[class*="paging"] a:text-is("{page_index+1}")',
               f'[class*="pagination"] a:text-is("{page_index+1}")')
    for f in page.frames:
        for selector in selectors:
            try:
                l=f.locator(selector)
                for i in range(min(4,l.count())):
                    e=l.nth(i)
                    if e.is_visible() and e.is_enabled():
                        e.click(timeout=2500)
                        page.wait_for_timeout(800)
                        return True
            except Exception:pass
    return False



# HTML filters supplied from the actual K-apt search page on 2026-10-19.
# The site publicly exposes GET /bid/bidList.do.  "사업자"=02,
# "용역"=03, "물품"=04 and goods purchase (NOT asset sale)=13.
KAPT_CATEGORIES = {
    'service': ('03', '', '일반용역'),
    'goods':   ('04', '13', '물품'),
}
KAPT_LIST_JS = r'''() => {
  const table = document.querySelector('#tblBidList');
  if (!table) return {found:false, rows:[], headers:[]};
  const norm = s => (s || '').replace(/\s+/g, ' ').trim();
  const headers = Array.from(table.querySelectorAll('thead th')).map(x => norm(x.textContent));
  const rows = Array.from(table.querySelectorAll('tbody tr.notice-row[dataid]')).map(tr => {
    const tds = Array.from(tr.children).filter(x => x.tagName === 'TD');
    if (tds.length < 8) return null;
    const cells = tds.map(td => norm(td.textContent));
    const aptClick = tds[6].getAttribute('onclick') || '';
    const aptCode = (aptClick.match(/initList\(\s*4\s*,\s*['"]([^'"]+)['"]/i) || [,''])[1];
    return {headers, cells, external_id:tr.getAttribute('dataid'),
      attachment:!!tds[3].querySelector('img'), apt_code:aptCode};
  }).filter(Boolean);
  return {found:true, rows, headers};
}'''


def kapt_url(kind, page_no=1, start=None, end=None, page_size=100, config=None):
    """Build site-native GET URL using user-editable filters; legacy calls still work."""
    if kind not in kapt_filters.KIND_CODES:
        raise ValueError('지원하지 않는 K-apt 입찰분류입니다.')
    if config is None:
        cfg=kapt_filters.default_config()
        if kind not in cfg['categories']:cfg['categories'].append(kind)
        if start is not None:cfg['dateStart']=start
        if end is not None:cfg['dateEnd']=end
        cfg['pageSelect']=page_size
    else:
        cfg=dict(config)
    return kapt_filters.build_url(SITES['kapt']['url'],kind,int(page_no),cfg)


def _launch_kapt_context(playwright):
    """Start owned private-profile Chrome, identically to the G2B headless flow."""
    profile=Path(os.getenv('KAPT_HEADLESS_PROFILE',str(Path(__file__).resolve().parent/'kapt_headless_profile'))).resolve()
    profile.mkdir(parents=True,exist_ok=True)
    show=os.getenv('KAPT_SHOW_BROWSER','0').lower() in ('1','true','yes','on')
    opts=dict(user_data_dir=str(profile),headless=not show,accept_downloads=False,
              locale='ko-KR',viewport={'width':1450,'height':950},timezone_id='Asia/Seoul',
              args=['--no-first-run','--no-default-browser-check'])
    try:
        return playwright.chromium.launch_persistent_context(channel='chrome',**opts)
    except Exception as first:
        exe=shutil.which('chromium') or shutil.which('chromium-browser')
        if not exe:raise RuntimeError('Headless Chrome 실행 실패: '+str(first)) from first
        return playwright.chromium.launch_persistent_context(executable_path=exe,**opts)


def kapt_site_subtypes(group='02',kind='service'):
    """Read actual K-apt subcategory options using directly-launched Chrome."""
    from playwright.sync_api import sync_playwright
    if group not in ('01','02'):raise ValueError('입찰분류1 코드 오류')
    if kind not in kapt_filters.KIND_CODES:raise ValueError('입찰분류2 코드 오류')
    cfg=kapt_filters.default_config()
    cfg['categories']=[kind]
    cfg['codeClassifyType1']=group
    cfg['subtypes'][kind]=''
    with sync_playwright() as p:
        context=_launch_kapt_context(p)
        page=context.new_page()
        try:
            page.goto(kapt_url(kind,1,config=cfg),wait_until='domcontentloaded',timeout=30000)
            page.locator('#code_classify_type_2').wait_for(state='attached',timeout=12000)
            # JS onchange getClassify_type('codeClassifyType3') populates service options.
            page.select_option('#code_classify_type_1',group)
            page.wait_for_timeout(500)
            page.select_option('#code_classify_type_2',kapt_filters.KIND_CODES[kind][0])
            page.wait_for_timeout(1200)
            return page.locator('#code_classify_type_3').evaluate("el => Array.from(el.options).map(o=>({value:o.value,label:o.textContent.trim()}))")
        finally:
            context.close()


def kapt_extract(page, category, source_url):
    """Read observed table #tblBidList; notice keys are <tr dataid=...>."""
    data = page.evaluate(KAPT_LIST_JS)
    if not data['found']:
        raise RuntimeError('K-apt 목록 테이블 #tblBidList가 없습니다.')
    rows = data['rows']
    for row in rows:
        row['category'] = category
        row['url'] = source_url  # observed search page, not a fabricated detail endpoint
    return rows, data['headers']


def _collect_kapt(tab, con, pages, update, audit_urls, config=None):
    scanned = saved = 0
    diagnostics = []
    last_headers = []
    config=kapt_filters.validate_filters(config)
    # Each selected category is a separate GET; defaults are goods+service.
    for kind in config['categories']:
        _code, category = kapt_filters.KIND_CODES[kind]
        for pg in range(1, pages+1):
            url = kapt_url(kind,pg,config=config)
            update(message=f'K-apt {category} {pg}/{pages}페이지 조회',stage=f'kapt_{kind}')
            tab.goto(url, wait_until='domcontentloaded', timeout=35000)
            # Page response may contain the full table or be updated on load.
            tab.locator('#tblBidList').wait_for(state='attached', timeout=15000)
            # A silently ignored filter must not be mistaken for successful collection.
            actual_type=tab.locator('#code_classify_type_2').input_value()
            if actual_type != _code:
                raise RuntimeError(f'K-apt 요청 분류 {_code}와 실제 화면 {actual_type}가 다릅니다: {kind}')
            rows, hdr = kapt_extract(tab,category,url)
            last_headers = hdr
            if not rows:
                content=tab.locator('#tblBidList').inner_text()
                if re.search(r'검색결과가 없습니다|자료가 없습니다|조회된.*없습니다|검색 결과가 없습니다',content):
                    diagnostics.append(f'{category}: {pg}페이지 종료 (사이트 0건 표기)')
                    break
                if pg > 1:
                    diagnostics.append(f'{category}: {pg}페이지에 공고행이 없어 종료')
                    break
                raise RuntimeError(f'{category} 첫 페이지는 열렸으나 dataid가 있는 공고 행이 없습니다.')
            output = save_rows(con,'kapt',rows)
            scanned += output['accepted'];saved += output['added']
            update(scanned=scanned,saved=saved,message=f'K-apt {category} {pg}페이지: {output["accepted"]}건 검사, 신규 누적 {saved}건',stage=f'kapt_{kind}')
            diagnostics.append(f'{category} {pg}페이지 {output["accepted"]}건, 신규 {output["added"]}건')
            if len(rows) < config['pageSelect']:
                break
    return scanned,saved,last_headers,diagnostics

def _run(source,db_path,pages,config=None):
    from sqlite3 import connect
    from playwright.sync_api import sync_playwright
    tab=None
    kapt_context=None
    audit_urls=[]; last_headers=[]
    result='error'; message=''
    scanned=saved=0; stage='connect'; audit_written=False
    try:
        _update(source,status='running',message=('Headless Chrome 직접 실행 중' if source=='kapt' else 'Chrome 9333 연결 중'),stage=stage)
        with sync_playwright() as playwright:
            if source=='kapt':
                kapt_context=_launch_kapt_context(playwright)
                context=kapt_context
            else:
                browser=playwright.chromium.connect_over_cdp('http://127.0.0.1:9333',timeout=15000)
                if not browser.contexts:raise RuntimeError('Chrome 9333에 브라우저 컨텍스트가 없습니다.')
                context=browser.contexts[0]
            tab=context.new_page()
            tab.set_default_timeout(8000)
            def observe(response):
                try:
                    u=urlsplit(response.url)
                    if any(u.hostname==h or u.hostname.endswith('.'+h) for h in SITES[source]['hosts']):
                        if any(t in u.path.lower() for t in ('bid','list','notice','estimate','tender')):
                            if u.path not in audit_urls and len(audit_urls)<40:audit_urls.append(u.path)
                except Exception:pass
            tab.on('response',observe)
            stage='navigation'
            _update(source,message='공식 사이트 열기',stage=stage)
            if source!='kapt':
                tab.goto(SITES[source]['url'],wait_until='domcontentloaded',timeout=35000)
                tab.wait_for_timeout(1700)
                navigated=_navigate_menu(tab,source)
                if navigated=='navigation_not_found':
                    _update(source,message='메뉴 자동 탐색 중. 사이트 내 공개 입찰목록 찾는 중',stage=stage)
                stage='search'
                _update(source,message='공고 검색 및 표 인식',stage=stage)
                _click_text(tab,('검색','조회','검색하기'),timeout=1700)
                tab.wait_for_timeout(1800)
            stage='collect'
            with connect(db_path,timeout=20) as con:
                con.execute('PRAGMA busy_timeout=20000')
                init_db(con)
                if source=='kapt':
                    scanned,saved,last_headers,diagnostics = _collect_kapt(tab,con,pages,lambda **kw:_update(source,**kw),audit_urls,config)
                    result='completed'
                    live=stored_stats(con)['sites']['kapt']
                    if scanned>0 and live['stored']==0:
                        raise RuntimeError('공고를 검사했지만 DB 보관 건수가 0입니다. DB 저장 경로/권한을 점검하십시오.')
                    selection='·'.join(kapt_filters.KIND_CODES[k][1] for k in kapt_filters.validate_filters(config)['categories'])
                    message=(f'K-apt {selection} 검색 완료: 검사 {scanned}건, '
                             f'신규 {saved}건, 중복 {scanned-saved}건, '
                             f'DB 실제 보관 {live["stored"]}건 '
                             f'(물품 {live["categories"]["물품"]}건, '
                             f'일반용역 {live["categories"]["일반용역"]}건, '
                             f'기타 {live["other"]}건); '+'; '.join(diagnostics))
                else:
                    for i in range(pages):
                        attempts=0; rr=[]
                        while attempts<2:
                            rr=_rows(tab)
                            if rr:break
                            attempts+=1
                            tab.wait_for_timeout(1400)
                        if not rr:
                            if i==0:
                                message='공개 입찰목록 표를 찾지 못했습니다. 실제 페이지 메뉴/로그인/화면 구조 진단이 필요합니다.'
                                result='needs_site_structure'
                            else:
                                message=f'{i}페이지까지 수집했고 이후 목록 테이블을 찾지 못했습니다.'
                                result='partial'
                            break
                        last_headers=rr[0]['headers']
                        output=save_rows(con,source,rr)
                        scanned+=output['accepted'];saved+=output['added']
                        _update(source,scanned=scanned,saved=saved,message=f'{i+1}페이지 처리, 새 공고 {saved}건',stage=stage)
                        if i+1>=pages:
                            result='completed';message=f'{i+1}페이지 수집 완료 (신규 {saved}건, 처리 {scanned}건)';break
                        if not _next_page(tab,i+1):
                            result='partial';message=f'{i+1}페이지 처리 후 다음 페이지 버튼을 찾지 못했습니다.';break
                con.execute('INSERT INTO external_source_audit(source,checked_at,result,message,url,source_response_paths,detected_headers) VALUES (?,?,?,?,?,?,?)',
                            (source,_time(),result,message,tab.url,json.dumps(audit_urls,ensure_ascii=False),json.dumps(last_headers,ensure_ascii=False)))
                con.commit()
                audit_written=True
    except Exception as exc:
        message=f'{stage} 단계 오류: {type(exc).__name__}: {str(exc)[:240]}'
        result='error'
    finally:
        if not audit_written:
            try:
                with connect(db_path,timeout=15) as con:
                    init_db(con)
                    con.execute('INSERT INTO external_source_audit(source,checked_at,result,message,url,source_response_paths,detected_headers) VALUES (?,?,?,?,?,?,?)',
                        (source,_time(),result,message,tab.url if tab else '',json.dumps(audit_urls,ensure_ascii=False),json.dumps(last_headers,ensure_ascii=False)))
                    con.commit()
            except Exception:pass
        if tab is not None:
            try:tab.close()
            except Exception:pass
        if kapt_context is not None:
            try:kapt_context.close()
            except Exception:pass
        _update(source,status=result,message=message,scanned=scanned,saved=saved,stage=stage)


def start(source,db_path,pages=20,config=None):
    if source not in SITES:raise ValueError('지원하지 않는 사이트입니다.')
    pages=max(1,min(int(pages),100))
    if source=='kapt':config=kapt_filters.validate_filters(config)
    if not LOCK.acquire(blocking=False):return {'ok':False,'error':'다른 사이트의 수집 상태 갱신 중입니다.'}
    try:
        if _BATCH_RUNNING or any(v['status'] in ('running','queued') for v in STATE.values()):
            return {'ok':False,'error':'다른 사이트 수집이 진행 중입니다. 완료 후 실행해 주십시오.'}
        STATE[source]={'status':'running','message':'작업 예약됨','saved':0,'scanned':0,'at':_time(),'stage':'queued'}
    finally:LOCK.release()
    threading.Thread(target=_run,args=(source,str(db_path),pages,config),daemon=True,name=f'{source}-collector').start()
    return {'ok':True,'source':source,'pages':pages,'message':('Headless Chrome 직접 실행 후 공식 K-apt 공고 자동수집 시작' if source=='kapt' else '공식 입찰공고 자동수집 시작')}


def audit(con,source):
    init_db(con)
    if source not in SITES:raise ValueError('지원하지 않는 사이트입니다.')
    r=con.execute('SELECT * FROM external_source_audit WHERE source=? ORDER BY id DESC LIMIT 1',(source,)).fetchone()
    return dict(r) if r else {}

# Batch startup: K-apt and S2B run sequentially; G2B remains its own module.
_BATCH_RUNNING = False

def start_all(db_path, pages=20,config=None):
    global _BATCH_RUNNING
    pages=max(1,min(int(pages),100))
    config=kapt_filters.validate_filters(config)
    with LOCK:
        if _BATCH_RUNNING or any(x['status']=='running' for x in STATE.values()):
            return {'ok':False,'error':'다른 수집 작업이 진행 중입니다.'}
        _BATCH_RUNNING=True
        for source in SITES:
            STATE[source]={'status':'queued','message':'일괄 자동수집 대기 중','saved':0,'scanned':0,'at':_time(),'stage':'queued'}
    def job():
        global _BATCH_RUNNING
        try:
            for source in SITES:
                _run(source,str(db_path),pages,config if source=='kapt' else None)
        finally:
            with LOCK:_BATCH_RUNNING=False
    threading.Thread(target=job,daemon=True,name='other-procurement-batch').start()
    return {'ok':True,'sites':list(SITES),'pages':pages,'message':'K-apt(선택 분류) → S2B 순차 자동수집 예약'}
