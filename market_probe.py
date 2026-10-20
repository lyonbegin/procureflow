"""Explore public navigation with Railway headless Chromium (no authentication bypass)."""
import json,logging,re,time
from datetime import datetime,timezone
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright
from db import session

TARGETS={
 'freemoa':'https://www.freemoa.net/',
 'wanted_gigs':'https://gigs.wanted.co.kr/',
 'kmong':'https://kmong.com/',
 'work24':'https://www.work24.go.kr/cm/main.do',
 'daangn':'https://jobs.daangn.com/',
 'soomgo':'https://soomgo.com/',
 'freemoa_projects':'https://www.freemoa.net/m4/s41',
 'freemoa_partners':'https://www.freemoa.net/m7/s71',
 'freemoa_portfolios':'https://www.freemoa.net/m7/s712',
 'kmong_it':'https://kmong.com/category/6',
 'daangn_cleaning':'https://jobs.daangn.com/s?regionId=28&jobTasks=%5B%22HOUSEWORK%22%5D',
 'soomgo_experts':'https://soomgo.com/search/pro/review_count?from=web_gnb',

}
NAV_WORDS=re.compile(r'프로젝트|포트폴리오|파트너|전문가|고수|외주|견적|채용|일자리|알바|지원|청소|이사|운송|프리랜서',re.I)

def scan(name,url,context):
    page=context.new_page()
    result={'source':name,'url':url,'observed_at':datetime.now(timezone.utc).isoformat(),
            'status':'unavailable','links':[],'xhr':[]}
    def on_response(resp):
        if len(result['xhr'])>=45 or resp.request.resource_type not in ('xhr','fetch'):return
        domain=urlparse(resp.url)
        if any(x in domain.netloc for x in ('google','naver','doubleclick','analytics','sentry','clarity','channel','posthog')):return
        result['xhr'].append({'host':domain.netloc,'path':domain.path[:200],'code':resp.status})
    page.on('response',on_response)
    try:
        resp=page.goto(url,wait_until='domcontentloaded',timeout=22000)
        page.wait_for_timeout(1200)
        result['http_status']=resp.status if resp else None
        result['final_url']=page.url
        result['title']=page.title()[:250]
        body=page.locator('body').inner_text(timeout=5000)
        result['body_excerpt']=body[:1200]
        result['total_anchors']=page.locator('a[href]').count()
        all_links=page.locator('a[href]').evaluate_all("""nodes=>nodes.map(a=>({
                title:(a.innerText||a.getAttribute('aria-label')||'').trim().slice(0,120),
                url:a.href
              })).filter(a=>/^https?:/.test(a.url))""")
        host=urlparse(page.url).netloc.replace('www.','')
        filtered=[]
        seen=set()
        for item in all_links:
            itemhost=urlparse(item['url']).netloc.replace('www.','')
            if itemhost!=host and not itemhost.endswith('.'+host):continue
            if item['url'] in seen:continue
            seen.add(item['url'])
            if len(filtered)<100 and (NAV_WORDS.search(item['title']) or NAV_WORDS.search(urlparse(item['url']).path) or len(filtered)<15):
                filtered.append(item)
        result['links']=filtered
        result['status']='ok' if result['http_status']==200 else 'http_error'
    except Exception as exc:result['error']=type(exc).__name__+': '+str(exc)[:260]
    finally:page.close()
    return result

def run():
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True,args=['--no-sandbox','--disable-dev-shm-usage'])
        try:
            for name,url in TARGETS.items():
                context=browser.new_context(locale='ko-KR',viewport={'width':1366,'height':900})
                result=scan(name,url,context)
                with session() as db:
                    db.execute("""INSERT INTO procureflow.settings(key,value) VALUES (%s,%s::jsonb)
                        ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value,updated_at=now()""",
                        ('market-probe:'+name,json.dumps(result,ensure_ascii=False)))
                logging.info('MARKET_PROBE %s',json.dumps({**result,'links':result['links'][:30]},ensure_ascii=False)[:4200])
                context.close()
                time.sleep(.4)
        finally:browser.close()
if __name__=='__main__':run()
