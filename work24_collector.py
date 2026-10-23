"""Read-only Work24 recruitment leads collector.

ProcureFlow records staffing demand as *potential service leads*, not as actual
procurement tenders. The source and original recruitment ID are preserved.
No applicant/contact records are fetched and no applications are submitted.

The government Open API is preferred if WORK24_API_KEY is issued later.
This bounded browser adapter works with publicly viewable job listing/details.
"""
from __future__ import annotations
import json
import os
import logging
import re
import time
from datetime import datetime,timezone
from urllib.parse import parse_qs, urlparse, urlencode

from playwright.sync_api import sync_playwright
from db import session

BASE="https://www.work24.go.kr"
LIST_PATH="/wk/a/b/1200/retriveDtlEmpSrchList.do"
DETAIL_PATH="/wk/a/b/1500/empDetailAuthView.do"
SERVICE_TAGS = [
 ("cleaning",r"청소|미화|환경미화|환경관리|방역|소독|세척|클리닝|하우스키핑"),
 ("security",r"경비|보안|방재|주차관리|시설경비|안전관리"),
 ("facility",r"시설관리|건물관리|설비관리|기계설비|전기관리|소방시설|공조|빌딩관리"),
 ("transport",r"운전|배송|운송|물류|택배|화물|이사|배차|출고|입고"),
 ("development",r"프로그래밍|개발자|소프트웨어|정보화|전산|웹개발|앱개발|AI 개발|ERP|MES|서버 개발"),
 ("environment",r"폐기물|재활용|분리수거|음식물쓰레기|자원순환"),
 ("administration",r"사무보조|행정지원|민원안내|접수|운영지원|비서"),
 ("education",r"교육운영|강사|교사|강의|훈련운영|교수"),
 ("events",r"행사운영|전시|전시회|박람회|이벤트|축제운영"),
 ("design",r"디자인|광고|마케팅|홍보|영상편집|콘텐츠 제작"),
]
CONTACT_CUT = re.compile(r"(?:채용\s*담당자|채용담당자\s*정보)(?:\s|\n|$)")
EMAIL = re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}")
MOBILE = re.compile(r"(?<!\d)01[016789][- ]?\d{3,4}[- ]?\d{4}(?!\d)")


def detail_ref(url: str):
    p=urlparse(url)
    if p.scheme!="https" or p.hostname not in ("www.work24.go.kr","work24.go.kr"):
        return None
    if p.path!=DETAIL_PATH:
        return None
    q=parse_qs(p.query)
    wanted=q.get("wantedAuthNo",[""])[0].strip()
    info=q.get("infoTypeCd",[""])[0].strip()
    group=q.get("infoTypeGroup",[""])[0].strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{4,75}",wanted) or not re.fullmatch(r"[A-Za-z0-9_-]{2,40}",info):
        return None
    if group and not re.fullmatch(r"[A-Za-z0-9_-]{2,50}",group):
        return None
    # Work24 authentic listing ID + originating data provider id (avoid collision).
    return {"wantedAuthNo":wanted,"infoTypeCd":info,"infoTypeGroup":group,
            "source_id":f"{info}:{wanted}"}


def normalize_detail_url(url: str) -> str:
    ref=detail_ref(url)
    if ref is None:raise ValueError("invalid_work24_detail_url")
    params={"wantedAuthNo":ref["wantedAuthNo"],"infoTypeCd":ref["infoTypeCd"]}
    if ref["infoTypeGroup"]:params["infoTypeGroup"]=ref["infoTypeGroup"]
    return BASE+DETAIL_PATH+"?"+urlencode(params)


def classify(text: str) -> str:
    for area,regex in SERVICE_TAGS:
        if re.search(regex,text,re.I):return area
    return "other"


def list_links(page) -> list[dict]:
    anchors=page.locator('a[href]').evaluate_all(
       """items => items.map(a => ({
          url:a.href, label:(a.innerText||a.getAttribute('title')||'').trim().slice(0,280),
          context:(a.closest('tr,li,article')||a).innerText?.trim().slice(0,700)||''
       }))"""
    )
    found={}
    for a in anchors:
        ref=detail_ref(a["url"])
        if not ref:continue
        found.setdefault(ref["source_id"],{
            **ref,"url":normalize_detail_url(a["url"]),
            "listing_title":a["label"],"listing_excerpt":a["context"]})
    return list(found.values())


def read_detail(page, card):
    url=card["url"]
    response=page.goto(url,wait_until="domcontentloaded",timeout=27000)
    if not response or response.status>=400:
        raise RuntimeError(f"detail_http_{response.status if response else 'no_response'}")
    page.wait_for_timeout(700)
    current=detail_ref(page.url)
    if not current or current["source_id"]!=card["source_id"]:
        raise RuntimeError("detail_not_matched")
    raw=page.locator("body").inner_text(timeout=6500)
    if "요청하신 페이지에 일시적인 문제가 발생했습니다" in raw:
        raise RuntimeError("work24_server_error_page")
    if "모집요강" not in raw or "근무조건" not in raw:
        raise RuntimeError("not_a_complete_job_detail")
    parts=raw.splitlines()
    # Work24's front matter contains '채용정보 상세' then employer then
    # job title; anchor the extraction on that explicit page heading.
    textlines=[s.strip() for s in parts if s.strip()]
    summary=textlines
    header_positions=[i for i,t in enumerate(textlines) if t.startswith("채용정보 상세")]
    frontpos=header_positions[-1] if header_positions else None
    if frontpos is not None:
        summary=textlines[frontpos+1:frontpos+22]
    bad={"일반기업","공공기관","가족","상세정보","정보제공처","조회수",
         "채용정보 제공 사이트 바로가기","링크 복사","이메일 전송","인쇄하기",
         "모집요강","근무조건","복리후생","기업정보","전형방법"}
    title=card.get("listing_title","").strip()
    if not title or title in ("상세보기","채용정보",""):
        # Job title immediately before the provider/view-count block.
        for i,item in enumerate(summary):
            if item.startswith("정보제공처") and i>=1:
                candidate=summary[i-1].strip()
                if candidate not in bad and len(candidate)>=5:title=candidate
                break
    if not title or title in bad:
        title=next((t for t in summary if len(t)>14 and t not in bad),"")
    if not title:raise RuntimeError("title_not_extracted")
    company=""
    if frontpos is not None:
        tail=textlines[frontpos+1:frontpos+22]
        if "기업정보" in tail:
            ix=tail.index("기업정보")
            next_names=[t for t in tail[ix+1:ix+5] if t not in bad and t!=title]
            if next_names:company=next_names[0][:160]
        if not company:
            for item in tail:
                if (item!=title and item not in bad and not item.startswith(("정보제공처","조회수"))
                        and not re.search(r"공유하기|링크|로그인|스크랩",item) and len(item)>1):
                    company=item[:160];break
    # Do not repurpose applicant contact details for marketing/sales leads.
    publicbody=CONTACT_CUT.split(raw,maxsplit=1)[0][-25000:]
    publicbody=EMAIL.sub("[email redacted]",MOBILE.sub("[phone redacted]",publicbody))
    provider={"VALIDATION":"고용24","CJK":"잡코리아"}.get(card["infoTypeCd"],card["infoTypeCd"])
    area=classify((title+" "+publicbody[:4000])[:4200])
    meta={
        "demand_type":"job_demand","is_procurement_tender":False,
        "is_confirmed_outsourcing":False,"potential_service_lead":True,
        "service_area":area,"company":company,"information_provider":provider,
        "information_provider_code":card["infoTypeCd"],
        "original_wanted_auth_no":card["wantedAuthNo"],
        "original_group":card["infoTypeGroup"],
        "source_listing_excerpt":card.get("listing_excerpt",""),
        "collected_from":"work24_public_detail",
        "detail_verified":True,"observed_at":datetime.now(timezone.utc).isoformat()
    }
    for name,regex in (
        ("wage",r"임금조건\s*\n?\s*([^\n]{1,90})"),
        ("place",r"근무\s*예정지\s*\n?\s*([^\n]{1,100})"),
        ("working_hours",r"근무\s*시간\s*\n?\s*([^\n]{1,90})"),
        ("employment",r"고용형태\s*\n?\s*([^\n]{1,90})"),
    ):
        m=re.search(regex,publicbody)
        if m:meta[name]=m.group(1).strip()
    return {"source_id":card["source_id"],"title":title[:300],
            "url":normalize_detail_url(url),"body":publicbody,"meta":meta}


def store(item):
    with session() as db:
        row=db.execute("""
        INSERT INTO procureflow.market_records
          (source,kind,source_id,title,url,body,meta)
        VALUES ('work24','job_demand',%s,%s,%s,%s,%s::jsonb)
        ON CONFLICT (source,kind,source_id) DO UPDATE SET
          title=EXCLUDED.title,url=EXCLUDED.url,body=EXCLUDED.body,
          meta=EXCLUDED.meta,last_seen=now()
        RETURNING (xmax=0) AS inserted
        """,(item["source_id"],item["title"],item["url"],item["body"],
              json.dumps(item["meta"],ensure_ascii=False))).fetchone()
    return bool(row["inserted"])


# Each query is applied in the *actual Work24 detailed job-search form*,
# not searched on the main page or fabricated as URL query parameters.
DEFAULT_QUERIES=("미화","청소","경비","시설관리","배송","운전","개발","폐기물","행정지원","방역")
SEARCH_URL=BASE+LIST_PATH
LOGIN_URL=BASE+"/cm/z/b/0210/openLginPage.do"


def login_if_configured(page) -> str:
    """Attempt member ID/password login for every collection run.

    Credentials only come from Railway environment variables, never source
    code, request configs, logs, or persisted recruitment records. Public
    job listings remain collectible if the website refuses ID login.
    """
    account=os.environ.get("WORK24_LOGIN_ID","")
    password=os.environ.get("WORK24_LOGIN_PASSWORD","")
    if not account or not password:
        logging.info("WORK24_LOGIN status=not_configured")
        return "not_configured"
    try:
        response=page.goto(LOGIN_URL,wait_until="domcontentloaded",timeout=30000)
        if not response or response.status>=400:
            logging.warning("WORK24_LOGIN status=login_page_unavailable")
            return "login_page_unavailable"
        page.locator("a.link-id").first.click(timeout=8000)
        popup=page.locator("section.pop_cert_id.on")
        popup.locator("input#id").fill(account,timeout=8000)
        popup.locator("input#pwd").fill(password,timeout=8000)
        popup.locator("#btnIndvIdLogin").click(timeout=10000)
        page.wait_for_timeout(1700)
        # Verify signed-in state on the same browser context, not merely a
        # successful click or a redirected URL.
        page.goto(SEARCH_URL,wait_until="domcontentloaded",timeout=30000)
        page.wait_for_timeout(700)
        logout=page.get_by_text("로그아웃",exact=True)
        authenticated=any(logout.nth(i).is_visible() for i in range(min(logout.count(),5)))
        outcome="authenticated" if authenticated else "not_authenticated"
        logging.info("WORK24_LOGIN status=%s",outcome)
        return outcome
    except Exception as exc:
        # Never log the raw exception: browser errors may contain form data.
        outcome="error_"+type(exc).__name__
        logging.warning("WORK24_LOGIN status=%s",outcome)
        return outcome


def search_keyword(page,term: str) -> dict:
    """Use actual Work24 detailed-search fields, validate the applied query.

    The detailed-search results route uses srcKeyword (not the site-wide
    global search box). Never mark an unverified/default listing as filtered.
    """
    resp=page.goto(SEARCH_URL,wait_until="domcontentloaded",timeout=35000)
    if not resp or resp.status>=400:
        raise RuntimeError("search_page_http_"+str(resp.status if resp else "empty"))
    page.wait_for_timeout(900)
    selectors=(
        'input[name="srcKeyword"]:visible',
        'input#srcKeyword:visible',
        'input[name="srchWrd"]:visible',
        'input#srchWrd:visible',
        'input[placeholder*="여러 단어"]:visible',
    )
    target=next((page.locator(sel).first for sel in selectors
                 if page.locator(sel).count()),None)
    if target is None:
        raise RuntimeError("missing_detailed_search_keyword_control")
    target.fill(term,timeout=7000)
    logging.info("WORK24_SEARCH_TERM term=%s input_filled=1",term)
    # Historical button (#btnSearch) and fnSearch('searchForm') were global
    # search controls, not the actual mForm detailed-search submit action.
    initial_ids=set(x["source_id"] for x in list_links(page))
    # The actual detailed-search input is #srcKeyword, but it is *outside*
    # the submission form mForm. The visible search button near that input
    # copies the query into mForm's hidden #hidSrcKeyword before submission.
    # #btnSearch can resolve to the unrelated global website search.
    control=page.evaluate("""() => {
      const anchor=document.querySelector('#srcKeyword');
      if (!anchor) return {status:'no_srcKeyword'};
      const chain=new Map();let d=0;
      for(let n=anchor;n;n=n.parentElement)chain.set(n,d++);
      const distance=b=>{let y=b,k=0;for(;y;y=y.parentElement,k++)
          if(chain.has(y))return k+chain.get(y);return 10000};
      const candidates=[...document.querySelectorAll('button,a,input[type="button"],input[type="submit"]')]
          .filter(x=>/^\s*검색\s*$/.test((x.innerText||x.value||x.getAttribute('aria-label')||'').trim()))
          .filter(x=>!!(x.offsetWidth||x.offsetHeight||x.getClientRects().length))
          .map(x=>({node:x,dist:distance(x)}))
          .sort((a,b)=>a.dist-b.dist);
      if (!candidates.length)return {status:'no_detailed_search_button'};
      const x=candidates[0].node;
      const label=(x.innerText||x.value||'').trim();
      const diagnostic={status:'clicked',tag:x.tagName,id:x.id||'',
            class_name:(x.className||'').toString().slice(0,90),
            onclick:(x.getAttribute('onclick')||'').slice(0,130),
            distance:candidates[0].dist,button_candidates:candidates.length,
            has_mForm:!!document.querySelector('#mForm')};
      x.click();
      return diagnostic;
    }""")
    logging.info("WORK24_SEARCH_TRIGGER term=%s info=%s",
                 term,json.dumps(control,ensure_ascii=False)[:1000])
    if control.get("status")!="clicked":
        raise RuntimeError("detailed_search_button_missing")
    page.wait_for_timeout(2200)
    query=parse_qs(urlparse(page.url).query)
    url_term=(query.get("srcKeyword") or [""])[0].strip()
    source_field=page.locator('input[name="srcKeyword"]')
    form_term=""
    if source_field.count():
        try:form_term=source_field.first.input_value(timeout=3000).strip()
        except Exception:pass
    if url_term and url_term != term:
        raise RuntimeError("search_keyword_mismatch")
    if form_term and form_term != term:
        raise RuntimeError("search_form_keyword_mismatch")
    post_ids=set(x["source_id"] for x in list_links(page))
    visible_term=""
    try:visible_term=page.locator("#srcKeyword").input_value(timeout=2000).strip()
    except Exception:pass
    verified_by=("url" if url_term==term else "form" if form_term==term
                 else "changed_results" if visible_term==term and post_ids!=initial_ids
                 else "")
    if not verified_by:
        # Only introspect search-control attributes; never inspect credentials,
        # email, contact data, cookies, hidden state or the full HTML body.
        try:
            ui=page.evaluate("""() => ({
              inputs:[...document.querySelectorAll('input')]
                .filter(e=>/keyword|srch|검색어|여러 단어/i.test(
                  [e.name,e.id,e.placeholder].join(' ')))
                .slice(0,20).map(e=>({name:e.name,id:e.id,type:e.type,
                  placeholder:(e.placeholder||'').slice(0,85),
                  shown:!!(e.offsetWidth||e.offsetHeight||e.getClientRects().length),
                  form:e.form?.id||''})),
              controls:[...document.querySelectorAll('button,input[type="button"],input[type="submit"],a')]
                .filter(e=>/검색|search/i.test(
                  [e.id,e.name,e.innerText,e.value].join(' ').slice(0,70)))
                .slice(0,18).map(e=>({tag:e.tagName,id:e.id,name:e.name||'',
                  label:(e.innerText||e.value||'').trim().slice(0,40),
                  onclick:(e.getAttribute('onclick')||'').slice(0,100),
                  form:e.closest('form')?.id||''})),
              forms:[...document.querySelectorAll('form')]
                .map(f=>({id:f.id,name:f.name,action:(f.getAttribute('action')||'').slice(0,100)}))
                .filter(f=>/search|srch|keyword|emp/i.test([f.id,f.name,f.action].join(' ')))
                .slice(0,10),
              paramNames:[...new URLSearchParams(location.search).keys()].filter(k=>/key|srch|search/i.test(k)).slice(0,20)
            })""")
            logging.warning("WORK24_SEARCH_FORM_DIAG term=%s info=%s",
                            term,json.dumps(ui,ensure_ascii=False)[:3700])
        except Exception as diag_exc:
            logging.warning("WORK24_SEARCH_FORM_DIAG error=%s",type(diag_exc).__name__)
        raise RuntimeError("search_keyword_not_verified")
    found=list_links(page)
    if not found:
        page.wait_for_timeout(1900)
        found=list_links(page)
    logging.info("WORK24_SEARCH_VALIDATED term=%s by=%s links=%s",
                 term,verified_by,len(found))
    return {"term":term,"url":page.url,"links":found,"verified_by":verified_by}


def collect(pages=1,limit=10,queries=None):
    """Use actual search filters; store only true matched job detail pages.

    An individual Work24 search result is *not* a confirmed outsourcing
    request. Deduplicate Work24 and third-party syndicated listings using
    the original source-coded recruitment ID.
    """
    pages=max(1,min(int(pages),20))
    limit=max(1,min(int(limit),200))
    terms=tuple(dict.fromkeys(str(t).strip()[:70] for t in (
        queries if queries else DEFAULT_QUERIES
    ) if str(t).strip()))[:12]
    if not terms:terms=DEFAULT_QUERIES
    result={"source":"work24","role":"job_demand","status":"started",
            "search_page":SEARCH_URL,"search_terms":list(terms),
            "examined":0,"saved":0,"new":0,"pages_checked":0,
            "errors":[],"verified_ids":[],"failed_ids":[],"listings":[]}
    candidates={}
    max_attempts=max(20,min(90,limit*4))
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True,args=['--no-sandbox','--disable-dev-shm-usage'])
        ctx=browser.new_context(locale="ko-KR",timezone_id="Asia/Seoul")
        page=ctx.new_page()
        try:
            result["login_status"]=login_if_configured(page)
            for term in terms:
                if len(candidates)>=max_attempts:break
                try:
                    selected=search_keyword(page,term)
                    found=selected["links"]
                    result["pages_checked"]+=1
                    result["listings"].append(
                        {"search_term":term,"url":selected["url"],
                         "found":len(found),"verified_by":selected["verified_by"]}
                    )
                    logging.info("WORK24_SEARCH_RESULT term=%s found=%s",
                                 term,len(found))
                    if not found:
                        result["errors"].append("search_"+term+":no_result_links")
                    for record in found:
                        if len(candidates)>=max_attempts:break
                        record["search_term"]=term
                        candidates.setdefault(record["source_id"],record)
                except Exception as exc:
                    result["errors"].append(
                        "search_"+term+":"+type(exc).__name__+":"+str(exc)[:110]
                    )
                    logging.warning("WORK24_SEARCH_ERROR term=%s type=%s",
                                    term,type(exc).__name__)
            # Avoid claiming successful pagination: the search page uses its
            # own JavaScript result paging; separate queries are real and
            # transparent while deeper paging remains a later adapter.
            if pages>1:result["errors"].append("multi_page_pagination_not_yet_implemented")
            result["discovered"]=len(candidates)
            ordered=sorted(candidates.values(),
                key=lambda x:{"VALIDATION":0,"CJK":1}.get(x["infoTypeCd"],2))
            for card in ordered[:max_attempts]:
                if result["saved"]>=limit:break
                result["examined"]+=1
                try:
                    detail=read_detail(page,card)
                    detail["meta"]["search_term"]=card["search_term"]
                    was_new=store(detail)
                    result["saved"]+=1;result["new"]+=int(was_new)
                    result["verified_ids"].append(card["source_id"])
                    logging.info("WORK24_DETAIL id=%s term=%s area=%s provider=%s new=%s",
                                 card["source_id"],card["search_term"],
                                 detail["meta"]["service_area"],
                                 detail["meta"]["information_provider"],was_new)
                except Exception as exc:
                    result["failed_ids"].append(card["source_id"])
                    # Only print our own explicit validation reasons; never
                    # include raw browser exceptions or secret form contents.
                    reason=(str(exc)[:90] if isinstance(exc,RuntimeError)
                            else type(exc).__name__)
                    result["errors"].append("detail_"+card["source_id"]+":"+reason)
                    logging.warning("WORK24_DETAIL_ERROR id=%s reason=%s",
                                    card["source_id"],reason)
                time.sleep(.5)
            result["status"]=("collected" if result["saved"] else
                              "error" if result["failed_ids"] else
                              "discovery_only" if candidates else "error")
        except Exception as exc:
            result["status"]="error"
            result["errors"].append("collector:"+type(exc).__name__+":"+str(exc)[:140])
        finally:
            ctx.close();browser.close()
    return result


if __name__=="__main__":
    print(json.dumps(collect(),ensure_ascii=False))
