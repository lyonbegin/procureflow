"""Per-case category-exact public-source page collector; cannot replace official 10y coverage."""
import re
from html.parser import HTMLParser
from urllib.parse import urlparse,urljoin,urlencode
from playwright.sync_api import sync_playwright
from db import session
from g2b_case_10y import CASE_BID,CAT8,ensure_schema,parse_8digit_notice

class Links(HTMLParser):
    def __init__(self):
        super().__init__();self.hrefs=[]
    def handle_starttag(self,tag,attrs):
        if tag=="a":
            x=dict(attrs).get("href")
            if x:self.hrefs.append(x)

def crawl_one_index_page(page=1,limit=20):
    ensure_schema()
    url="https://bid24.kr/list?"+urlencode({
        "q":"정보시스템개발서비스","all":"1","sort":"new","page":page})
    result={"page":page,"url":url,"checked":0,"saved":0,
            "source":"secondary_public","official_months_completed":0,
            "errors":[]}
    with sync_playwright() as pw:
        ctx=pw.request.new_context(timeout=12000)
        try:
            r=ctx.get(url)
            if r.status!=200:raise RuntimeError("category_list_http_"+str(r.status))
            p=Links();p.feed(r.text())
            hrefs=[]
            for h in p.hrefs:
                full=urljoin(url,h)
                u=urlparse(full)
                if u.scheme=="https" and u.hostname=="bid24.kr" and re.fullmatch(r"/b/R\d{2}BK\d{8}",u.path):
                    if full not in hrefs:hrefs.append(full)
            result["listed"]=len(hrefs)
            for address in hrefs[:max(1,min(20,int(limit)))]:
                try:
                    doc=ctx.get(address)
                    if doc.status!=200:continue
                    obj,err=parse_8digit_notice(doc.text(),address)
                    result["checked"]+=1
                    if not obj:continue
                    with session() as db:
                        db.execute("""INSERT INTO procureflow.g2b_case_10yr_history(
                            case_bid_no,hist_notice_no,hist_notice_ord,
                            classification8,published_on,title,agency,amount,
                            source_url,evidence)
                            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,
                            'secondary_public_code_verified')
                            ON CONFLICT(case_bid_no,hist_notice_no,hist_notice_ord)
                            DO UPDATE SET published_on=excluded.published_on,
                            title=excluded.title,source_url=excluded.source_url,
                            collected_at=now()""",
                        (CASE_BID,obj["notice_no"],obj["notice_ord"],CAT8,
                         obj["published_on"],obj["title"],obj["agency"],
                         obj["amount"],address))
                    result["saved"]+=1
                except Exception as exc:
                    if len(result["errors"])<5:result["errors"].append(type(exc).__name__+":"+str(exc)[:90])
        finally:ctx.dispose()
    return result

def crawl_next_page():
    """Persist a strict page cursor, advancing only after every link was checked."""
    import json
    key="g2b:single:81111599:secondary_index_cursor"
    with session() as db:
        row=db.execute("SELECT value FROM procureflow.settings WHERE key=%s",(key,)).fetchone()
        page=max(1,int((row["value"] if row else {}).get("page",1)))
    result=crawl_one_index_page(page=page,limit=20)
    if result.get("listed",0)>0 and result["checked"]>=result["listed"] and not result["errors"]:
        with session() as db:
            db.execute("""INSERT INTO procureflow.settings(key,value)
               VALUES (%s,%s::jsonb) ON CONFLICT(key) DO UPDATE
               SET value=excluded.value,updated_at=now()""",
               (key,json.dumps({"page":page+1,"last_checked":page,
                                 "saved":result["saved"],"category":"81111599"})))
        result["next_page"]=page+1
    else:
        result["next_page"]=page
        result["cursor_advanced"]=False
    return result
