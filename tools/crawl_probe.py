#!/usr/bin/env python3
"""Standalone public-site crawl diagnostic: GitHub Actions or Windows, no Railway/DB.

Writes bounded JSON evidence and one listing screenshot. No credentials, no bypass.
"""
import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse, parse_qs
from playwright.sync_api import sync_playwright

SITES = {
    "wishket": {
        "projects": ("https://www.wishket.com/project/", r"^/project/[0-9]+/?$"),
        "partners": ("https://www.wishket.com/partners/", r"^/partners/p/[^/]+/?$"),
        "portfolios": ("https://www.wishket.com/partners/wishket-portfolio/?tab=all", r"^/partners/wishket-portfolio/[0-9]+/?$"),
    },
    "freemoa": {
        "projects": ("https://www.freemoa.net/m4/s41", r"^/m4/(?:s41\?pno=[0-9]+|[^/]+(?:\?.*?\b(?:pno|pjno)=[0-9]+.*)?)$"),
        "partners": ("https://www.freemoa.net/m7/s71", r"^/m7/freelance_detail\?fno=[0-9]+(?:&.*)?$"),
        "portfolios": ("https://www.freemoa.net/m7/s712", r"^/m7/(?:portfolio[^?]*|freelance_detail\?[^#]*\btab=[0-9]+.*)$"),
    },
    "wanted": {
        "projects": ("https://www.wanted.co.kr/gigs/projects", r"^/gigs/projects/[0-9]+/?$"),
        "partners": ("https://www.wanted.co.kr/gigs/premium", r"^/gigs/(?:premium|experts)/[0-9]+/?$"),
        "portfolios": ("https://www.wanted.co.kr/gigs/experts", r"^/gigs/(?:experts|premium)/[0-9]+/?$"),
    },
}
HOSTS = {
    "wishket": {"www.wishket.com","wishket.com"},
    "freemoa": {"www.freemoa.net","freemoa.net","m.freemoa.net"},
    "wanted": {"www.wanted.co.kr","wanted.co.kr"},
}
BLOCK_TERMS = ("request blocked","access denied","captcha","robot check")
IDENTIFIER_PATTERNS = [
    (re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}"), "[email]"),
    (re.compile(r"(?<!\d)(?:01[016789][-\s]?\d{3,4}[-\s]?\d{4})(?!\d)"), "[phone]"),
]
FIELDS = {
    "budget": re.compile(r"(?:예상\s*금액|예산|프로젝트\s*금액)\s*[:：]?\s*([\d,.]+\s*(?:만|억)?\s*원)", re.I),
    "period": re.compile(r"(?:예상\s*기간|진행\s*기간|개발\s*기간)\s*[:：]?\s*([^\n]{1,70})", re.I),
    "customer": re.compile(r"(?:고객사|클라이언트|발주처)\s*[:：]?\s*([^\n]{1,70})", re.I),
}

def recognized(site, section, url):
    if not url.startswith(("http://","https://")): return False
    p=urlparse(url)
    if p.hostname not in HOSTS[site]: return False
    path=p.path + ("?" + p.query if p.query else "")
    if site=="freemoa" and section=="projects":
        # Site has both desktop and mobile detail forms, e.g. /m4/s41?pno=41284.
        if p.path=="/m4/s41":return "pno" in parse_qs(p.query)
    return bool(re.match(SITES[site][section][1],path))

def redact(text):
    for pattern, substitute in IDENTIFIER_PATTERNS: text=pattern.sub(substitute,text)
    return text

def parse_record(site,section,url,title,body):
    out={"site":site,"section":section,"url":url,"title":redact(title[:230]),
         "body_excerpt":redact(body[:1300]),"source_id":None,"fields":{}}
    p=urlparse(url)
    if p.path=="/m4/s41":out["source_id"]=parse_qs(p.query).get("pno",[None])[0]
    elif p.path.endswith("/freelance_detail"):out["source_id"]=parse_qs(p.query).get("fno",[None])[0]
    else:
        pieces=p.path.rstrip("/").split("/")
        out["source_id"]=pieces[-1] if pieces else None
    for name,pattern in FIELDS.items():
        match=pattern.search(body)
        if match:out["fields"][name]=redact(match.group(1).strip())
    return out

def extract_links(page,site,section):
    nodes=page.locator("a[href]").evaluate_all(
        """els=>els.map(a=>({url:a.href,title:(a.innerText||a.getAttribute('aria-label')||'').trim()}))"""
    )
    result={}
    for node in nodes:
        link=node.get("url","").split("#",1)[0]
        if recognized(site,section,link) and link not in result:
            result[link]=redact(node.get("title","")[:150])
    return [{"url":url,"anchor":title} for url,title in result.items()]

def scan(site,section,outdir,max_records=4,timeout_ms=22000):
    started=datetime.now(timezone.utc).isoformat()
    entry,_=SITES[site][section]
    outdir=Path(outdir)
    outdir.mkdir(parents=True,exist_ok=True)
    report={"site":site,"section":section,"listing_url":entry,"started_utc":started,
            "status":"starting","http_status":None,"final_url":None,"listing_title":None,
            "discovered":0,"parsed":0,"links":[],"records":[],"xhr":[],"errors":[]}
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True,args=["--no-sandbox","--disable-dev-shm-usage"])
        context=browser.new_context(locale="ko-KR",viewport={"width":1366,"height":900})
        page=context.new_page()
        def watch_response(response):
            if response.request.resource_type not in ("xhr","fetch") or len(report["xhr"])>=60:return
            parsed=urlparse(response.url)
            if parsed.hostname not in HOSTS[site]:return
            report["xhr"].append({"path":parsed.path,"status":response.status,
                                  "resource_type":response.request.resource_type})
        page.on("response",watch_response)
        try:
            resp=page.goto(entry,wait_until="domcontentloaded",timeout=timeout_ms)
            report["http_status"]=resp.status if resp else None
            report["final_url"]=page.url
            if not resp or resp.status in (401,403,429):
                report["status"]="blocked_or_restricted"
            elif resp.status>=400:
                report["status"]="http_error"
            else:
                page.wait_for_timeout(1700)
                report["listing_title"]=redact(page.title()[:220])
                listing_text=page.locator("body").inner_text(timeout=6000)
                if any(s in listing_text[:900].lower() for s in BLOCK_TERMS):
                    report["status"]="blocked_or_restricted"
                else:
                    links=extract_links(page,site,section)
                    report["links"]=links[:100]
                    report["discovered"]=len(links)
                    report["listing_excerpt"]=redact(listing_text[:1000])
                    try:page.screenshot(path=str(outdir/"listing.png"),full_page=False,timeout=7500)
                    except Exception as exc:report["errors"].append("screenshot:"+type(exc).__name__)
                    report["status"]="links_found" if links else "listing_only_no_detail_links"
                    for item in links[:max_records]:
                        try:
                            dresp=page.goto(item["url"],wait_until="domcontentloaded",timeout=timeout_ms)
                            if not dresp or dresp.status!=200:
                                report["errors"].append("detail_http:"+str(dresp.status if dresp else None))
                                continue
                            page.wait_for_timeout(450)
                            body=page.locator("body").inner_text(timeout=6000)[:18000]
                            if not body or len(body)<120:continue
                            record=parse_record(site,section,item["url"],page.title(),body)
                            record["http_status"]=dresp.status
                            report["records"].append(record)
                            report["parsed"]+=1
                        except Exception as exc:
                            report["errors"].append("detail:"+type(exc).__name__+":"+str(exc)[:150])
                    if report["parsed"]:report["status"]="detail_parsed"
        except Exception as exc:
            report["status"]="navigation_error"
            report["errors"].append(type(exc).__name__+":"+str(exc)[:230])
        finally:
            context.close()
            browser.close()
    (outdir/"result.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({k:report[k] for k in ("site","section","status","http_status","discovered","parsed","errors")},ensure_ascii=False),flush=True)
    return report

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--site",choices=sorted(SITES),default="wishket")
    ap.add_argument("--section",choices=("projects","partners","portfolios"),default="projects")
    ap.add_argument("--limit",type=int,default=4)
    ap.add_argument("--output",default="artifacts/crawl-probe")
    args=ap.parse_args()
    if not 1<=args.limit<=10:ap.error("limit must be 1..10")
    scan(args.site,args.section,args.output,args.limit)

if __name__=="__main__": main()
