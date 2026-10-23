"""Detailed public Freemoa partner and portfolio collector.

The listing has JS-driven cards; follow real observed links and public detail
tabs. Does not fabricate portfolio links or equate partner names with projects.
Records enough source evidence to audit completeness and restrictions.
"""
import hashlib,json,logging,re,time
from urllib.parse import urlencode,urlsplit,parse_qs
from playwright.sync_api import sync_playwright
from db import session
from private_detail_utils import public_page_extract,parse_public_sections

ROOT="https://www.freemoa.net"
START={
 "freemoa_partners":ROOT+"/m7/s71",
 "freemoa_portfolios":ROOT+"/m7/s712"
}
PARTNER_RE=re.compile(r"/m7/freelance_detail\?fno=(\d+)")
PORT_RE=re.compile(r"/m7/(?:portfolio[^/?]*|port_detail)[^?#]*(?:\?[^#]*)?",re.I)


def _upsert(source,kind,url,title,text,meta):
    key=hashlib.sha256(url.encode()).hexdigest()[:24]
    with session() as db:
        row=db.execute("""
          INSERT INTO procureflow.market_records
            (source,kind,source_id,title,url,body,meta)
          VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb)
          ON CONFLICT(source,kind,source_id) DO UPDATE
             SET title=excluded.title,url=excluded.url,body=excluded.body,
                 meta=excluded.meta,last_seen=now()
          RETURNING xmax=0 AS fresh
        """,(source,kind,key,title[:350],url,text[:75000],
             json.dumps(meta,ensure_ascii=False))).fetchone()
    return bool(row["fresh"])


def _public_fnos(page):
    values=page.locator("a[href]").evaluate_all("""els=>els.map(x=>x.href||'')
                  .filter(x=>x.includes('/m7/freelance_detail?fno='))""")
    return list(dict.fromkeys(m.group(1) for u in values
                             if (m:=PARTNER_RE.search(u))))


def _cards(page):
    """Read candidate real DOM URL/onclick of cards without guessing path."""
    return page.evaluate("""() => [...document.querySelectorAll('a[href], [onclick], [data-pfno], [data-pfo-no], [data-portno]')]
      .map(e=>({tag:e.tagName,href:(e.href||e.getAttribute('href')||'').slice(0,250),
        onclick:(e.getAttribute('onclick')||'').slice(0,300),
        text:(e.innerText||'').replace(/\\s+/g,' ').trim().slice(0,180)}))
      .filter(x=>/portfolio|pfno|pfo.no|portno|portfol|\\/m7\\/|포트폴리오|상세보기/i.test(
        x.href+' '+x.onclick+' '+x.text)).slice(0,60)""")

def _text_evidence(page):
    raw=page.locator("body").inner_text(timeout=7000)
    data=public_page_extract(page)
    # Body.innerText preserves headings/newlines, while clone may flatten them.
    fixed=parse_public_sections(raw)
    data.update(fixed)
    return data

def _partner_details(page,fno):
    url=f"{ROOT}/m7/freelance_detail?fno={fno}"
    res=page.goto(url,wait_until="domcontentloaded",timeout=28000)
    if not res or res.status!=200:raise RuntimeError("partner_http_"+str(res.status if res else "missing"))
    page.wait_for_timeout(600)
    full=_text_evidence(page)
    titles=[x for x in full["headings"] if x and x not in ("포트폴리오","수행내역")]
    meta={"origin":"public_detail","profile_fno":fno,"public_tab_sections":{},
          "sections":full["sections"],"technologies":full["technologies"],
          "body_length":full["body_length"],"portfolio_reference_count":None,
          "headings":full["headings"],"images":full["images"][:24],
          "public_links":full["links"][:55]}
    mx=re.search(r"전체\s*포트폴리오\s*목록\s*\((\d+)\)",full["text"])
    if mx:meta["portfolio_reference_count"]=int(mx.group(1))
    m=re.search(r"파트너스\s*분류\s*([^\n]{1,60})",full["text"])
    if m:meta["partner_type"]=m.group(1).strip()[:60]
    m=re.search(r"파트너스\s*지역\s*([^\n]{1,70})",full["text"])
    if m:meta["region"]=m.group(1).strip()[:70]
    # Some tabs have separate server-rendered details; capture only pages
    # that contain real useful content (not the common project-request modal).
    for tab in ("1","2","3","4"):
        try:
            tr=page.goto(url+"&tab="+tab,wait_until="domcontentloaded",timeout=23000)
            if not tr or tr.status>=400:continue
            page.wait_for_timeout(330)
            tx=_text_evidence(page)
            if len(tx["text"])>150:
                tag={"1":"portfolios","2":"completed_projects",
                     "3":"skills","4":"career"}[tab]
                meta["public_tab_sections"][tag]={
                    "url":page.url,"body_length":tx["body_length"],
                    "technologies":tx["technologies"],
                    "text":tx["text"][:18000],
                    "headings":tx["headings"][:25],
                    "images":tx["images"][:25]}
        except Exception as ex:
            meta.setdefault("tab_errors",[]).append(tab+":"+type(ex).__name__)
    combined=full["text"]
    for tag,details in meta["public_tab_sections"].items():
        if len(details["text"])>150 and details["text"] not in combined:
            combined+="\n\n["+tag+"]\n"+details["text"]
    combined=combined[:75000]
    title=next((x for x in titles if len(x)>3 and "파트너스" not in x),
               f"프리모아 공개 파트너 {fno}")
    if len(combined)<350:raise RuntimeError("partner_detail_insufficient")
    fresh=_upsert("freemoa_partners","expert_supply",url,title,combined,meta)
    return {"url":url,"fresh":fresh,"text_length":len(combined),
            "tab_count":len(meta["public_tab_sections"]),
            "portfolio_reference_count":meta["portfolio_reference_count"]}


def _discover_portfolios(page,limit):
    """Observe JS card details first; never save a listing title alone."""
    samples=_cards(page)
    urls=[]
    for c in samples:
        m=PORT_RE.search(c.get("href") or "")
        if m:
            u=c["href"]
            if u.startswith(ROOT) and u not in urls:urls.append(u)
    diagnostic=[{"tag":x["tag"],"href":x["href"][:160],
                 "onclick":x["onclick"][:190],"text":x["text"][:90]}
                for x in samples[:12]]
    return urls[:limit],diagnostic


def collect(source,pages=1,limit=10):
    if source not in START:raise ValueError("unsupported_freemoa_deep_source")
    pages=max(1,min(int(pages),12))
    limit=max(1,min(int(limit),60))
    result={"source":source,"status":"started","discovered":0,
            "saved":0,"new":0,"details":[],"errors":[],"diagnostics":[]}
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True,args=["--no-sandbox","--disable-dev-shm-usage"])
        ctx=browser.new_context(locale="ko-KR",viewport={"width":1440,"height":900})
        page=ctx.new_page()
        seen=set()
        try:
            for n in range(1,pages+1):
                start=START[source]
                url=start+("?page="+str(n) if n>1 else "")
                res=page.goto(url,wait_until="domcontentloaded",timeout=35000)
                if not res or res.status>=400:
                    result["errors"].append("listing_http:"+str(res.status if res else None))
                    break
                page.wait_for_timeout(1200)
                if source=="freemoa_partners":
                    fnos=_public_fnos(page)
                    result["diagnostics"].append({"page":n,"partner_ids":len(fnos)})
                    for fno in fnos:
                        if fno in seen:continue
                        seen.add(fno)
                        result["discovered"]+=1
                        if result["saved"]>=limit:break
                        try:
                            item=_partner_details(page,fno)
                            result["saved"]+=1
                            result["new"]+=int(item["fresh"])
                            result["details"].append(item)
                            logging.info("FREEMOA_PARTNER_DEEP fno=%s body=%s tabs=%s portfolio_count=%s",
                                         fno,item["text_length"],item["tab_count"],
                                         item["portfolio_reference_count"])
                        except Exception as ex:
                            result["errors"].append(fno+":"+type(ex).__name__+":"+str(ex)[:100])
                    if result["saved"]>=limit:break
                else:
                    urls,diagnostic=_discover_portfolios(page,limit)
                    result["diagnostics"].append({"page":n,"portfolio_links":len(urls),
                                                  "card_dom":diagnostic})
                    logging.info("FREEMOA_PORTFOLIO_LIST_DIAG %s",
                                 json.dumps(result["diagnostics"][-1],ensure_ascii=False)[:2600])
                    for detail in urls:
                        if detail in seen:continue
                        seen.add(detail)
                        try:
                            dr=page.goto(detail,wait_until="domcontentloaded",timeout=25000)
                            if not dr or dr.status>=400:continue
                            body=_text_evidence(page)
                            if body["body_length"]<250:continue
                            meta={"origin":"public_portfolio_detail",
                                  "sections":body["sections"],
                                  "technologies":body["technologies"],
                                  "images":body["images"][:40],
                                  "public_links":body["links"][:45],
                                  "body_length":body["body_length"]}
                            title=next((v for v in body["headings"] if len(v)>4),page.title())
                            fresh=_upsert(source,"portfolio_reference",detail,title,
                                          body["text"],meta)
                            result["saved"]+=1
                            result["new"]+=int(fresh)
                            result["details"].append({"url":detail,"fresh":fresh,
                                                      "body_length":body["body_length"]})
                        except Exception as ex:
                            result["errors"].append("portfolio:"+type(ex).__name__+
                                                     ":"+str(ex)[:100])
                    if result["saved"]>=limit:break
            result["status"]=("collected" if result["saved"] and not result["errors"]
                              else "partial" if result["saved"]
                              else "discovery_only" if not result["errors"]
                              else "error")
        except Exception as ex:
            result["status"]="error"
            result["errors"].append(type(ex).__name__+":"+str(ex)[:150])
        finally:
            ctx.close()
            browser.close()
    return result
