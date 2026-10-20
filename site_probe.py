"""One-time public page reconnaissance with the same Railway Headless Chromium runtime."""
import json,logging,time
from datetime import datetime,timezone
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright
from db import session

TARGETS=[
 ('wishket','https://www.wishket.com/project/'),
 ('wishket_portfolios','https://www.wishket.com/partners/wishket-portfolio/?tab=all&page=3'),
 ('wishket_portfolio_detail','https://www.wishket.com/partners/wishket-portfolio/293597/'),
 ('wishket_project_clear','https://www.wishket.com/project/#clear'),
 ('freemoa','https://www.freemoa.net/'),
 ('wanted_gigs','https://www.wanted.co.kr/'),
 ('kmong','https://kmong.com/'),
 ('work24','https://www.work24.go.kr/'),
 ('daangn','https://www.daangn.com/'),
 ('soomgo','https://soomgo.com/'),
]
def run():
 with sync_playwright() as p:
  browser=p.chromium.launch(headless=True,args=['--no-sandbox','--disable-dev-shm-usage'])
  try:
   for name,url in TARGETS:
    context=browser.new_context(locale='ko-KR',viewport={'width':1366,'height':900},ignore_https_errors=False)
    page=context.new_page()
    captured=[]
    def response(resp):
     try:
      if resp.request.resource_type in ('xhr','fetch') and len(captured)<12:
       parsed=urlparse(resp.url)
       captured.append({'status':resp.status,'host':parsed.netloc,'path':parsed.path[:160]})
     except Exception:pass
    page.on('response',response)
    started=time.monotonic()
    result={'source':name,'requested_url':url,'checked_at':datetime.now(timezone.utc).isoformat()}
    try:
     resp=page.goto(url,wait_until='domcontentloaded',timeout=25000)
     page.wait_for_timeout(2800)
     result.update({'http_status':resp.status if resp else None,'final_url':page.url,'title':page.title()[:180],
        'body_length':len(page.locator('body').inner_text(timeout=4000)),
        'links':page.locator('a[href]').count(),
        'project_links':page.locator('a[href*="project"]').count(),
        'internal_links':page.locator('a[href]').evaluate_all("els=>Array.from(new Set(els.map(a=>a.href).filter(x=>x.includes('wishket.com')))).slice(0,45)"),
        'forms':page.locator('form').count(),
        'dynamic_requests':captured,
        'body_sample':page.locator('body').inner_text(timeout=4000)[:1400]})
    except Exception as exc:result['error']=type(exc).__name__+': '+str(exc)[:250]
    result['elapsed_seconds']=round(time.monotonic()-started,2)
    try:
     with session() as db:
      db.execute("""INSERT INTO procureflow.settings(key,value) VALUES (%s,%s::jsonb)
           ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value,updated_at=now()""",
           ('site-probe:'+name,json.dumps(result,ensure_ascii=False)))
    except Exception:logging.exception('Site probe persistence failed: %s',name)
    logging.info('SITE_PROBE %s',json.dumps(result,ensure_ascii=False)[:1600])
    context.close()
  finally:browser.close()
if __name__=='__main__':run()
