"""Wishket public project, partner and portfolio collector. Headless Chromium."""
import json,re,time,logging
from urllib.parse import urljoin,urlparse
from playwright.sync_api import sync_playwright
from db import session

ROOT="https://www.wishket.com"
KINDS={
 "projects":("/project/",r"^/project/\d+/$"),
 "partners":("/partners/#clear",r"^/partners/p/[^/]+/"),
 "portfolios":("/partners/wishket-portfolio/?tab=all",r"^/partners/wishket-portfolio/\d+/$")
}
def collect(kind="portfolios",pages=2,limit=30):
 if kind not in KINDS:raise ValueError("unsupported kind")
 path,pattern=KINDS[kind];count=0;errors=[]
 with sync_playwright() as p:
  browser=p.chromium.launch(headless=True,args=["--no-sandbox","--disable-dev-shm-usage"])
  context=browser.new_context(locale="ko-KR",viewport={"width":1366,"height":900})
  page=context.new_page()
  try:
   for n in range(1,min(500,int(pages))+1):
    url=urljoin(ROOT,path)
    if kind=="portfolios":url=ROOT+"/partners/wishket-portfolio/?tab=all&page="+str(n)
    elif n>1:url+=("?page="+str(n))
    try:
     response=page.goto(url,wait_until="domcontentloaded",timeout=30000)
     if not response or response.status>=400:errors.append(f"listing {n}: HTTP {response.status if response else 'none'}");break
     page.wait_for_timeout(1000)
     hrefs=page.locator("a[href]").evaluate_all("els=>els.map(e=>e.getAttribute('href'))")
     links=sorted(set(urljoin(ROOT,x) for x in hrefs if x and re.match(pattern,urlparse(urljoin(ROOT,x)).path)))
     if not links and kind=="partners":
      # The partner directory renders profiles dynamically; use public
      # portfolio detail pages to discover their linked partner profiles.
      logging.info("Partner directory has no HTML anchors; following public portfolio author links")
      portfolio_list=ROOT+"/partners/wishket-portfolio/?tab=all&page="+str(n)
      page.goto(portfolio_list,wait_until="domcontentloaded",timeout=30000)
      portfolio_hrefs=page.locator('a[href]').evaluate_all("els=>els.map(e=>e.getAttribute('href'))")
      portfolio_links=sorted(set(urljoin(ROOT,x) for x in portfolio_hrefs if x and re.match(r"^/partners/wishket-portfolio/\d+/$",urlparse(urljoin(ROOT,x)).path)))
      author_links=set()
      for portfolio_url in portfolio_links[:max(10,limit)]:
       try:
        detail_resp=page.goto(portfolio_url,wait_until="domcontentloaded",timeout=25000)
        if detail_resp and detail_resp.status==200:
         phrefs=page.locator('a[href]').evaluate_all("els=>els.map(e=>e.getAttribute('href'))")
         for href in phrefs:
          if href:
           u=urljoin(ROOT,href)
           if re.match(pattern,urlparse(u).path):author_links.add(u)
       except Exception as exc:logging.warning("Partner fallback portfolio error: %s",type(exc).__name__)
      links=sorted(author_links)
     if not links:errors.append(f"page {n} produced no matching detail links");break
     for detail_url in links:
      if count>=limit:break
      try:
       resp=page.goto(detail_url,wait_until="domcontentloaded",timeout=25000)
       if not resp or resp.status!=200:continue
       page.wait_for_timeout(350)
       title=page.title()[:300]
       body=page.locator("body").inner_text(timeout=5000)[:60000]
       idmatch=re.search(r"/(\d+)/?$",urlparse(detail_url).path)
       record_id=(idmatch.group(1) if idmatch else urlparse(detail_url).path.strip("/").replace("/","_"))
       # Capture explicit customer labels only; do not infer masked client identities.
       matches=re.findall(r"(?:고객사|클라이언트|발주처)\s*[:：]?\s*([^\n]{1,100})",body)
       customers=[x.strip() for x in matches if x.strip()]
       item={"kind":kind,"source_id":record_id,"url":detail_url,"title":title,
             "text":body,"public_customer_labels":customers,"listing_page":n}
       with session() as db:
        db.execute("""INSERT INTO procureflow.wishket_records(kind,source_id,title,url,body,customers,raw)
         VALUES (%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb)
         ON CONFLICT(kind,source_id) DO UPDATE SET title=EXCLUDED.title,url=EXCLUDED.url,
         body=EXCLUDED.body,customers=EXCLUDED.customers,raw=EXCLUDED.raw,updated_at=now()""",
         (kind,record_id,title,detail_url,body,json.dumps(customers,ensure_ascii=False),
          json.dumps(item,ensure_ascii=False)))
       count+=1
      except Exception as exc:errors.append(detail_url+" "+type(exc).__name__)
     if count>=limit:break
    except Exception as exc:errors.append(f"listing {n} "+type(exc).__name__);break
  finally:browser.close()
 return {"kind":kind,"saved":count,"errors":errors[:12]}
