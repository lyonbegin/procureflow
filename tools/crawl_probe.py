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
        "projects": ("https://www.freemoa.net/m4/s41?page=1", r"^/m4/(?:s41\?pno=[0-9]+|[^/]+(?:\?.*?\b(?:pno|pjno)=[0-9]+.*)?)$"),
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
        # Never confuse the project creation form with a published project.
        # Confirmed public desktop/mobile detail form: /m4/s41?pno=<number>.
        value=parse_qs(p.query).get("pno",[""])[0]
        return p.path=="/m4/s41" and bool(re.fullmatch(r"[0-9]+",value))
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


def extract_freemoa_project_cards(page):
    """Read Freemoa's real click-cards, which expose data-pno rather than href.

    These records reflect the public LISTING, not yet the opened detail modal.
    """
    cards=page.locator("#projectListNew > li.proj-list-item_li_new").evaluate_all("""
        nodes => nodes.map(li => {
          const titleNode=li.querySelector('.projTitle[data-pno]');
          if(!titleNode) return null;
          const pno=titleNode.getAttribute('data-pno');
          if(!/^\\d+$/.test(pno||'')) return null;
          const data=[...li.querySelectorAll(':scope > div.projectInfo')];
          const top=titleNode.parentElement;
          const headings=[...top.querySelectorAll(':scope > div:not(.projTitle) > p')]
                           .map(p=>p.textContent.trim()).filter(Boolean);
          const tags=data[0] ? [...data[0].querySelectorAll('p')]
                           .map(p=>p.textContent.trim()).filter(Boolean) : [];
          const categories=data[0]?.querySelector(':scope > div')?.textContent.trim() || '';
          const metrics={};
          for(const p of data[1]?.querySelectorAll(':scope > p') || []){
            const k=p.querySelector('span')?.textContent.trim();
            const v=p.querySelector('b')?.textContent.trim();
            if(k&&v) metrics[k]=v;
          }
          const client=data[2]?.querySelector('div > div > p > span')?.textContent.trim() || null;
          const region=data[2]?.querySelector('div > div > p > b')?.textContent.trim() || null;
          const summary=data[2]?.firstElementChild?.textContent.trim() || '';
          return {
            source_id:pno,
            url:'https://m.freemoa.net/m4/s41?pno='+encodeURIComponent(pno),
            title:titleNode.querySelector('p.title')?.textContent.trim()||'',
            work_type:headings[0]||null,
            status:headings[1]||null,
            categories,tags,metrics,summary:summary.slice(0,2200),
            client_alias:client,region
          };
        }).filter(Boolean)
    """)
    results=[]
    for card in cards:
        if not card.get("title"):continue
        metrics=card.pop("metrics")
        desc=card.pop("summary")
        results.append({
            "site":"freemoa","section":"projects",
            "source_id":card["source_id"],
            "url":card["url"],
            "title":redact(card["title"][:230]),
            "body_excerpt":redact(desc[:1300]),
            "fields":{
                "budget":metrics.get("예상비용"),
                "monthly_pay":metrics.get("월 임금"),
                "period":metrics.get("예상기간"),
                "applicants":metrics.get("지원자수"),
                "deadline":metrics.get("마감일정"),
                "categories":card["categories"],
                "tags":card["tags"],
                "work_type":card["work_type"],
                "status":card["status"],
                "client_alias":redact(card["client_alias"] or ""),
                "region":card["region"],
            },
            "evidence":"public_listing_card",
            "detail_verified":False,
        })
    return results

def extract_freemoa_project_details(page, cards, report, max_records=10):
    """Open real public project detail popup by clicking the data-pno card.

    The listing text is not accepted as project detail. Attach full public modal
    content only after the modal title matches the clicked project.
    """
    valid=0
    report["detail_diagnostics"]=[]
    for record in cards[:max_records]:
        pno=record["source_id"]
        title=record["title"]
        diag={"source_id":pno,"listing_title":title,"opened":False}
        try:
            locator=page.locator(f'#projectListNew .projTitle[data-pno="{pno}"]').first
            with page.expect_response(lambda resp: "/m4a/s41v" in resp.url,timeout=10000) as detail_event:
                locator.click(timeout=9000)
            detail_response=detail_event.value
            detail_response.finished()
            request=detail_response.request
            diag["xhr_request_method"]=request.method
            diag["xhr_request_path"]=urlparse(request.url).path
            try:
                detail_text=detail_response.text()
                diag["xhr_body_method"]="chromium_response"
            except Exception as body_exc:
                diag["chromium_read_error"]=type(body_exc).__name__+":"+str(body_exc)[:130]
                # Read the same public response via the site's own browser
                # context (same-origin fetch), retaining normal TLS validation.
                browser_result=page.evaluate("""async req=>{
                    const headers={
                        'Accept':'application/json, text/javascript, */*; q=0.01',
                        'X-Requested-With':'XMLHttpRequest'
                    };
                    if(req.contentType) headers['Content-Type']=req.contentType;
                    const opts={method:req.method,headers,credentials:'same-origin'};
                    if(req.method!=='GET')opts.body=req.body;
                    const resp=await fetch(req.url,opts);
                    return {status:resp.status,body:await resp.text()};
                }""",{
                    "url":request.url,
                    "method":request.method,
                    "body":request.post_data,
                    "contentType":request.headers.get("content-type","")
                })
                detail_text=browser_result["body"]
                diag["xhr_body_method"]="same_origin_browser_fetch"
                diag["xhr_retry_status"]=browser_result["status"]
            diag["xhr_http_status"]=detail_response.status
            diag["xhr_chars"]=len(detail_text)
            diag["xhr_excerpt"]=redact(detail_text[:16000])
            diag["xhr_content_type"]=detail_response.headers.get("content-type","")
            detail_json=None
            try:
                detail_json=json.loads(detail_text)
                diag["xhr_json_type"]=type(detail_json).__name__
                if isinstance(detail_json,dict): diag["xhr_keys"]=list(detail_json)[:35]
            except (ValueError,TypeError):
                pass
            if isinstance(detail_json,dict) and detail_json.get("ERROR",{}).get("NO")==-1:
                diag["requires_login"]=True
                diag["auth_message"]=str(detail_json["ERROR"].get("MSG",""))[:100]
                # Try only the publicly available mobile project URL.
                # No passwords, cookie injection, access-control bypass or
                # replays of restricted endpoints.
                mobile=page.context.new_page()
                try:
                    candidate=record["url"]
                    mobile_resp=mobile.goto(candidate,wait_until="commit",timeout=16000)
                    mobile.wait_for_timeout(1200)
                    mobile_text=mobile.locator("body").inner_text(timeout=6000)
                    diag["mobile_http"]=mobile_resp.status if mobile_resp else None
                    diag["mobile_final_url"]=mobile.url
                    diag["mobile_title"]=mobile.title()[:170]
                    diag["mobile_text_length"]=len(mobile_text)
                    diag["mobile_text_excerpt"]=redact(mobile_text[:1500])
                    if mobile_resp and mobile_resp.status==200 and title in mobile_text:
                        # Do not confuse snippets with a complete project brief.
                        mobile_desc=mobile.locator("#projectInfoDataDetail").first
                        desc=(mobile_desc.inner_text(timeout=1000) if mobile_desc.count() else "")
                        if len(desc.strip())>=120 and not desc.strip().endswith("..."):
                            record["detail"]={"project_description":redact(desc[:25000]),
                                              "origin":"public_mobile_detail"}
                            record["detail_verified"]=True
                            record["evidence"]="public_mobile_detail"
                            record["body_excerpt"]=redact(desc[:1300])
                            valid+=1
                            diag["description_chars"]=len(desc)
                except Exception as mobile_exc:
                    diag["mobile_error"]=type(mobile_exc).__name__+":"+str(mobile_exc)[:170]
                finally:
                    mobile.close()
                report["detail_diagnostics"].append(diag)
                continue
            try:
                page.wait_for_function("""expected => {
                    const root=document.querySelector('#projectViewWrap');
                    if(!root || getComputedStyle(root).display==='none') return false;
                    const v=root.querySelector('.projectInfoData[data-name="title"]');
                    const text=(v?.textContent||'').trim();
                    return text && text===expected;
                }""",arg=title,timeout=12000)
                diag["opened"]=True
            except Exception as e:
                diag["wait_error"]=type(e).__name__
                diag["modal_visible"]=page.locator("#projectViewWrap").is_visible()
                diag["page_url_after_click"]=page.url
                diag["modal_title"]=page.locator('#projectViewWrap [data-name="title"]').first.text_content(timeout=2000)[:200]
                report["detail_diagnostics"].append(diag)
                continue

            detail=page.locator("#projectViewWrap").evaluate("""root=>{
                const t=selector => (root.querySelector(selector)?.textContent||'').trim();
                const many=selector=>[...root.querySelectorAll(selector)].map(el=>(el.textContent||'').trim());
                const prop=(name)=>t('[data-name="'+name+'"]');
                return {
                    title:prop('title'),
                    registered_at:t('.projectInfoDate'),
                    budget:prop('costView'),
                    period_days:prop('during'),
                    kickoff:prop('BEGIN_EXPECT'),
                    project_area:prop('proj_filed_new'),
                    project_class:t('.projectType'),
                    planning_stage:prop('plan_nm'),
                    meeting_area:prop('pvNmu'),
                    deadline:t('.enddate_custom'),
                    work_type:t('#projectWorkType'),
                    project_description:t('#projectInfoDataDetail'),
                    recruit_requirements:t('#recruitMemoDiv .recruitMemo'),
                    client_alias:t('.companyUserId'),
                    client_company_info:t('#projectViewClientCompanyInfo'),
                    client_post_count:prop('all_cnt'),
                    client_contract_count:prop('contract_cnt'),
                    client_contract_amount:prop('sum_cost'),
                    related_technologies:many('.prj-need-tech-new span,.prj-need-tech-new b'),
                    summary:t('#projectViewConMidArticle'),
                    visible_text:(root.innerText||'').slice(0,18000)
                }
            }""")
            detail={k:(redact(v[:30000]) if isinstance(v,str) else v) for k,v in detail.items()}
            desc=detail.get("project_description") or ""
            requirements=detail.get("recruit_requirements") or ""
            if len(desc)+len(requirements)<90:
                diag["reason"]="Detail popup appeared but public description too short"
                diag["desc_len"]=len(desc)
                diag["recruit_len"]=len(requirements)
                report["detail_diagnostics"].append(diag)
                continue
            record["detail_verified"]=True
            record["evidence"]="public_clicked_detail_modal"
            record["detail"]=detail
            record["body_excerpt"]=desc[:1300]
            valid+=1
            diag["description_chars"]=len(desc)
            diag["recruitment_chars"]=len(requirements)
            diag["client_alias"]=detail.get("client_alias")
            report["detail_diagnostics"].append(diag)
        except Exception as e:
            diag["error"]=type(e).__name__+":"+str(e)[:160]
            report["detail_diagnostics"].append(diag)
        finally:
            # Close modal through public UI if possible; otherwise restore listing
            # without trying to bypass any access restriction.
            try:
                page.keyboard.press("Escape")
                if page.locator("#projectViewWrap").is_visible():
                    # The DOM has a separate popup outside the listing. Hiding it
                    # only resets this browser view for the next already-visible card.
                    page.evaluate("""()=>{
                        document.querySelector('#projectViewWrap')?.style.setProperty('display','none');
                    }""")
            except Exception:
                pass
    report["detail_records_parsed"]=valid
    return valid


def scan(site,section,outdir,max_records=4,timeout_ms=22000,storage_state=None):
    started=datetime.now(timezone.utc).isoformat()
    entry,_=SITES[site][section]
    outdir=Path(outdir)
    outdir.mkdir(parents=True,exist_ok=True)
    report={"site":site,"section":section,"listing_url":entry,"started_utc":started,
            "status":"starting","http_status":None,"final_url":None,"listing_title":None,
            "discovered":0,"parsed":0,"links":[],"records":[],"xhr":[],"errors":[]}
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True,args=["--no-sandbox","--disable-dev-shm-usage"])
        opts={"locale":"ko-KR","viewport":{"width":1366,"height":900}}
        if storage_state:
            statefile=Path(storage_state).expanduser().resolve()
            if not statefile.is_file():raise FileNotFoundError(str(statefile))
            opts["storage_state"]=str(statefile)
        context=browser.new_context(**opts)
        page=context.new_page()
        def watch_response(response):
            if response.request.resource_type not in ("xhr","fetch") or len(report["xhr"])>=60:return
            parsed=urlparse(response.url)
            if parsed.hostname not in HOSTS[site]:return
            report["xhr"].append({"path":parsed.path,"status":response.status,
                                  "resource_type":response.request.resource_type})
        page.on("response",watch_response)
        try:
            if site=="freemoa" and section=="projects":
                # ?page=1 can stall in GitHub-hosted runners. Retry known public list paths.
                resp=None
                for candidate in (entry,
                        "https://www.freemoa.net/m4/s41",
                        "https://m.freemoa.net/m4/s41?page=1"):
                    try:
                        resp=page.goto(candidate,wait_until="commit",timeout=12000)
                        page.wait_for_selector("#projectListNew > li.proj-list-item_li_new",
                            state="attached",timeout=13000)
                        report["working_listing_url"]=candidate
                        break
                    except Exception as navigation_exc:
                        report["errors"].append("listing_attempt:"+candidate+":"+
                            type(navigation_exc).__name__)
                        resp=None
            else:
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
                    special=(site=="freemoa" and section=="projects")
                    cards=extract_freemoa_project_cards(page) if special else []
                    links=([{"url":card["url"],"anchor":card["title"]} for card in cards]
                           if special else extract_links(page,site,section))
                    report["links"]=links[:100]
                    report["discovered"]=len(links)
                    report["listing_excerpt"]=redact(listing_text[:1000])
                    try:page.screenshot(path=str(outdir/"listing.png"),full_page=False,timeout=7500)
                    except Exception as exc:report["errors"].append("screenshot:"+type(exc).__name__)
                    report["status"]="links_found" if links else "listing_only_no_detail_links"
                    if special:
                        report["list_cards_parsed"]=len(cards)
                        report["detail_records_parsed"]=0
                        report["records"]=cards[:max_records]
                        report["parsed"]=len(report["records"])
                        if report["parsed"]:
                            report["status"]="listing_cards_parsed"
                            if extract_freemoa_project_details(page,report["records"],report,max_records):
                                report["status"]="detail_modal_parsed"
                            else:
                                auth_ids=[d["source_id"] for d in report.get("detail_diagnostics",[])
                                          if d.get("requires_login")]
                                report["auth_required_project_ids"]=auth_ids
                                report["status"]=("detail_login_required" if auth_ids
                                                  else "listing_cards_only_no_detail")
                    for item in ([] if special else links[:max_records]):
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
                    if report["parsed"] and not special:report["status"]="detail_parsed"
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
    ap.add_argument("--storage-state",default=None,help="Local authenticated Freemoa session JSON; never commit or upload")
    args=ap.parse_args()
    if not 1<=args.limit<=10:ap.error("limit must be 1..10")
    scan(args.site,args.section,args.output,args.limit,storage_state=args.storage_state)

if __name__=="__main__": main()
