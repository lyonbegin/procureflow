"""Read-only REAL G2B BID NOTICE search UI with 10-digit detail filter.

Unlike the old procurement-request dlOderReqSrchM, this module never uses
a guessed 입찰공고 POST URL or silently falls back to parent-8/all notices.
It navigates the public G2B 입찰공고 검색 screen, sets the visible exact-10
field, observes the resulting same-origin XHR, and accepts only responses
whose request BODY demonstrably carried the selected code and date window.

One 31-day or shorter window, one page, no bulk crawling or bid submission.
"""
from __future__ import annotations

from calendar import monthrange
from datetime import date
from urllib.parse import unquote_plus, urlparse
import json
import re

G2B_HOME="https://www.g2b.go.kr/"
DETAIL_CODE="8111159901"
ID_RE=re.compile(r"^(?:R\d{2}[A-Z]{2}\d{8}|\d{11})$")
ORD_RE=re.compile(r"^\d{1,3}$")
MONTH_RE=re.compile(r"^(20\d{2})-(0[1-9]|1[0-2])$")
CODE_RE=re.compile(r"^\d{10}$")
DATE_RE=re.compile(r"^\d{4}-\d{2}-\d{2}$")

# A search-field label from the REAL bid-notice screen, NOT the old
# procurement-request JSON model, is required.
DETAIL_LABELS=("세부품명번호","세부품명 번호","세부품명")
START_LABELS=("공고게시 시작일","공고게시일 시작","시작일","공고 시작일")
END_LABELS=("공고게시 종료일","공고게시일 종료","종료일","공고 종료일")
G2B_HOST="www.g2b.go.kr"


class SearchBlocked(RuntimeError):
    def __init__(self,reason):
        self.reason=reason
        super().__init__(reason)


def _month_before(month):
    y,m=map(int,month.split("-"))
    return f"{y-1:04d}-12" if m==1 else f"{y:04d}-{m-1:02d}"


def search_window(detail10,start,end,cursor=None,page=1):
    """Resolve 10-year boundary into ONE calendar-month search window."""
    if not isinstance(detail10,str) or not CODE_RE.fullmatch(detail10):
        raise ValueError("OFFICIAL_SEARCH_EXACT_10_DIGITS_REQUIRED")
    if not isinstance(start,str) or not isinstance(end,str) or not DATE_RE.fullmatch(start) or not DATE_RE.fullmatch(end):
        raise ValueError("OFFICIAL_SEARCH_INVALID_DATE_FORMAT")
    first,last=date.fromisoformat(start),date.fromisoformat(end)
    if first>last or (last-first).days>3660:
        raise ValueError("OFFICIAL_SEARCH_INVALID_PERIOD")
    if not isinstance(page,int) or page<1 or page>10:
        raise ValueError("OFFICIAL_SEARCH_PAGE_OUT_OF_RANGE")
    month=cursor or last.strftime("%Y-%m")
    if not MONTH_RE.fullmatch(month):
        raise ValueError("OFFICIAL_SEARCH_INVALID_CURSOR")
    y,m=map(int,month.split("-"))
    lower=max(first,date(y,m,1))
    upper=min(last,date(y,m,monthrange(y,m)[1]))
    if lower>upper:
        raise ValueError("OFFICIAL_SEARCH_CURSOR_OUT_OF_PERIOD")
    previous=_month_before(month)
    has_previous=date.fromisoformat(previous+"-"+str(monthrange(*map(int,previous.split("-")))[1]))>=first
    return {"detail10":detail10,"start":lower.isoformat(),"end":upper.isoformat(),
            "full_period_start":first.isoformat(),"full_period_end":last.isoformat(),
            "cursor":month,"page":page,
            "previous_month":previous if has_previous else None}


def _flatten_post(post):
    if not isinstance(post,str):
        return ""
    # UTF-8 WebSquare bodies can be JSON or application/x-www-form-urlencoded.
    return unquote_plus(post)


def request_has_filter(post, detail10, start, end):
    """Prove same-origin actual bid SEARCH XHR sent 10-digit filter + dates.

    A text occurrence alone is not enough: it must be attached to a named
    classification field. Unknown field names must not be treated as evidence.
    """
    raw=_flatten_post(post)
    if not raw or detail10 not in raw:
        return False
    try:
        body=json.loads(raw)
    except (ValueError,TypeError):
        # Some WebSquare submissions use URL-encoded nested body; inspect
        # only explicit name=value pairs, never arbitrary substring match.
        from urllib.parse import parse_qs
        pairs=parse_qs(raw,keep_blank_values=True)
        fields=[(k,v) for k,values in pairs.items() for v in values]
    else:
        fields=[]
        def walk(node):
            if isinstance(node,dict):
                for k,v in node.items():
                    if isinstance(v,(dict,list)):walk(v)
                    else:fields.append((str(k),str(v)))
            elif isinstance(node,list):
                for child in node:walk(child)
        walk(body)
    def is_code_key(name):
        k=re.sub(r"[^a-z0-9]","",name.lower())
        return (k in {"dtlsprnmno","dtilprdctclsfcno","dtilprdlstclsfcno",
                      "dtilprdlstclsfno","dtilprdctclsfno",
                      "detailprdctclsfcno","prdlstdtlno"} or
                ("detail" in k or "dtls" in k or "dtil" in k) and
                 ("prnm" in k or "prdct" in k or "prdlst" in k or "clsfc" in k))
    exact=any(is_code_key(key) and value.strip()==detail10 for key,value in fields)
    if not exact:
        return False
    dates=[start.replace("-",""),end.replace("-","")]
    # A date field may contain YYYYMMDD, YYYY-MM-DD or YYYY/MM/DD.
    compact=re.sub(r"[^0-9]","",raw)
    return all(d in compact for d in dates)


def _frames(page):
    # Site may use WebSquare iframes or a root document.
    return [f for f in page.frames if not f.is_detached()]


def _click_label(page,labels,action="click"):
    for frame in _frames(page):
        for label in labels:
            for locator in (frame.get_by_role("link",name=label,exact=True),
                            frame.get_by_role("button",name=label,exact=True),
                            frame.get_by_text(label,exact=True)):
                try:
                    for index in range(min(locator.count(),10)):
                        loc=locator.nth(index)
                        if not loc.is_visible():continue
                        if action=="hover":loc.hover(timeout=1200)
                        else:loc.click(timeout=1400)
                        page.wait_for_timeout(750)
                        return True
                except Exception:
                    continue
    return False


def _field_from_label(page,labels):
    """Discover input by its ACTUAL adjacent label/ID rather than guessing."""
    js=r"""(labels)=>{
      const norm=s=>(s||'').replace(/\s+/g,'').replace(/[:：]/g,'').trim();
      const wanted=labels.map(norm);
      const inputs=[...document.querySelectorAll('input:not([type=hidden]),textarea')];
      for(const input of inputs){
        if(!input.id || input.disabled || input.readOnly)continue;
        const name=[input.getAttribute('aria-label'),input.getAttribute('title'),
          input.getAttribute('placeholder'),input.getAttribute('name')].filter(Boolean);
        if(name.some(t=>wanted.some(w=>norm(t).includes(w))))return input.id;
      }
      const nodes=[...document.querySelectorAll('label,th,td,span,strong,div')];
      for(const node of nodes){
        if(!wanted.some(w=>norm(node.textContent)===w))continue;
        const candidates=[node,node.nextElementSibling,node.parentElement,
          node.parentElement?.nextElementSibling,node.parentElement?.parentElement,
          node.parentElement?.parentElement?.nextElementSibling];
        for(const parent of candidates){
          if(!parent)continue;
          const matches=[...parent.querySelectorAll('input:not([type=hidden]),textarea')].filter(e=>e.id&&!e.disabled&&!e.readOnly);
          if(matches.length===1)return matches[0].id;
        }
      }
      return null;
    }"""
    for frame in _frames(page):
        try:
            identity=frame.evaluate(js,list(labels))
            if identity:
                return frame,frame.locator("[id="+json.dumps(identity)+"]")
        except Exception:
            continue
    return None,None


def _date_field_group(page):
    """Identify two date inputs belonging to the G2B notice-posted-date row."""
    js=r"""()=>{
       const norm=s=>(s||'').replace(/\s+/g,'').trim();
       const keys=['공고게시일','공고일자','공고게시일자','공고게시기간','공고/개찰일자','공고·개찰일자'];
       const els=[...document.querySelectorAll('th,td,label,span')];
       for(const el of els){
          if(!keys.some(k=>norm(el.textContent)===k))continue;
          const roots=[el.parentElement,el.parentElement?.parentElement,
                       el.parentElement?.nextElementSibling];
          for(const root of roots){
             if(!root)continue;
             const inputs=[...root.querySelectorAll('input:not([type=hidden])')].filter(e=>e.id&&!e.disabled&&!e.readOnly);
             if(inputs.length>=2 && inputs.length<=4)return inputs.slice(0,2).map(e=>e.id);
          }
       }
       return [];
    }"""
    for frame in _frames(page):
        try:
            pair=frame.evaluate(js)
            if len(pair)==2 and pair[0]!=pair[1]:
                return frame,[frame.locator("[id="+json.dumps(x)+"]") for x in pair]
        except Exception:
            continue
    return None,None


def _fill_date(locator,day):
    current=locator.get_attribute("value") or ""
    value=day.replace("-","") if re.fullmatch(r"\d{8}",current) else day
    locator.fill(value,timeout=2200)
    locator.press("Tab",timeout=1500)
    return value


def _fill_search_fields(page,w):
    frame,code=_field_from_label(page,DETAIL_LABELS)
    if code is None:
        raise SearchBlocked("BID_NOTICE_EXACT10_FIELD_NOT_FOUND")
    code.fill(w["detail10"],timeout=2200)
    code.press("Tab",timeout=1400)
    if w["detail10"] not in (code.input_value() or ""):
        raise SearchBlocked("BID_NOTICE_EXACT10_INPUT_REJECTED")
    date_frame,dates=_date_field_group(page)
    if dates is None:
        # It is unsafe to issue a 10-year unbounded request. Do not search.
        raise SearchBlocked("BID_NOTICE_POSTED_DATE_FIELDS_NOT_FOUND")
    _fill_date(dates[0],w["start"])
    _fill_date(dates[1],w["end"])
    return True


def _wait_for_site_rendered(page, timeout_ms=16000):
    """Allow slow official WebSquare boot before menu discovery.

    Rendering is NOT proof of a valid search: all exact-10 request/response
    validations remain mandatory. No response payload or secrets are logged.
    """
    elapsed=0
    while elapsed<=timeout_ms:
        try:
            for frame in _frames(page):
                if urlparse(frame.url).hostname not in (G2B_HOST,"g2b.go.kr"):
                    continue
                ready=frame.evaluate("""() => ({
                    state: document.readyState,
                    text: (document.body?.innerText || '').trim().length,
                    controls: document.querySelectorAll('input,button,a,[role=button],[role=link]').length
                })""")
                if ready.get("state") in ("interactive","complete") and (
                    ready.get("text",0)>0 or ready.get("controls",0)>0
                ):
                    return True
        except Exception:
            # Frame navigation during WebSquare boot is transient.
            pass
        if elapsed>=timeout_ms:
            break
        page.wait_for_timeout(min(500,timeout_ms-elapsed))
        elapsed+=min(500,timeout_ms-elapsed)
    return False


def _wait_for_exact10_field(page, timeout_ms=12000):
    elapsed=0
    while elapsed<=timeout_ms:
        if _field_from_label(page,DETAIL_LABELS)[1] is not None:
            return True
        if elapsed>=timeout_ms:
            break
        page.wait_for_timeout(600)
        elapsed+=600
    return False


def _navigate(page):
    # No hardcoded fake bid-list endpoint. A real, visible input is mandatory.
    if _field_from_label(page,DETAIL_LABELS)[1] is not None:
        return
    for names in (("입찰",),("입찰공고",),("입찰공고목록","입찰공고 목록"),
                  ("입찰공고 검색","입찰공고조회","공고현황")):
        _click_label(page,names,action="hover")
        _click_label(page,names,action="click")
        page.wait_for_timeout(800)
        if _field_from_label(page,DETAIL_LABELS)[1] is not None:
            return
    # Publicly observed G2B bid-notice link family; candidate only.
    # All results must still pass the exact-10 request verification.
    if _field_from_label(page,DETAIL_LABELS)[1] is None:
        try:
            page.goto("https://www.g2b.go.kr/link/PNPE027_01/",
                      wait_until="domcontentloaded",timeout=30000)
            _wait_for_site_rendered(page,16000)
            _click_label(page,("입찰공고목록","입찰공고 목록"))
            if _wait_for_exact10_field(page,3000):
                return
            _click_label(page,("상세조건","상세검색","상세조건 펼침"))
            if _wait_for_exact10_field(page,12000):
                return
        except Exception:
            pass
    _click_label(page,("상세조건","상세검색","검색조건","상세조건 검색"),action="click")
    if not _wait_for_exact10_field(page,4500):
        try:
            # Official homepage can return a valid page title but empty
            # WebSquare body in the Railway headless environment.
            empty=page.evaluate("""() => {
              const body=(document.body?.innerText||'').trim();
              const controls=document.querySelectorAll('input,button,a').length;
              return !body && controls===0;
            }""")
            if empty:
                raise SearchBlocked("G2B_OFFICIAL_SITE_RENDERED_EMPTY")
        except SearchBlocked:
            raise
        except Exception:
            pass
        raise SearchBlocked("BID_NOTICE_SEARCH_SCREEN_OR_10DIGIT_FILTER_NOT_FOUND")


def _response_records(document):
    """Extract only actual bid notice rows; no inferred matches from title."""
    if not isinstance(document,dict):
        return None,None
    if str(document.get("ErrorCode",0)) not in ("0","00"):
        raise SearchBlocked("BID_NOTICE_G2B_SEARCH_RESPONSE_ERROR")
    found=[]
    known_list=False
    def visit(node,depth=0):
        nonlocal known_list
        if depth>6:return
        if isinstance(node,list):
            if not node:known_list=True
            for v in node[:200]:visit(v,depth+1)
        elif isinstance(node,dict):
            if "bidPbancNo" in node or "bidNtceNo" in node:
                found.append(node);known_list=True;return
            for k,v in node.items():
                if isinstance(v,list) and re.search(r"bid|pbanc|ntce|list|result",str(k),re.I):
                    known_list=True
                if isinstance(v,(dict,list)):visit(v,depth+1)
    visit(document)
    if not known_list:
        return None,None
    total=None
    for root in [document,document.get("result",{}),document.get("body",{})]:
        if isinstance(root,dict):
            for k in ("totalCount","totCnt","total","totalCnt"):
                if k in root:
                    try:total=int(root[k])
                    except (TypeError,ValueError):pass
    out=[]
    seen=set()
    for rec in found:
        no=str(rec.get("bidPbancNo") or rec.get("bidNtceNo") or "")
        ord_=str(rec.get("bidPbancOrd") or rec.get("bidNtceOrd") or "000").zfill(3)
        if not ID_RE.fullmatch(no) or not ORD_RE.fullmatch(ord_):continue
        if (no,ord_) in seen:continue
        seen.add((no,ord_))
        codes={str(v).strip() for k,v in rec.items() if re.search(
            r"(dtlsPrnmNo|dtilPrdctClsfcNo|dtilPrdlstClsfcNo|dtilPrdctClsfNo)",str(k),re.I) and v}
        out.append({"bid_no":no,"bid_ord":ord_,
                    "title":str(rec.get("bidPbancNm") or rec.get("bidNtceNm") or "")[:240],
                    "agency":str(rec.get("grpNm") or rec.get("ntceInsttNm") or "")[:150],
                    "direct_category_codes":list(sorted(codes))[:5],
                    "raw":rec,
                    "posted_on":str(rec.get("bidPbancPstgDt") or
                             rec.get("bidNtceDt") or rec.get("pbancPstgDt") or "")[:10]})
    return out,total


def _safe_search_screen_diagnostic(tab):
    """Read PUBLIC DOM structure only, never credentials/cookies/input values."""
    details=[]
    for frame in list(tab.frames)[:8]:
        if frame.is_detached():continue
        try:
            host=urlparse(frame.url).hostname
            if host not in (G2B_HOST,"g2b.go.kr"):continue
            nodes=frame.evaluate(r"""()=>{
              const xs=[...document.querySelectorAll('a,button,input,label,[role=link],[role=button]')];
              return {title:(document.title||'').slice(0,90),
                bodyText:(document.body?.innerText||'').slice(-550),
                fieldNames:[...document.querySelectorAll('label,th,span')].map(e=>(e.innerText||'').trim()).filter(s=>/세부품명|상세조건|공고.개찰일자/.test(s)).slice(0,18),
                controls:xs.filter(e=>e.tagName==='INPUT'||e.tagName==='LABEL'||e.tagName==='BUTTON').slice(0,55).map(e=>({
                    tag:e.tagName,
                    text:(e.tagName==='INPUT'?'':(e.innerText||e.title||'')).trim().slice(0,55),
                    type:e.getAttribute('type')||'',
                    aria:e.getAttribute('aria-label')||'',
                    placeholder:e.getAttribute('placeholder')||''
                  }))
              }
            }""")
            details.append({"path":urlparse(frame.url).path[:130],
                            "title":nodes.get("title"),
                            "body":nodes.get("bodyText"),
                            "controls":nodes.get("controls",[])})
        except Exception as exc:
            # Only public page path and single-line exception category/message;
            # never request bodies, private values, cookies or auth headers.
            try:
                target=urlparse(frame.url)
                details.append({"host":target.hostname,"path":target.path[:120],
                   "error_type":type(exc).__name__,
                   "detail":str(exc).splitlines()[0][:160]})
            except Exception:details.append({"error_type":type(exc).__name__})
    return details

def run_search(detail10,start,end,cursor=None,page=1,*,factory=None):
    """One PUBLIC real website search. No external result data is fabricated."""
    w=search_window(detail10,start,end,cursor,page)
    output={"status":"blocked","source":"g2b_public_bid_notice_search_ui",
      "filter_type":"actual_bid_notice_search_screen_exact10",
      "detail10":detail10,"request_window":{"start":w["start"],"end":w["end"]},
      "page":page,"cursor":w["cursor"],"next_month":w["previous_month"],
      "case_specific_outcome_collection":False,"ten_year_complete":False,
      "bid_submitted":False}
    if factory is None:
        from playwright.sync_api import sync_playwright
        factory=sync_playwright
    try:
        with factory() as p:
            browser=p.chromium.launch(headless=True,args=[
                "--no-sandbox","--disable-dev-shm-usage"])
            context=browser.new_context(locale="ko-KR",timezone_id="Asia/Seoul",
                viewport={"width":1440,"height":900},
                user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/154.0.0.0 Safari/537.36"))
            context.set_default_timeout(2800)
            requests=[]
            responses=[]
            def on_request(req):
                parsed=urlparse(req.url)
                if (parsed.hostname==G2B_HOST and req.method=="POST"
                        and parsed.path.endswith(".do")):
                    if request_has_filter(req.post_data,detail10,w["start"],w["end"]):
                        requests.append({"url":req.url.split("?")[0],"request":req})
            def on_response(r):
                if any(x["request"]==r.request for x in requests):
                    responses.append(r)
            context.on("request",on_request)
            context.on("response",on_response)
            tab=context.new_page()
            tab.goto(G2B_HOME,wait_until="domcontentloaded",timeout=30000)
            if not _wait_for_site_rendered(tab):
                import logging
                logging.warning("FRESH_G2B_PUBLIC_SEARCH_SCREEN_LIVE %s",
                  json.dumps(_safe_search_screen_diagnostic(tab),
                    ensure_ascii=False,default=str)[:5500])
                raise SearchBlocked("G2B_OFFICIAL_SITE_RENDERED_EMPTY_AFTER_WAIT")
            try:
                _navigate(tab)
            except SearchBlocked:
                import logging
                logging.warning("FRESH_G2B_PUBLIC_SEARCH_SCREEN_LIVE %s",
                  json.dumps(_safe_search_screen_diagnostic(tab),
                    ensure_ascii=False,default=str)[:5500])
                raise
            _fill_search_fields(tab,w)
            # Require an actual site search button and form submission.
            if not _click_label(tab,("검색",),"click"):
                raise SearchBlocked("BID_NOTICE_SEARCH_BUTTON_NOT_FOUND")
            tab.wait_for_timeout(2500)
            if not requests:
                raise SearchBlocked("BID_NOTICE_10DIGIT_NOT_IN_ACTUAL_POST_REQUEST")
            if page>1:
                # Every page request must repeat the same 10-digit filter.
                pg=str(page)
                if not _click_label(tab,(pg,),"click"):
                    raise SearchBlocked("BID_NOTICE_PAGE_BUTTON_NOT_FOUND")
                tab.wait_for_timeout(1700)
            # Only the selected window + page may be accepted.
            matched_responses=[r for r in responses if request_has_filter(
                r.request.post_data,detail10,w["start"],w["end"])]
            if not matched_responses:
                raise SearchBlocked("BID_NOTICE_SEARCH_RESPONSE_NOT_CAPTURED")
            last=matched_responses[-1]
            if last.status!=200:
                raise SearchBlocked("BID_NOTICE_SEARCH_HTTP_"+str(last.status))
            try:
                data=last.json()
            except Exception:
                raise SearchBlocked("BID_NOTICE_SEARCH_RESPONSE_NOT_JSON") from None
            records,total=_response_records(data)
            if records is None:
                raise SearchBlocked("BID_NOTICE_RESPONSE_SCHEMA_UNCONFIRMED")
            confirmed=[]
            pending=[]
            for item in records:
                if any(c!=detail10 for c in item["direct_category_codes"]):
                    raise SearchBlocked("BID_NOTICE_RESPONSE_HAS_OTHER_EXPLICIT_DETAIL10")
                if detail10 in item["direct_category_codes"]:
                    confirmed.append(item)
                else:
                    pending.append(item)
            output.update(status="partial_filtered_result",
                search_request_verified=True,
                live_search_endpoint=urlparse(last.url).path,
                matched_explicit_detail10=confirmed,
                pending_original_detail10_verification=pending,
                response_sha=__import__("hashlib").sha256(
                    json.dumps(data,ensure_ascii=False,sort_keys=True,default=str).encode()).hexdigest(),
                returned_bid_ids=len(records),official_total=total,
                next_page=page+1 if len(records)>0 and len(records)>=10 else None,
                search_source_status="live_post_with_exact_filter_and_window")
            context.close()
            browser.close()
    except SearchBlocked as exc:
        output["reason"]=exc.reason
        output["search_request_verified"]=False
    except Exception as exc:
        output["reason"]="G2B_UI_RUNTIME_"+type(exc).__name__
        output["search_request_verified"]=False
    return output
