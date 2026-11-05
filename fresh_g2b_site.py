"""Actual source adapters ONLY. No legacy DB access or 229-record cache.

Search: G2B public real UI, fails closed until observed exact-10 POST.
Opening: existing verified WebSquare endpoints, real listing keys first.
Documents: fetch file links from actual G2B detail page, verify hosts and bytes.
"""
from __future__ import annotations
import hashlib,json,re,time
from datetime import date,timedelta
from urllib.parse import urlencode,urljoin,urlparse,parse_qs
from urllib.request import Request,urlopen
from playwright.sync_api import sync_playwright
from g2b_bid_notice_site_search import run_search,search_window

BASE="https://www.g2b.go.kr/"
HOSTS={"www.g2b.go.kr","g2b.go.kr"}
BID=re.compile(r"^(?:R\d{2}[A-Z]{2}\d{8}|\d{11})$")
ORD=re.compile(r"^\d{3}$")
LIST=BASE+"pb/pbo/pboc/OnbsRslt/selectOnbsRsltClsfList.do"
DETAIL=BASE+"pb/pbo/pboc/OnbsRslt/selectOnbsRsltSbidGods.do"
LIST_MENU='{"menuNo":"01522","menuCangVal":"PBOC006_01","bsneClsfCd":"%EC%97%85130028","scrnNo":"02117"}'
LIST_SUBMISSION="mf_wfm_container_selectOnbsRsltClsfList"
DETAIL_MENU='{"menuNo":"15620","scrnNo":"08542"}'

class SourceBlocked(RuntimeError):pass

def _check(no,ord_):
    if not BID.fullmatch(no or "") or not ORD.fullmatch(ord_ or ""):
        raise SourceBlocked("INVALID_G2B_NOTICE_ID")

def search_one(detail10,first,last,cursor=None,page=1):
    w=search_window(detail10,first,last,cursor,page)
    result=run_search(detail10,first,last,cursor,page)
    if not (result.get("status")=="partial_filtered_result" and
            result.get("search_request_verified")):
        raise SourceBlocked("OFFICIAL_BID_SEARCH_UNVERIFIED_"+str(result.get("reason") or result.get("status")))
    rows=[]
    verified=result.get("matched_explicit_detail10") or []
    pending=result.get("pending_original_detail10_verification") or []
    for item in list(verified)+list(pending):
        codes=item.get("direct_category_codes") or []
        explicit=detail10 in codes
        if detail10 and codes and not explicit:
            continue
        raw=item.get("raw")
        if not isinstance(raw,dict):
            raise SourceBlocked("OFFICIAL_SEARCH_ORIGINAL_ROW_MISSING")
        posted=str(item.get("posted_on") or "")[:10]
        if re.fullmatch(r"\d{8}",posted):
            posted=posted[:4]+"-"+posted[4:6]+"-"+posted[6:8]
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}",posted):
            posted=None
        rows.append({
          "bid_no":item["bid_no"],"bid_ord":item["bid_ord"],
          "detail10":detail10,"title":item["title"],
          "agency":item["agency"],"posted_on":posted,
          "original_category_evidence":explicit,
          "official_filter_verified":True,"raw":raw
        })
    return w,result,rows

def _post(ctx,url,data,headers):
    response=ctx.request.post(url,data=json.dumps(data,ensure_ascii=False),
       headers=headers,timeout=35000)
    if response.status!=200:raise SourceBlocked("G2B_HTTP_"+str(response.status))
    try:body=response.json()
    except (ValueError,TypeError):raise SourceBlocked("G2B_RESPONSE_NOT_JSON") from None
    if not isinstance(body,dict) or not isinstance(body.get("result"),dict):
        raise SourceBlocked("G2B_RESPONSE_SCHEMA_UNVERIFIED")
    if str(body.get("ErrorCode",0)) not in ("0","00"):
        raise SourceBlocked("G2B_RESPONSE_ERROR_CODE_"+str(body.get("ErrorCode")))
    return body["result"]

def _date_windows(posted):
    """Bound to explicit posted date; don't scan ALL notices or use stale DB."""
    try:initial=date.fromisoformat(posted)
    except (ValueError,TypeError):raise SourceBlocked("OFFICIAL_NOTICE_PUBLISHED_DATE_REQUIRED")
    last=min(date.today(),initial+timedelta(days=92))
    while initial<=last:
        end=min(last,initial+timedelta(days=30))
        yield initial,end
        initial=end+timedelta(days=1)

def _listing(ctx,no,ord_,published):
    for begin,end in _date_windows(published):
        # G2B's existing observed opening-list submission has a real bidPbancNo
        # condition. Do not treat an empty response as proof that no bidder exists.
        for page in range(1,5):
            first=1+(page-1)*10
            req={"dlSrchOnbsRsltClsfListInM":{
                "bidPbancNo":no,"bidPbancOrd":ord_,"bidPbancNm":"",
                "onbsYmdStr":begin.strftime("%Y%m%d"),
                "onbsYmdEnd":end.strftime("%Y%m%d"),
                "prcmBsneSeCd":"0000 조070001 조070002 조070003 조070004 조070005",
                "frcpYn":"Y","rsrvYn":"Y","laseYn":"Y","chkBsneAllYn":"Y",
                "lastIndex":first+9,"firstIndex":first,
                "inqEnd":"","stepBarYn":"","pbancKndCd":"공440002"}}
            result=_post(ctx,LIST,req,{
               "Accept":"application/json",
               "Content-Type":"application/json;charset=UTF-8",
               "Menu-Info":LIST_MENU,"submissionid":LIST_SUBMISSION,
               "Usr-Id":"null","Referer":BASE})
            candidates=result.get("onbsRsltClsfList")
            if not isinstance(candidates,list):
                raise SourceBlocked("G2B_OPENING_LIST_SCHEMA_MISSING")
            for r in candidates:
                if not isinstance(r,dict) or str(r.get("bidPbancNo") or "")!=no:
                    continue
                if str(r.get("bidPbancOrd") or "000").zfill(3)!=ord_:continue
                yield {
                  "bid_no":no,"bid_ord":ord_,
                  "bid_clsfc_no":str(r.get("bidClsfNo") or "0"),
                  "bid_progress_ord":str(r.get("bidPrgrsOrd") or "000"),
                  "business_code":str(r.get("prcmBsneSeCd") or ""),
                  "status":str(r.get("bidPgstCd") or ""),
                  "raw_listing":r,"listing_url":LIST}
            if len(candidates)<10:break

def _opening(ctx,listing):
    no,ord_=listing["bid_no"],listing["bid_ord"]
    bidders=[];raw_info={};etc={};total=0
    for pn in range(1,6):
        req={"dlSrchOnbsRsltBidInM":{
          "bidPbancNo":no,"bidPbancOrd":ord_,
          "bidClsfNo":listing["bid_clsfc_no"],
          "bidPrgrsOrd":listing["bid_progress_ord"],
          "prcmBsneSeCd":listing["business_code"],
          "bidPgstCd":listing["status"],
          "bzmnRegNo":"","reOpenPbancYN":"",
          "currentPage":pn,"recordCountPerPage":"999"}}
        result=_post(ctx,DETAIL,req,{
          "Content-Type":"application/json","Menu-Info":DETAIL_MENU,
          "User-Agent":"Mozilla/5.0","Referer":BASE})
        rows=result.get("successBidInfo")
        if not isinstance(rows,list):raise SourceBlocked("G2B_BIDDER_LIST_NOT_PUBLISHED")
        if pn==1:
            raw_info=result.get("bidInfo") or {}
            etc=result.get("etcData") or {}
            if rows:
                try:total=int(rows[0].get("totCnt") or 0)
                except (ValueError,TypeError):total=0
        bidders.extend(x for x in rows if isinstance(x,dict))
        if not rows or str(rows[-1].get("nextRowYn") or "N")!="Y":break
    if len(bidders)>=5*999 and str(rows[-1].get("nextRowYn") or "N")=="Y":
        raise SourceBlocked("G2B_BIDDER_PAGINATION_INCOMPLETE")
    return {"bid_no":no,"bid_ord":ord_,"total":total or len(bidders),
      "bidders":bidders,"bid_info":raw_info,"etc_data":etc}

def _confirmed_name(entry):
    # Explicit final winner + completion signal, not merely rank 1.
    fields=("fnlSucsfbdCorpNm","bidWinnrNm","fnlBidWinnrNm")
    markers=("최종낙찰","낙찰자확정","낙찰자 선정 완료")
    for obj in (entry.get("bid_info"),entry.get("etc_data")):
        if not isinstance(obj,dict):continue
        serialized=json.dumps(obj,ensure_ascii=False,default=str)
        if not any(m in serialized for m in markers):continue
        for key in fields:
            winner=str(obj.get(key) or "").strip()
            if winner:return winner
    return None

def opening_for_one(no,ord_,published):
    _check(no,ord_)
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True,args=["--no-sandbox","--disable-dev-shm-usage"])
        context=browser.new_context(locale="ko-KR",timezone_id="Asia/Seoul")
        try:
            r=context.request.get(BASE,timeout=25000)
            if r.status>=400:raise SourceBlocked("G2B_HOME_HTTP_"+str(r.status))
            observed=list(_listing(context,no,ord_,published))
            outputs=[]
            for listing in observed:
                entry=_opening(context,listing)
                outputs.append({"listing":listing,"opening":entry,
                                "confirmed_winner_name":_confirmed_name(entry)})
            return outputs
        finally:
            context.close();browser.close()

def _official(url):
    p=urlparse(url)
    return p.scheme=="https" and p.hostname in HOSTS and not p.username and not p.password

def source_detail_url(no,ord_):
    _check(no,ord_)
    return BASE+"link/PNPE027_01/single/?"+urlencode({
        "bidPbancNo":no,"bidPbancOrd":ord_})

def discover_attachments(no,ord_):
    """Use direct official site, not old DB's known file URLs.
    Only return confirmed government-origin attachment links.
    """
    target=source_detail_url(no,ord_)
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True,args=["--no-sandbox","--disable-dev-shm-usage"])
        context=browser.new_context(locale="ko-KR",timezone_id="Asia/Seoul")
        try:
            page=context.new_page()
            response=page.goto(target,wait_until="domcontentloaded",timeout=35000)
            if not response or response.status>=400:
                raise SourceBlocked("G2B_DETAIL_UNAVAILABLE")
            page.wait_for_timeout(1200)
            candidates=[]
            for fr in page.frames:
                if fr.is_detached():continue
                try:
                    links=fr.locator("a[href]").evaluate_all(
                       "(nodes)=>nodes.map(n=>({href:n.href,text:(n.innerText||n.title||'').trim()}))")
                except Exception:continue
                for link in links:
                    u=link["href"]
                    if not _official(u):continue
                    path=urlparse(u).path.lower()
                    if not re.search(r"attach|download|file|doc|spec|hwp|pdf|hwpx",path):
                        continue
                    q=parse_qs(urlparse(u).query)
                    # If URL carries bid identifier, it must match.
                    for k in ("bidPbancNo","bidNtceNo"):
                        if k in q and q[k]!=[no]:
                            raise SourceBlocked("G2B_ATTACHMENT_NOTICE_MISMATCH")
                    candidates.append({"url":u,"filename":link["text"][:190],
                         "file_key":hashlib.sha256(u.encode()).hexdigest()[:36]})
            dedup={x["url"]:x for x in candidates}
            return {"bid_no":no,"bid_ord":ord_,"source_url":target,
                    "files":list(dedup.values())[:70],
                    "state":"links_visible" if dedup else "attachment_links_not_identified"}
        finally:context.close();browser.close()

def download_attachment(item):
    """HTTPS allowlist + redirect validation; real bytes only."""
    url=item["url"]
    if not _official(url):raise SourceBlocked("NON_OFFICIAL_FILE_HOST")
    req=Request(url,headers={"Accept":"application/octet-stream",
                              "User-Agent":"Mozilla/5.0"})
    with urlopen(req,timeout=30) as r:
        if not _official(r.url):raise SourceBlocked("NON_OFFICIAL_FILE_REDIRECT")
        mime=r.headers.get("Content-Type","")[:100]
        raw=r.read(18*1024*1024+1)
        if len(raw)>18*1024*1024:raise SourceBlocked("OFFICIAL_FILE_TOO_LARGE")
        if not raw:raise SourceBlocked("OFFICIAL_FILE_EMPTY")
        # HTML error pages are not downloadable attachments.
        if raw[:1024].lstrip().lower().startswith((b"<!doctype html",b"<html")):
            raise SourceBlocked("OFFICIAL_FILE_HTML_ERROR")
    name=item["filename"] or urlparse(url).path.rsplit("/",1)[-1]
    from g2b_documents import extract_file
    try:state,text=extract_file(name,raw)
    except Exception as err:state,text="parse_"+type(err).__name__,""
    return {"filename":name,"url":url,"file_key":item["file_key"],
            "mime":mime,"data":raw,"sha256":hashlib.sha256(raw).hexdigest(),
            "extract_state":state,"extracted_text":text}
