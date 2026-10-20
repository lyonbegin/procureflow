"""Bounded public-listing collectors for ProcureFlow private work sources.

Reads only public pages that render without login/CAPTCHA; blocked sites stay blocked.
Use distinct opportunity and subcontractor-supply roles; never turn job ads into worker profiles.
"""
import hashlib,json,logging,re,time
from urllib.parse import urljoin,urlparse
from playwright.sync_api import sync_playwright
from db import session

CONFIG={
 'freemoa':{'role':'development_demand','start':'https://www.freemoa.net/',
    'nav':r'프로젝트|비교견적|포트폴리오|파트너',
    'detail':r'project|proj|estimate|portfolio|partner|view'},
 'wanted_gigs':{'role':'development_demand','start':'https://gigs.wanted.co.kr/',
    'nav':r'프로젝트|프리랜서','detail':r'project|projects'},
 'kmong':{'role':'expert_supply','start':'https://kmong.com/',
    'nav':r'IT.프로그래밍|청소|이사|전문가|카테고리|AI 서비스',
    'detail':r'gig|service|portfolio|seller|experts|@'},
 'work24':{'role':'business_demand','start':'https://www.work24.go.kr/cm/main.do',
    'nav':r'채용정보|일자리 찾기|지역별|직종별|채용공고',
    'detail':r'empDetail|wantedAuthNo|empInfo|recruit'},
 'daangn':{'role':'job_demand','start':'https://jobs.daangn.com/',
    'nav':r'가사.집청소|물류.현장|심부름|알바|배송',
    'detail':r'/kr/jobs/|/jobs/'},
 'soomgo':{'role':'expert_supply','start':'https://soomgo.com/',
    'nav':r'고수찾기|이사.청소|외주|전문가|고수',
    'detail':r'/pro/|/pro$|profile|master|expert|/search|/service'},
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
                    title=page.title()[:250]
                    if len(body)<130:continue
                    key=hashlib.sha256(item['url'].encode()).hexdigest()[:24]
                    sample={'site':site,'role':cfg['role'],'listing_label':item['anchor'],
                        'http_status':r.status}
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
