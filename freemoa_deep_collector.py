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


def _upsert(source,kind,url,title,text,meta,source_id=None):
    key=source_id or hashlib.sha256(url.encode()).hexdigest()[:24]
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
    """Portfolio cards invoke showPortfolio('<real ID>') rather than anchor URLs."""
    cards=page.locator('[onclick*="showPortfolio"]').evaluate_all(
        """els=>els.map(e=>({event:e.getAttribute('onclick')||'',
          label:(e.innerText||'').replace(/\s+/g,' ').trim().slice(0,260)}))""")
    results=[]
    for c in cards:
        m=re.search(r"showPortfolio\s*\(\s*['\"]?(\d+)",c["event"])
        if m and m.group(1) not in results:
            results.append(m.group(1))
    return results[:limit],[{"event":x["event"][:120],
                             "label":x["label"][:180]} for x in cards[:10]]

def portfolio_title_from_card(label,portfolio_id):
    """Use real visible card label, never an invented generic title."""
    title=re.split(r"\s*#",label or "",maxsplit=1)[0]
    title=title.lstrip("+").strip()
    return title[:280] if title else "프리모아 포트폴리오 "+str(portfolio_id)


def _visible_modal(page):
    """Read the actual visible portfolio modal after clicking the source card."""
    data=page.evaluate("""() => {
      const nodes=[...document.querySelectorAll('[role="dialog"],.modal,.modal-dialog,[id*="portfolio"],[id*="Portfolio"],[class*="portfolio"],[class*="Portfolio"]')];
      return nodes.filter(e=>e.getClientRects().length>0)
         .map(e=>({selector:String(e.id||e.className||'').slice(0,120),
                   text:(e.innerText||'').trim().slice(0,25000)}))
         .filter(x=>x.text.length>230 && x.text.length<25000 &&
                   !x.text.includes('제 1 조 (목적) :::'))
         .sort((a,b)=>Number(b.text.includes('프로젝트 요약'))-
                       Number(a.text.includes('프로젝트 요약')))
         .slice(0,12);
    }""")
    selected=next((x["text"] for x in data if
                  "프로젝트 요약" in x["text"]
                  and "포트폴리오 타이틀이 입력되는 공간" not in x["text"][:140]),"")
    return selected,data[:10]


def _expand_public_modal(page):
    try:
        count=page.evaluate("""() => {
           let clicked=0;
           for(const e of [...document.querySelectorAll('a,button,span,div')]){
              if(clicked>=4)break;
              if(!e.getClientRects().length)continue;
              const t=(e.innerText||'').trim();
              if((t==='펼치기'||t==='+ 펼치기'||t==='더보기')
                && e.closest('[class*="portfolio"],[class*="modal"],[role="dialog"]')){
                  e.click();clicked++;
              }
           }
           return clicked;
        }""")
        if count:page.wait_for_timeout(350)
        return count
    except Exception:return 0


def collect(source,pages=1,limit=10,page_start=1):
    if source not in START:raise ValueError("unsupported_freemoa_deep_source")
    pages=max(1,min(int(pages),12))
    limit=max(1,min(int(limit),60))
    page_start=max(1,min(int(page_start),100000))
    result={"source":source,"status":"started","discovered":0,
            "saved":0,"new":0,"details":[],"errors":[],"diagnostics":[],
            "page_start":page_start,"last_page":page_start,"has_more":False,
            "page_fingerprint":""}
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True,args=["--no-sandbox","--disable-dev-shm-usage"])
        ctx=browser.new_context(locale="ko-KR",viewport={"width":1440,"height":900})
        page=ctx.new_page()
        seen=set()
        try:
            seen_fingerprints=set()
            for n in range(page_start,page_start+pages):
                result["last_page"]=n
                start=START[source]
                url=start+("?page="+str(n) if n>1 else "")
                res=page.goto(url,wait_until="domcontentloaded",timeout=35000)
                if not res or res.status>=400:
                    result["errors"].append("listing_http:"+str(res.status if res else None))
                    break
                page.wait_for_timeout(1200)
                if source=="freemoa_partners":
                    fnos=_public_fnos(page)
                    fingerprint=hashlib.sha256("|".join(fnos).encode()).hexdigest()[:24] if fnos else ""
                    if fingerprint and fingerprint in seen_fingerprints:
                        result["has_more"]=False
                        result["diagnostics"].append({"page":n,"repeated_page":True})
                        break
                    seen_fingerprints.add(fingerprint)
                    result["page_fingerprint"]=fingerprint
                    result["has_more"]=len(fnos)>=10
                    result["diagnostics"].append({"page":n,"partner_ids":len(fnos)})
                    if not fnos:break
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
                    ids,diagnostic=_discover_portfolios(page,limit)
                    fingerprint=hashlib.sha256("|".join(ids).encode()).hexdigest()[:24] if ids else ""
                    if fingerprint and fingerprint in seen_fingerprints:
                        result["has_more"]=False
                        result["diagnostics"].append({"page":n,"repeated_page":True})
                        break
                    seen_fingerprints.add(fingerprint)
                    result["page_fingerprint"]=fingerprint
                    result["has_more"]=len(ids)>=10
                    if not ids:break
                    source_labels={}
                    for original in diagnostic:
                        found=re.search(r"showPortfolio\s*\(\s*['\"]?(\d+)",
                                        original["event"])
                        if found:source_labels[found.group(1)]=original["label"]
                    result["discovered"]+=len(ids)
                    result["diagnostics"].append({
                        "page":n,"js_portfolio_cards":len(ids),
                        "card_dom":diagnostic[:8]})
                    logging.info("FREEMOA_PORTFOLIO_LIST_DIAG %s",
                                 json.dumps(result["diagnostics"][-1],
                                            ensure_ascii=False)[:2000])
                    for portfolio_id in ids:
                        if portfolio_id in seen:continue
                        seen.add(portfolio_id)
                        if result["saved"]>=limit:break
                        try:
                            # Reload to close previous modal before click.
                            rr=page.goto(url,wait_until="domcontentloaded",
                                         timeout=26000)
                            if not rr or rr.status>=400:continue
                            page.wait_for_timeout(600)
                            cards=page.locator('[onclick*="showPortfolio"]')
                            target=None
                            for ci in range(min(cards.count(),150)):
                                x=cards.nth(ci)
                                event=x.get_attribute("onclick") or ""
                                if re.search(r"showPortfolio\s*\(\s*['\"]?"+
                                             re.escape(portfolio_id)+r"\b",event):
                                    target=x
                                    break
                            if target is None:
                                result["errors"].append("missing_js_card:"+portfolio_id)
                                continue
                            label=target.inner_text(timeout=1800).strip()
                            before=page.locator("body").inner_text(timeout=3500)
                            # A JavaScript-bound card can be hidden under a
                            # large floating layer; dispatch its own DOM click
                            # rather than requiring a physical pointer hit.
                            before_pages=len(ctx.pages)
                            network=[]
                            def capture(resp):
                                if any(k in resp.url.lower() for k in
                                       ("portfolio","/m7/","/api/")):
                                    network.append({
                                        "url":resp.url.split("?")[0][:160],
                                        "status":resp.status})
                            page.on("response",capture)
                            target.evaluate("(e)=>e.click()")
                            page.wait_for_timeout(1900)
                            modal,candidates=_visible_modal(page)
                            if not modal:
                                page.wait_for_timeout(850)
                                modal,candidates=_visible_modal(page)
                            # Expand only AFTER the real project-summary panel
                            # is identified; broad global clicks can change
                            # unrelated search-list paging.
                            expanded=0
                            if modal:
                                expanded=_expand_public_modal(page)
                                if expanded:
                                    expanded_text,_=_visible_modal(page)
                                    if expanded_text and len(expanded_text)>len(modal):
                                        modal=expanded_text
                            if not modal and len(ctx.pages)>before_pages:
                                popped=ctx.pages[-1]
                                popped.wait_for_load_state("domcontentloaded",timeout=6000)
                                modal=popped.locator("body").inner_text(timeout=4500)[:27000]
                            after=page.locator("body").inner_text(timeout=3500)
                            if not modal and after!=before:
                                idx=after.find("프로젝트 요약")
                                if idx>=0:
                                    modal=after[idx:idx+18000]
                            if not modal:
                                logging.info("FREEMOA_MODAL_DOM_DIAG id=%s changed=%s before=%s after=%s nodes=%s network=%s",
                                    portfolio_id,before!=after,len(before),len(after),
                                    json.dumps([{"id":x["selector"],"length":len(x["text"]),
                                                 "sample":x["text"][:170]} for x in candidates[:7]],
                                               ensure_ascii=False)[:1150],
                                    json.dumps(network[:6],ensure_ascii=False)[:700])
                            parsed=parse_public_sections(modal)
                            if parsed["body_length"]<230:
                                result["errors"].append("modal_no_real_detail:"+portfolio_id)
                                logging.warning(
                                    "FREEMOA_MODAL_EMPTY id=%s nodes=%s",
                                    portfolio_id,json.dumps([
                                        {"selector":x["selector"],"length":len(x["text"])}
                                        for x in candidates],ensure_ascii=False)[:700])
                                continue
                            title=portfolio_title_from_card(
                                label if label else source_labels.get(portfolio_id,""),
                                portfolio_id)
                            # Modal has no URL; store truthful source page + real ID.
                            source_url=ROOT+"/m7/s712"
                            media=page.evaluate("""() => {
                                const nodes=[...document.querySelectorAll(
                                    '[role="dialog"],.modal,.modal-dialog,[id*="portfolio"],[id*="Portfolio"]')]
                                   .filter(e=>e.getClientRects().length && (e.innerText||'').includes('프로젝트 요약'));
                                const parent=nodes.sort((a,b)=>(a.innerText||'').length-(b.innerText||'').length)[0];
                                if(!parent)return {images:[],links:[]};
                                const images=[...parent.querySelectorAll('img[src]')]
                                  .filter(e=>e.getClientRects().length)
                                  .map(e=>({url:(e.currentSrc||e.src||'').slice(0,700),
                                           alt:(e.alt||'').slice(0,200)}))
                                  .filter(e=>/^https:\\/\\//.test(e.url)).slice(0,60);
                                const links=[...parent.querySelectorAll('a[href]')]
                                  .map(e=>({url:(e.href||'').slice(0,700),
                                           label:(e.innerText||'').slice(0,160)}))
                                  .filter(e=>/^https:\\/\\//.test(e.url)).slice(0,40);
                                return {images,links}
                            }""")
                            meta={"origin":"public_javascript_portfolio_modal",
                                  "portfolio_id":portfolio_id,
                                  "source_page":source_url,
                                  "listing_page":url,
                                  "card_label":label[:300],
                                  "verified_project_summary":True,
                                  "expanded_more":expanded,
                                  "sections":parsed["sections"],
                                  "technologies":parsed["technologies"],
                                  "body_length":parsed["body_length"],
                                  "images":media["images"],
                                  "public_links":media["links"],
                                  "modal_structure":[{"selector":x["selector"],
                                    "body_length":len(x["text"])} for x in candidates]}
                            fresh=_upsert(source,"portfolio_reference",source_url,
                                          title,parsed["text"],meta,
                                          source_id=portfolio_id)
                            result["saved"]+=1
                            result["new"]+=int(fresh)
                            result["details"].append({
                                "portfolio_id":portfolio_id,
                                "title":title[:130],
                                "body_length":parsed["body_length"],
                                "fresh":fresh})
                            logging.info("FREEMOA_PORTFOLIO_DEEP id=%s length=%s new=%s",
                                         portfolio_id,parsed["body_length"],fresh)
                        except Exception as ex:
                            result["errors"].append("portfolio_"+portfolio_id+":"+
                                  type(ex).__name__+":"+str(ex)[:95])
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
