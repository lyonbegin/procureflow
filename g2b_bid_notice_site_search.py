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


def _verified_date_replay(original, detail10, start, end):
    """Patch only dates in an observed official bid-list POST.

    Never manufacture a search endpoint, replace the category code, or replay
    if the originating WebSquare request fails identity validation.
    """
    url=urlparse(original.url)
    if (url.scheme!="https" or url.hostname!=G2B_HOST or
        url.path!="/pn/pnp/pnpe/BidPbac/selectBidPbacScrollTypeList.do" or
        original.method!="POST"):
        raise SearchBlocked("OFFICIAL_POST_ENDPOINT_NOT_OBSERVED")
    try:
        envelope=json.loads(original.post_data)
        original_fields=envelope["dlBidPbancLstM"]
    except (ValueError,TypeError,KeyError):
        raise SearchBlocked("OFFICIAL_POST_JSON_SCHEMA_NOT_OBSERVED") from None
    if not isinstance(original_fields,dict):
        raise SearchBlocked("OFFICIAL_POST_FIELDS_INVALID")
    if str(original_fields.get("dtlsPrnmNo") or "")!=detail10:
        raise SearchBlocked("OFFICIAL_POST_EXACT10_NOT_VERIFIED")
    if not all(re.fullmatch(r"20[0-9]{6}",str(original_fields.get(key) or ""))
               for key in ("fromBidDt","toBidDt")):
        raise SearchBlocked("OFFICIAL_POST_DATE_KEYS_NOT_VERIFIED")
    patched=json.loads(json.dumps(envelope))
    fields=patched["dlBidPbancLstM"]
    fields["fromBidDt"]=start.replace("-","")
    fields["toBidDt"]=end.replace("-","")
    payload=json.dumps(patched,ensure_ascii=False,separators=(",",":"))
    if not request_has_filter(payload,detail10,start,end):
        raise SearchBlocked("OFFICIAL_POST_DATE_PATCH_NOT_VERIFIED")
    return payload


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
    """Prefer the actual observed G2B detail-number input in the visible tab."""
    if "세부품명번호" in labels:
        for frame in _frames(page):
            try:
                shown=frame.locator('input[id*="dtlsPrnmNo"]:visible:not([disabled]):not([readonly])')
                if shown.count():
                    return frame,shown.first
            except Exception:
                pass
    js=r"""(labels)=>{
      const norm=s=>(s||'').replace(/\s+/g,'').replace(/[:：]/g,'').trim();
      const wanted=labels.map(norm);
      const inputs=[...document.querySelectorAll('input:not([type=hidden]):not([type=button]):not([type=submit]):not([type=checkbox]):not([type=radio]),textarea')];
      for(const input of inputs){
        if(!input.id || input.disabled || input.readOnly)continue;
        const name=[input.getAttribute('aria-label'),input.getAttribute('title'),
          input.getAttribute('placeholder'),input.getAttribute('name')].filter(Boolean);
        if(name.some(t=>wanted.some(w=>norm(t).includes(w))))return input.id;
      }
      const nodes=[...document.querySelectorAll('label,th,td,span,strong,div')];
      for(const node of nodes){
        if(!wanted.some(w=>norm(node.textContent)===w))continue;
        if(node.tagName==='LABEL' && node.htmlFor){
          const linked=document.getElementById(node.htmlFor);
          if(linked && linked.id && !linked.disabled && !linked.readOnly &&
              !['button','hidden','submit','checkbox','radio'].includes(linked.type))
            return linked.id;
        }
        const candidates=[node,node.nextElementSibling,node.parentElement,
          node.parentElement?.nextElementSibling,node.parentElement?.parentElement,
          node.parentElement?.parentElement?.nextElementSibling,node.closest('tr')];
        for(const parent of candidates){
          if(!parent)continue;
          const matches=[...parent.querySelectorAll('input:not([type=hidden]):not([type=button]):not([type=submit]):not([type=checkbox]):not([type=radio]),textarea')].filter(e=>e.id&&!e.disabled&&!e.readOnly);
          if(matches.length===1)return matches[0].id;
        }
      }
      return null;
    }"""
    for frame in _frames(page):
        try:
            identity=frame.evaluate(js,list(labels))
            if identity:
                locator=frame.locator("[id="+json.dumps(identity)+"]")
                if locator.count() and locator.first.is_visible() and locator.first.is_enabled():
                    return frame,locator.first
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
             const inputs=[...root.querySelectorAll('input:not([type=hidden]):not([type=button]):not([type=submit]):not([type=checkbox]):not([type=radio])')].filter(e=>e.id&&!e.disabled&&!e.readOnly&&e.getClientRects().length>0);
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
    # Official G2B WebSquare validates yyyyMMdd, even when input starts blank.
    value=day.replace("-","")
    if not re.fullmatch(r"\d{8}",value):
        raise SearchBlocked("OFFICIAL_DATE_MUST_BE_YYYYMMDD")
    locator.fill(value,timeout=2200)
    locator.press("Tab",timeout=1500)
    return value


def _fill_search_fields(page,w):
    frame,code=_field_from_label(page,DETAIL_LABELS)
    if code is None:
        raise SearchBlocked("BID_NOTICE_EXACT10_FIELD_NOT_FOUND")
    try:
        code.fill(w["detail10"],timeout=2500)
        code.press("Tab",timeout=1500)
        if w["detail10"] not in (code.input_value() or ""):
            raise SearchBlocked("BID_NOTICE_EXACT10_INPUT_REJECTED")
    except SearchBlocked:
        raise
    except Exception as exc:
        raise SearchBlocked("G2B_DETAIL10_INPUT_NOT_EDITABLE_"+type(exc).__name__) from None
    date_frame,dates=_date_field_group(page)
    if dates is None:
        # It is unsafe to issue a 10-year unbounded request. Do not search.
        raise SearchBlocked("BID_NOTICE_POSTED_DATE_FIELDS_NOT_FOUND")
    try:
        _fill_date(dates[0],w["start"])
        _fill_date(dates[1],w["end"])
    except Exception as exc:
        raise SearchBlocked("G2B_NOTICE_DATES_NOT_EDITABLE_"+type(exc).__name__) from None
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


def _official_menu_click(page, labels):
    """Use the observed G2B GNB DOM ids; never guess a request endpoint."""
    script=r"""(target)=>{
      const norm=s=>(s||'').replace(/\s+/g,' ').trim();
      const els=[...document.querySelectorAll('a,button,[role="button"]')];
      const hits=els.filter(e=>norm(e.textContent)===target);
      const sorted=hits.map(e=>{
        const id=e.id||'';
        const visible=e.getClientRects().length>0;
        const score=(id.includes('gnbMenu')?50:0)+(id.includes('genMenu')?25:0)
          +(visible?15:0)+(id.includes('btn_menuLvl')?10:0);
        return {e,score};
      }).sort((a,b)=>b.score-a.score);
      if(!sorted.length)return false;
      sorted[0].e.click();
      return true;
    }"""
    for retry in range(16):
        for frame in _frames(page):
            for label in labels:
                try:
                    if frame.evaluate(script,label):
                        page.wait_for_timeout(950)
                        return True
                except Exception:
                    continue
        if retry==7:
            _click_label(page,("사이트맵","전체메뉴"))
        page.wait_for_timeout(350)
    return False


def _open_detail_search(page):
    """Invoke only the visible observed G2B WebSquare advanced-search control."""
    script=r"""()=>{
       const matches=[...document.querySelectorAll('input[type=button]')]
         .filter(e=>e.id.endsWith('btnSearchToggle') &&
                    e.getClientRects().length>0 && !e.disabled);
       if(!matches.length)return false;
       matches[0].click();
       return true;
    }"""
    for frame in _frames(page):
        try:
            if frame.evaluate(script):
                page.wait_for_timeout(1000)
                return True
        except Exception:
            continue
    return False


def _dismiss_public_notices(page):
    """Close only observed G2B public announcements using WebSquare API."""
    import logging
    closed=0
    for frame in _frames(page):
        try:
            outcome=frame.evaluate(r"""() => {
                const windows=[...document.querySelectorAll('.w2popup_window')]
                  .filter(e=>e.getClientRects().length>0 &&
                    (e.innerText||'').includes('나라장터 공지사항'));
                const ids=[...new Set(windows.map(e=>((e.id||'').match(/poupR[^_]+/)||[])[0]).filter(Boolean))];
                const api=window.WebSquare?.util;
                const scope=window.$p;
                let invoked=0;
                for(const id of ids){
                    try{
                        if(api && typeof api.closePopup==='function'){api.closePopup(id);invoked++;}
                        else if(scope && typeof scope.closePopup==='function'){scope.closePopup(id);invoked++;}
                    }catch(e){}
                }
                return {found:ids.length,invoked};
            }""")
            closed+=int(outcome.get("invoked") or 0)
            logging.warning("FRESH_G2B_OFFICIAL_POPUP_CLOSE %s",
                            json.dumps(outcome,ensure_ascii=False))
        except Exception as exc:
            logging.warning("FRESH_G2B_OFFICIAL_POPUP_CLOSE_ERROR %s",type(exc).__name__)
    page.wait_for_timeout(650)
    for frame in _frames(page):
        try:
            result=frame.evaluate(r"""() => {
              const pending=[...document.querySelectorAll('.w2popup_window')]
                .filter(e=>e.getClientRects().length>0 &&
                  (e.innerText||'').includes('나라장터 공지사항'));
              const layer=document.getElementById('_modal');
              if(pending.length || !layer || !layer.getClientRects().length)
                return {pending:pending.length,handled:false};
              const api=window.$p;
              if(api && typeof api.hideModal==='function') {
                api.hideModal();
                return {pending:0,handled:true};
              }
              return {pending:0,handled:false};
            }""")
            logging.warning("FRESH_G2B_MODAL_RELEASE %s",
                            json.dumps(result,ensure_ascii=False))
        except Exception:
            pass
    for frame in _frames(page):
        try:
            status=frame.evaluate(r"""() => {
                const windows=[...document.querySelectorAll('.w2popup_window')]
                    .filter(e=>e.getClientRects().length>0 &&
                        getComputedStyle(e).visibility!=='hidden' &&
                        getComputedStyle(e).display!=='none');
                const active=windows.filter(e=>(e.innerText||'').trim().length>0);
                const modal=document.getElementById('_modal');
                const safe=active.length===0 && modal &&
                    modal.classList.contains('w2modal_popup');
                if(safe)modal.style.pointerEvents='none';
                return {windows:active.length,release:!!safe,
                  titles:active.slice(0,5).map(e=>(e.innerText||'').trim().slice(0,90))};
            }""")
            logging.warning("FRESH_G2B_RESIDUAL_MODAL %s",
                json.dumps(status,ensure_ascii=False))
        except Exception:
            pass
    for frame in _frames(page):
        try:
            close=frame.locator('[id$="btnSitemapClose"]:visible')
            if close.count():close.first.click(force=True,timeout=1800)
        except Exception:
            pass
    return closed

def _click_notice_search(page):
    """Click the public main notice search button; never bid/submit controls."""
    import logging
    for frame in _frames(page):
        try:
            button=frame.locator('input[id$="btnS0004"]:visible')
            if button.count():
                try:
                    button.first.click(timeout=2500)
                except Exception as exc:
                    diagnostic=frame.evaluate("""() => {
                      const b=[...document.querySelectorAll('input[id$="btnS0004"]')]
                        .find(e=>e.getClientRects().length>0);
                      if(!b)return {button_missing:true};
                      const r=b.getBoundingClientRect();
                      const top=document.elementFromPoint(r.left+r.width/2,r.top+r.height/2);
                      return {button:b.id,topId:(top?.id||'').slice(0,110),
                        topTag:top?.tagName||'',topClass:(""+(top?.className||'')).slice(0,110),
                        topText:(top?.innerText||top?.title||'').slice(0,110),
                        overlay:top!==b};
                    }""")
                    logging.warning("FRESH_G2B_MAIN_SEARCH_POINTER %s %s",
                      type(exc).__name__,json.dumps(diagnostic,ensure_ascii=False))
                    modal=frame.evaluate("""() => ({
                      popups:[...document.querySelectorAll('[class*=popup],[id*=poup],[role=dialog]')]
                        .filter(e=>e.getClientRects().length>0).slice(0,14)
                        .map(e=>({id:(e.id||'').slice(0,90),cls:(""+(e.className||'')).slice(0,100),
                          text:(e.innerText||'').trim().slice(0,180)})),
                      closers:[...document.querySelectorAll('input[type=button],button,a')]
                        .filter(e=>e.getClientRects().length>0 &&
                          /닫기|확인|close/i.test((e.value||'')+' '+(e.title||'')+' '+(e.innerText||'')))
                        .slice(0,20).map(e=>({id:(e.id||'').slice(0,100),
                          label:((e.value||e.innerText||e.title||'')+'').slice(0,65)}))
                    })""")
                    logging.warning("FRESH_G2B_MODAL_CHOICES %s",
                      json.dumps(modal,ensure_ascii=False)[:3500])
                    button.first.click(force=True,timeout=2500)
                return True
        except Exception as exc:
            logging.warning("FRESH_G2B_MAIN_SEARCH_CLICK_FAILURE %s",type(exc).__name__)
            continue
    return False

def _navigate(page):
    """Reach the real public notice list, then open advanced 10-digit criteria."""
    if _wait_for_exact10_field(page,1500):
        return
    for names in (("입찰",),("입찰공고",),("입찰공고목록", "입찰공고 목록")):
        if not _official_menu_click(page,names):
            raise SearchBlocked("G2B_NOTICE_MENU_MISSING_"+str(len(names)))
    if _wait_for_exact10_field(page,2500):
        return
    # The original G2B DOM shows the detail-number input inside tab2.
    # Activate its public goods tab before opening advanced search.
    _official_menu_click(page,("물품",))
    if _wait_for_exact10_field(page,2500):
        return
    if not _open_detail_search(page):
        raise SearchBlocked("G2B_NOTICE_DETAIL_TOGGLE_NOT_FOUND")
    if not _wait_for_exact10_field(page,12000):
        raise SearchBlocked("G2B_NOTICE_EXACT10_FIELD_NOT_RENDERED")



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
            if any(k in node for k in ("bidPbancNo","bidNtceNo","untyBidPbancNo","bidPbancUntyNo")):
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
        no=str(rec.get("bidPbancNo") or rec.get("bidNtceNo") or
               rec.get("untyBidPbancNo") or rec.get("bidPbancUntyNo") or "")
        ord_=str(rec.get("bidPbancOrd") or rec.get("bidNtceOrd") or
                 rec.get("untyBidPbancOrd") or rec.get("bidPbancUntyOrd") or "000").zfill(3)
        if not ID_RE.fullmatch(no) or not ORD_RE.fullmatch(ord_):continue
        if (no,ord_) in seen:continue
        seen.add((no,ord_))
        codes={str(v).strip() for k,v in rec.items() if re.search(
            r"(dtlsPrnmNo|dtilPrdctClsfcNo|dtilPrdlstClsfcNo|dtilPrdctClsfNo)",str(k),re.I) and v}
        out.append({"bid_no":no,"bid_ord":ord_,
                    "title":str(rec.get("bidPbancNm") or rec.get("bidNtceNm") or "")[:240],
                    "agency":str(rec.get("grpNm") or rec.get("ntceInsttNm") or
                                  rec.get("oderInstUntyGrpNm") or rec.get("dmstNm") or "")[:150],
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
                fieldNames:[...document.querySelectorAll('label,th,span')].map(e=>(e.innerText||'').trim()).filter(s=>/세부품명|상세조건|공고.개찰일자/.test(s)).slice(0,8),
                inputOptions:[...document.querySelectorAll('input[id*="dtlsPrnmNo"]')].slice(0,18)
                  .map(e=>({id:e.id,visible:!!e.getClientRects().length,disabled:e.disabled,readonly:e.readOnly})),
                detailControls:[...document.querySelectorAll('a,button,input[type=button],[role=button]')]
                  .filter(e=>/상세|검색조건|펼침/.test((e.innerText||'')+' '+(e.title||'')+' '+(e.value||'')))
                  .slice(0,14).map(e=>({id:e.id||'',tag:e.tagName,text:((e.innerText||e.title||e.value||'')+'').slice(0,45),visible:!!e.getClientRects().length})),
                targetRows:[...document.querySelectorAll('label,th,span,td')].filter(e=>(e.textContent||'').replace(/\s+/g,'').trim()==='세부품명번호').slice(0,4).map(e=>{
                   const root=e.closest('tr')||e.parentElement?.parentElement;
                   const xs=root?[...root.querySelectorAll('input')].slice(0,7):[];
                   return {tag:e.tagName,htmlFor:e.htmlFor||'',parent:e.parentElement?.tagName||'',inputCount:xs.length,
                     inputs:xs.map(x=>({id:x.id||'',type:x.type||'',name:x.name||'',visible:!!x.getClientRects().length,disabled:x.disabled}))};
                }),
                controls:xs.filter(e=>e.tagName==='INPUT'||e.tagName==='LABEL'||e.tagName==='BUTTON').slice(0,8).map(e=>({
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
                            "fieldNames":nodes.get("fieldNames",[]),
                            "inputOptions":nodes.get("inputOptions",[]),
                            "detailControls":nodes.get("detailControls",[]),
                            "targetRows":nodes.get("targetRows",[]),
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
    stage="setup"
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
            observed_posts=[]
            date_replay_candidates=[]
            def on_request(req):
                parsed=urlparse(req.url)
                if (parsed.hostname==G2B_HOST and req.method=="POST"
                        and parsed.path.endswith(".do")):
                    raw=_flatten_post(req.post_data)
                    # Diagnose dates only: never log raw body, company data,
                    # session keys or unrelated input fields.
                    date_evidence=[]
                    if detail10 in raw:
                        try:
                            decoded=json.loads(req.post_data)
                            def date_fields(obj,prefix=""):
                                if isinstance(obj,dict):
                                    for k,v in obj.items():
                                        key=(prefix+"."+str(k))[-110:]
                                        if isinstance(v,(dict,list)):date_fields(v,key)
                                        elif isinstance(v,(str,int)) and re.search(
                                            r"date|ymd|dt|from|to|str|end|begin|start|pbanc|onbs",str(k),re.I):
                                            value=str(v).strip()
                                            if re.fullmatch(r"20[0-9]{6}",value):
                                                date_evidence.append({"key":key,"date":value})
                                elif isinstance(obj,list):
                                    for x in obj[:10]:date_fields(x,prefix)
                            date_fields(decoded)
                        except (ValueError,TypeError):
                            pass
                    observed_posts.append({"path":parsed.path[:130],
                        "has_code":detail10 in raw,
                        "has_start":w["start"].replace("-","") in re.sub(r"[^0-9]","",raw),
                        "has_end":w["end"].replace("-","") in re.sub(r"[^0-9]","",raw),
                        "date_fields":date_evidence[:16]})
                    if (parsed.path=="/pn/pnp/pnpe/BidPbac/selectBidPbacScrollTypeList.do"
                            and detail10 in raw):
                        date_replay_candidates.append(req)
                    if request_has_filter(req.post_data,detail10,w["start"],w["end"]):
                        requests.append({"url":req.url.split("?")[0],"request":req})
            def on_response(r):
                if any(x["request"]==r.request for x in requests):
                    responses.append(r)
            context.on("request",on_request)
            context.on("response",on_response)
            tab=context.new_page()
            dialogs=[]
            def note_dialog(d):
                msg=(d.message or "")[:150]
                dialogs.append(msg)
                try:d.dismiss()
                except Exception:pass
            tab.on("dialog",note_dialog)
            stage="home_load"
            tab.goto(G2B_HOME,wait_until="domcontentloaded",timeout=30000)
            if not _wait_for_site_rendered(tab):
                tab.reload(wait_until="domcontentloaded",timeout=30000)
            if not _wait_for_site_rendered(tab):
                import logging
                logging.warning("FRESH_G2B_PUBLIC_SEARCH_SCREEN_LIVE %s",
                  json.dumps(_safe_search_screen_diagnostic(tab),
                    ensure_ascii=False,default=str)[:5500])
                raise SearchBlocked("G2B_OFFICIAL_SITE_RENDERED_EMPTY_AFTER_WAIT")
            stage="menu_navigation"
            try:
                _navigate(tab)
            except SearchBlocked:
                import logging
                logging.warning("FRESH_G2B_PUBLIC_SEARCH_SCREEN_LIVE %s",
                  json.dumps(_safe_search_screen_diagnostic(tab),
                    ensure_ascii=False,default=str)[:5500])
                raise
            stage="fill_code_and_dates"
            _fill_search_fields(tab,w)
            _dismiss_public_notices(tab)
            tab.wait_for_timeout(1600)
            _dismiss_public_notices(tab)
            stage="submit_search"
            # Require an actual site search button and form submission.
            if not _click_notice_search(tab):
                raise SearchBlocked("BID_NOTICE_SEARCH_BUTTON_NOT_FOUND")
            stage="await_verified_request"
            tab.wait_for_timeout(2500)
            corrected_response=None
            if not requests and date_replay_candidates:
                original=date_replay_candidates[-1]
                payload=_verified_date_replay(original,detail10,w["start"],w["end"])
                # Browser navigation supplied the authentic submission headers.
                # Playwright APIRequestContext shares this browser's cookie jar.
                allowed={"accept","content-type","menu-info","submissionid",
                         "usr-id","referer","x-requested-with"}
                headers={k:v for k,v in original.headers.items()
                         if k.lower() in allowed}
                headers["Content-Type"]="application/json;charset=UTF-8"
                corrected_response=context.request.post(
                    original.url.split("?")[0],data=payload,
                    headers=headers,timeout=35000)
                if corrected_response.status!=200:
                    raise SearchBlocked("OFFICIAL_DATE_REPLAY_HTTP_"+str(corrected_response.status))
            if not requests and corrected_response is None:
                import logging
                logging.warning("FRESH_G2B_SEARCH_DIALOGS %s",json.dumps(dialogs[-8:],ensure_ascii=False))
                logging.warning("FRESH_G2B_SEARCH_POST_DIAG %s",
                    json.dumps(observed_posts[-16:],ensure_ascii=False))
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
            if not matched_responses and corrected_response is None:
                raise SearchBlocked("BID_NOTICE_SEARCH_RESPONSE_NOT_CAPTURED")
            stage="verify_response"
            last=corrected_response if corrected_response is not None else matched_responses[-1]
            if last.status!=200:
                raise SearchBlocked("BID_NOTICE_SEARCH_HTTP_"+str(last.status))
            try:
                data=last.json()
            except Exception:
                raise SearchBlocked("BID_NOTICE_SEARCH_RESPONSE_NOT_JSON") from None
            # Schema evidence only, never log bid rows or sensitive values.
            def public_shape(value,depth=0):
                if depth>3:return {"type":type(value).__name__}
                if isinstance(value,dict):
                    return {str(k)[:55]: public_shape(v,depth+1)
                            for k,v in list(value.items())[:35]}
                if isinstance(value,list):
                    return {"type":"list","length":len(value),
                            "first":public_shape(value[0],depth+1) if value else None}
                return {"type":type(value).__name__}
            import logging
            logging.warning("FRESH_G2B_OFFICIAL_RESULT_SCHEMA %s",
                json.dumps(public_shape(data),ensure_ascii=False)[:4500])
            records,total=_response_records(data)
            logging.warning("FRESH_G2B_OFFICIAL_RESULT_COUNTS %s",
                json.dumps({"parsed":len(records) if records is not None else None,
                            "total":total,
                            "sample_public_bid_ids":[x["bid_no"] for x in (records or [])[:3]]},
                           ensure_ascii=False))
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
        output["reason"]="G2B_UI_RUNTIME_"+stage+"_"+type(exc).__name__
        output["search_request_verified"]=False
    return output
