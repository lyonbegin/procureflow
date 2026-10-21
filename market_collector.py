"""Bounded public-listing collectors for ProcureFlow private work sources.

Reads only public pages that render without login/CAPTCHA; blocked sites stay blocked.
Use distinct opportunity and subcontractor-supply roles; never turn job ads into worker profiles.
"""
import hashlib,json,logging,re,time
from urllib.parse import urljoin,urlparse
from playwright.sync_api import sync_playwright
from db import session

CONFIG={
 'freemoa':{'role':'development_demand','start':'https://www.freemoa.net/m4/s41',
    'nav':r'프로젝트|비교견적','detail':r'/m4/(?!s41(?:$|\?))|pjno=|pno=|project_detail'},
 'freemoa_partners':{'role':'expert_supply','start':'https://www.freemoa.net/m7/s71',
    'nav':r'파트너스|프리랜서','detail':r'/m7/freelance_detail\?fno='},
 'freemoa_portfolios':{'role':'portfolio_reference','start':'https://www.freemoa.net/m7/s712',
    'nav':r'포트폴리오','detail':r'/m7/portfolio|portfolio_detail|pfo_no=|pfno='},
 'wanted_gigs':{'role':'development_demand','start':'https://gigs.wanted.co.kr/',
    'nav':r'프로젝트|프리랜서','detail':r'project|projects'},
 'kmong_enterprise':{'role':'development_demand',
    'start':'https://kmong.com/enterprise/requests?category_list=6&page=1&q=&sort=created_at',
    'nav':r'프로젝트|IT|프로그래밍|외주|인력|전체',
'detail':r'/enterprise/requests/[0-9]+'},
 'kmong':{'role':'expert_supply','start':'https://kmong.com/category/6',
    'nav':r'IT.프로그래밍|AI|청소|이사|전문가','detail':r'/gig/|/service/|/seller/|/portfolio/[0-9]+'},
 'work24':{'role':'business_demand','start':'https://www.work24.go.kr/wk/a/b/1200/retriveDtlEmpSrchList.do',
    'nav':r'채용정보|일자리 찾기|지역별|직종별|채용공고','detail':r'empDetailAuthView|wantedAuthNo='},
 'daangn':{'role':'job_demand','start':'https://jobs.daangn.com/',
    'nav':r'가사.집청소|물류.현장|심부름|알바|배송',
    'detail':r'/job-posts/|/kr/jobs/'},
 'soomgo':{'role':'expert_supply','start':'https://soomgo.com/search/pro/review_count?from=web_gnb',
    'nav':r'고수찾기|이사.청소|외주|전문가|고수',
    'detail':r'/profile/users/|/service/|/pro/[0-9]+'},
}
CUTOFF=re.compile(r'javascript:|^#|login|sign.?up|register|logout|signup|privacy|terms|policy|customer.?support|support|faq|notices',re.I)

def allowed(site,u):
    if not u.startswith('https://'):return False
    host=urlparse(u).hostname or ''
    if site=='daangn':return host in ('jobs.daangn.com','www.daangn.com','daangn.com')
    if site=='wanted_gigs':return host in ('gigs.wanted.co.kr','www.wanted.co.kr')
    base=urlparse(CONFIG[site]['start']).hostname or ''
    return host==base or host==base.removeprefix('www.') or host=='www.'+base

def links(page):
    return page.locator('a[href]').evaluate_all("""els=>els.map(e=>({
        url:e.href,text:(e.innerText||e.getAttribute('aria-label')||'').replace(/\\s+/g,' ').trim().slice(0,160)
    })).filter(x=>x.url.startsWith('https://'))""")

SERVICE_TAGS={
 'cleaning':r'청소|미화|세척|소독|방역|정리',
 'transport':r'운송|배송|이사|화물|퀵|배달|캐리어|짐(?:옮기|운반)',
 'facility':r'경비|보안|시설관리|방재|전기안전|기계설비|시설점검',
 'development':r'개발|프로그래밍|ERP|MES|AI|앱제작|웹사이트|IT|소프트웨어',
}
def classify_demand(site,short_text):
    """Separate explicit service tasks from recurring employment demand."""
    area=next((key for key,pattern in SERVICE_TAGS.items() if re.search(pattern,short_text,re.I)),'other')
    if site=='kmong_enterprise': return 'project_request',area
    if site=='work24':return 'staffing_demand',area
    if site=='daangn':
        is_one_off=bool(re.search(r'건당|1회|단기|당일|오늘|내일|하루|이번주|한번|일회성|1일|2일',short_text,re.I))
        return ('concrete_task' if is_one_off and area!='other' else 'staffing_demand'),area
    return ('project_request' if site=='freemoa' else 'supply'),area

def run(site,pages=1,limit=8):
    if site not in CONFIG:raise ValueError('Unknown source')
    cfg=CONFIG[site];pages=max(1,min(int(pages),20));limit=max(1,min(int(limit),200))
    result={'source':site,'role':cfg['role'],'status':'started','examined':0,'saved':0,
            'new':0,'errors':[],'nav':[],'listings':[],'blocked_urls':[]}
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True,args=['--no-sandbox','--disable-dev-shm-usage'])
        context=browser.new_context(locale='ko-KR',viewport={'width':1366,'height':900})
        page=context.new_page()
        seen=set()
        try:
            res=page.goto(cfg['start'],wait_until='domcontentloaded',timeout=25000)
            if not res or res.status in (401,403,429):
                result.update(status='access_restricted',http_status=(res.status if res else None))
                return result
            if res.status>=400:
                result.update(status='http_error',http_status=res.status)
                return result
            page.wait_for_timeout(900)
            candidates=links(page)
            nav=[]
            for x in candidates:
                u=x['url'].split('#')[0]
                if allowed(site,u) and re.search(cfg['nav'],x['text'],re.I) and not CUTOFF.search(u) and u not in nav:
                    nav.append(u)
            result['nav']=nav[:18]
            # One landing page plus limited first-level list/category routes.
            listing_urls=[cfg['start']]
            listing_urls.extend(u for u in nav if u!=cfg['start'])
            listing_urls=listing_urls[:pages+2]
            detail=[]
            for listing_url in listing_urls:
                try:
                    r=page.goto(listing_url,wait_until='domcontentloaded',timeout=22000)
                    if not r or r.status>=400:continue
                    page.wait_for_timeout(850)
                    result['listings'].append({'url':listing_url,'code':r.status,'title':page.title()[:100]})
                    for x in links(page):
                        u=x['url'].split('#')[0]
                        parsed=urlparse(u)
                        if u in seen or not allowed(site,u) or CUTOFF.search(u):continue
                        if not re.search(cfg['detail'],parsed.path+('?' + parsed.query if parsed.query else ''),re.I):continue
                        if parsed.path in ('/','/pro','/pro/','/projects','/projects/','/project','/project/'):continue
                        seen.add(u)
                        detail.append({'url':u,'anchor':x['text']})
                except Exception as exc:result['errors'].append('listing '+type(exc).__name__+': '+str(exc)[:100])
            result['examined']=len(detail)
            for item in detail[:limit]:
                try:
                    r=page.goto(item['url'],wait_until='domcontentloaded',timeout=20000)
                    if not r:continue
                    if r.status in (401,403,429):
                        result['blocked_urls'].append({'url':item['url'],'status':r.status});continue
                    if r.status>=400:continue
                    page.wait_for_timeout(350)
                    body=page.locator('body').inner_text(timeout=4500)[:20000]
                    # Contact details on Work24 are for employment purposes only.
                    if site=='work24':body=body.split('채용 담당자')[0]
                    title=page.title()[:250]
                    if len(body)<130:continue
                    key=hashlib.sha256(item['url'].encode()).hexdigest()[:24]
                    task_class,service_area=classify_demand(site,(item['anchor']+' '+title)[:600])
                    budget_match=re.search(r'예산\s*\n?\s*([0-9][0-9,]*)\s*원',body)
                    budget_krw=int(budget_match.group(1).replace(',','')) if budget_match else None
                    format_match=re.search(r'진행 방식\s*\n?\s*(외주|상주)',body)
                    sample={'site':site,'role':cfg['role'],'listing_label':item['anchor'],
                        'http_status':r.status,'demand_type':task_class,'service_area':service_area,
                        'budget_krw':budget_krw,'work_format':format_match.group(1) if format_match else None}
                    with session() as db:
                        row=db.execute("""INSERT INTO procureflow.market_records
                            (source,kind,source_id,title,url,body,meta)
                            VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb)
                            ON CONFLICT(source,kind,source_id) DO UPDATE
                            SET title=EXCLUDED.title,url=EXCLUDED.url,body=EXCLUDED.body,
                              meta=EXCLUDED.meta,last_seen=now()
                            RETURNING xmax=0 AS new""",
                            (site,cfg['role'],key,title,item['url'],body,json.dumps(sample,ensure_ascii=False))).fetchone()
                        result['saved']+=1
                        result['new']+=1 if row['new'] else 0
                except Exception as exc:result['errors'].append('detail '+type(exc).__name__+': '+str(exc)[:100])
            if result['saved']:result['status']='collected'
            elif result['blocked_urls']:result['status']='access_restricted'
            else:result['status']='discovery_only'
        except Exception as exc:
            result['status']='error'
            result['errors'].append(type(exc).__name__+': '+str(exc)[:220])
        finally:
            context.close()
            browser.close()
    return result
