"""Read only from REAL official G2B web pages; no calls to historical DB.

Only pure external-fetch/extraction primitives are imported from the existing
project. Never invoke their collect / save_batch / session functions or legacy DB code.
"""
from __future__ import annotations
from datetime import date
from hashlib import sha256
from urllib.parse import urljoin,urlparse,urlencode,parse_qs
from urllib.request import Request,urlopen
import json
import re

G2B="https://www.g2b.go.kr/"
ALLOWED={"www.g2b.go.kr","g2b.go.kr"}
DOCUMENT_EXTENSIONS=(".hwp",".hwpx",".pdf",".docx",".xlsx",".xls",".zip",".doc",".txt",".csv")
BID=re.compile(r"^(?:R\d{2}[A-Z]{2}\d{8}|\d{11})$")
ORD=re.compile(r"^\d{3}$")
TEN=re.compile(r"^\d{10}$")


class SiteUnavailable(RuntimeError):
    pass


def official_url(url):
    parsed=urlparse(url)
    return parsed.scheme=="https" and parsed.hostname in ALLOWED and not parsed.username and not parsed.password


def official_file_identity(url):
    """Recognize real G2B site attachment endpoint and its notice identity."""
    if not official_url(url):
        raise ValueError("G2B_HTTPS_HOST_REQUIRED")
    p=urlparse(url)
    if p.path!="/pn/pnp/pnpe/UntyAtchFile/downloadFile.do":
        raise ValueError("NOT_OFFICIAL_NOTICE_FILE_ENDPOINT")
    q=parse_qs(p.query,keep_blank_values=True)
    no=(q.get("bidPbancNo") or [""])[0]
    ord_=(q.get("bidPbancOrd") or [""])[0]
    seq=(q.get("fileSeq") or [""])[0]
    if not BID.fullmatch(no) or not ORD.fullmatch(ord_) or not re.fullmatch(r"\d{1,4}",seq):
        raise ValueError("OFFICIAL_ATTACHMENT_IDENTITY_INCOMPLETE")
    if any(len(vals)!=1 for vals in q.values()):
        raise ValueError("DUPLICATE_ATTACHMENT_QUERY_PARAMETERS")
    return no,ord_


def detail_url(no,ord_):
    if not BID.fullmatch(no) or not ORD.fullmatch(ord_):
        raise ValueError("INVALID_G2B_NOTICE_ID")
    return G2B+"link/PNPE027_01/single/?"+urlencode(
      {"bidPbancNo":no,"bidPbancOrd":ord_})


def search_original_site(code10,start,end,month=None,page=1):
    from g2b_bid_notice_site_search import run_search
    if not TEN.fullmatch(code10):
        raise ValueError("EXACT_10_REQUIRED")
    return run_search(code10,start,end,cursor=month,page=page)


def _visible_text(fr):
    try:
        text=fr.locator("body").inner_text(timeout=2500)
        return text[:800000]
    except Exception:
        return ""


def _body_html(fr):
    try:return fr.locator("body").inner_html(timeout=2500)[:1800000]
    except Exception:return ""


def explicit_detail10(text,expected):
    """Require the FIRST explicit ten-digit number following a field label.

    A later unrelated code, or a code in a notice title, never proves this
    notice has the expected 10-digit detail classification.
    """
    if not TEN.fullmatch(expected):return False
    simple=re.sub(r"\s+"," ",text)
    for label in re.finditer(r"(?:세부품명번호|세부품명\s*번호|세부품명)",simple,re.I):
        segment=simple[label.end():label.end()+105]
        first=re.search(r"(?<!\d)\d{10}(?!\d)",segment)
        if first and first.group(0)==expected:
            return True
    return False

def extract_links(frame):
    js=r"""() => Array.from(document.querySelectorAll('a[href]'))
       .map(a=>({href:a.href,label:(a.innerText||a.getAttribute('title')||a.download||'').trim()}))
       .slice(0,800)"""
    out=[]
    try:
        for item in frame.evaluate(js):
            url=str(item.get("href") or "")
            path=urlparse(url).path.lower()
            label=str(item.get("label") or "")
            if not official_url(url):continue
            # Only mark a link as an attachment when the URL or link label
            # suggests a file, not site navigation or the whole detail page.
            if (path.endswith(DOCUMENT_EXTENSIONS) or
                any(label.lower().endswith(ext) for ext in DOCUMENT_EXTENSIONS) or
                re.search(r"/(?:file|atch|attach|download)/",path,re.I)):
                if len(url)<=1600 and not any(x["url"]==url for x in out):
                    out.append({"url":url,"filename":label[:230] or path.rsplit("/",1)[-1]})
    except Exception:
        pass
    return out[:60]


def fetch_original_detail(no,ord_,expected_code10):
    """Open official notice detail page, capture current DOM + file references.

    No classification verification without visibly adjacent detail-label/code.
    A blocked site is NOT a verified notice or an empty match.
    """
    if not TEN.fullmatch(expected_code10):
        raise ValueError("EXPECTED_DETAIL10_REQUIRED")
    url=detail_url(no,ord_)
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True,args=[
            "--no-sandbox","--disable-dev-shm-usage"])
        cx=browser.new_context(locale="ko-KR",timezone_id="Asia/Seoul")
        tab=cx.new_page()
        try:
            r=tab.goto(url,wait_until="domcontentloaded",timeout=35000)
            if not r or r.status!=200:
                raise SiteUnavailable("OFFICIAL_NOTICE_DETAIL_HTTP_"+str(r.status if r else 0))
            tab.wait_for_timeout(1800)
            frames=list(tab.frames)
            contents=[{"url":fr.url,"text":_visible_text(fr),"html":_body_html(fr)}
                      for fr in frames if "g2b.go.kr" in (urlparse(fr.url).hostname or "")]
            text_value="\n".join(x["text"] for x in contents)
            if not text_value.strip():
                raise SiteUnavailable("OFFICIAL_NOTICE_DETAIL_NOT_RENDERED")
            # Record the full available DOM snapshot and extraction evidence.
            verified=explicit_detail10(text_value,expected_code10)
            links=[]
            for fr in frames:
                if "g2b.go.kr" in (urlparse(fr.url).hostname or ""):
                    links+=extract_links(fr)
            urls={x["url"]:x for x in links}
            return {"bid_no":no,"bid_ord":ord_,"url":url,
                    "content":json.dumps(contents,ensure_ascii=False)[:2000000],
                    "detail10":expected_code10 if verified else None,
                    "explicit_detail10":verified,
                    "title":tab.title()[:400],
                    "agency":"",
                    "attachments":list(urls.values())[:60],
                    "extraction_status":"official_dom_10digit_label_verified" if verified
                              else "official_dom_without_explicit_detail10"}
        finally:
            cx.close()
            browser.close()


def download_original_file(url,max_bytes=18*1024*1024):
    """Only official HTTPS host, including redirect target. No DB lookup."""
    if not official_url(url):
        raise ValueError("UNTRUSTED_G2B_FILE_HOST")
    from g2b_documents import extract_file
    req=Request(url,headers={"Accept":"application/octet-stream",
                    "User-Agent":"ProcureFlow-FreshSite/1.0"})
    with urlopen(req,timeout=35) as r:
        if not official_url(r.url):
            raise ValueError("UNTRUSTED_G2B_FILE_REDIRECT")
        mime=str(r.headers.get("content-type") or "")[:120]
        name=r.headers.get_filename() if hasattr(r.headers,"get_filename") else None
        if not name:
            cd=str(r.headers.get("content-disposition") or "")
            m=re.search(r'filename="?([^";]+)"?',cd,re.I)
            if m:name=m.group(1)
        name=str(name or urlparse(r.url).path.rsplit("/",1)[-1] or "unknown")[:240]
        raw=r.read(max_bytes+1)
    if len(raw)>max_bytes:raise ValueError("FILE_EXCEEDS_18MB_LIMIT")
    # WebSquare downloadFile.do often has no filename extension at all.
    if raw.startswith(b"%PDF") and not name.lower().endswith(".pdf"):
        name="official_notice_"+sha256(raw).hexdigest()[:12]+".pdf"
    elif raw.startswith(b"PK\x03\x04") and "." not in name:
        name="official_notice_"+sha256(raw).hexdigest()[:12]+".hwpx"
    if raw[:50].lstrip().lower().startswith((b"<!doctype html",b"<html")):
        raise SiteUnavailable("FILE_RETURNED_HTML_NOT_DOWNLOAD")
    state,text_value=extract_file(name,raw)
    return {"content":raw,"filename":name,"mime":mime,"text":text_value,
            "state":state,"sha256":sha256(raw).hexdigest()}


def fetch_actual_opening(no,ord_):
    """Pure fetch_opening(), NOT collection or legacy save method from old project."""
    if not BID.fullmatch(no) or not ORD.fullmatch(ord_):
        raise ValueError("INVALID_OPENING_NOTICE")
    from playwright.sync_api import sync_playwright
    from g2b_bid_collector import fetch_opening
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True,args=[
            "--no-sandbox","--disable-dev-shm-usage"])
        cx=browser.new_context(locale="ko-KR",timezone_id="Asia/Seoul")
        try:
            r=cx.request.get(G2B,timeout=25000)
            if r.status!=200:
                raise SiteUnavailable("G2B_OPENING_HOMEPAGE_HTTP_"+str(r.status))
            result=fetch_opening(cx,no,ord_,max_pages=3)
            if result.get("bid_no")!=no or result.get("bid_ord")!=ord_:
                raise SiteUnavailable("G2B_OPENING_WRONG_NOTICE")
            return result
        finally:
            cx.close()
            browser.close()


def explicitly_confirmed_winner(data):
    """Pure final-award confirmation. Never rank-1-as-winner."""
    from g2b_bid_collector import _final_award
    info=data.get("bid_info") or {}
    etc=data.get("etc_data") or {}
    name=_final_award(info,etc)
    if not name:
        return {"status":"not_confirmed"}
    matching=[x for x in (data.get("bidders") or [])
              if str(x.get("grpNm") or "").strip()==name]
    if len(matching)!=1:
        return {"status":"winner_identity_ambiguous"}
    offer=matching[0]
    amount=str(offer.get("bdngAmt") or "").strip()
    if not re.fullmatch(r"\d+(?:\.\d+)?",amount):
        return {"status":"final_award_amount_not_verified"}
    return {"status":"explicit_final_confirmed","company":name,"amount":amount,
            "source_sha256":sha256(json.dumps({"info":info,"etc":etc,"offer":offer},
                        sort_keys=True,ensure_ascii=False,default=str).encode()).hexdigest()}


def probe_public_ui():
    """Capture only non-secret, public UI labels to diagnose G2B navigation.

    Records no cookies, form values, headers, identities or login state.
    Does NOT infer that a search or 10-digit field was verified.
    """
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True,args=["--no-sandbox","--disable-dev-shm-usage"])
        cx=browser.new_context(locale="ko-KR",timezone_id="Asia/Seoul")
        tab=cx.new_page()
        try:
            r=tab.goto(G2B,wait_until="domcontentloaded",timeout=35000)
            tab.wait_for_timeout(2200)
            def snapshot(label):
                fdata=[]
                for fr in tab.frames[:14]:
                    host=urlparse(fr.url).hostname or ""
                    if host and not host.endswith("g2b.go.kr"):continue
                    try:
                        safe=fr.evaluate(r"""()=>{
                          const visible=e=>!!(e.offsetWidth||e.offsetHeight||e.getClientRects().length);
                          const items=[...document.querySelectorAll('a,button,[role=button],label,input,select')];
                          return {
                            title:document.title,
                            body_excerpt:(document.body?.innerText||'').slice(0,900),
                            links:items.filter(e=>visible(e)&&e.tagName!=='INPUT'&&e.tagName!=='SELECT')
                              .slice(0,150).map(e=>({tag:e.tagName,text:(e.innerText||e.getAttribute('aria-label')||
                                    e.getAttribute('title')||'').trim().slice(0,60)}))
                              .filter(e=>e.text),
                            fields:items.filter(e=>visible(e)&&(e.tagName==='INPUT'||e.tagName==='SELECT'))
                              .slice(0,35).map(e=>({tag:e.tagName,id:e.id.slice(0,60),
                                name:(e.getAttribute('name')||'').slice(0,60),
                                placeholder:(e.getAttribute('placeholder')||'').slice(0,60)}))
                          }
                        }""")
                    except Exception as ex:
                        safe={"reason":type(ex).__name__}
                    fdata.append({"path":urlparse(fr.url).path[:100],"data":safe})
                return {"step":label,"http_status":r.status if r else None,
                        "page_path":urlparse(tab.url).path[:100],"frames":fdata}
            before=snapshot("homepage")
            clicked=[]
            for names in (("전체메뉴 열기","전체메뉴","전체 메뉴","전체메뉴보기"),
                          ("입찰공고 목록","입찰공고목록","입찰공고 조회","입찰공고")):
                ok=False
                for name in names:
                    for fr in tab.frames[:14]:
                        try:
                            loc=fr.get_by_text(name,exact=True)
                            if loc.count():
                                loc.first.click(timeout=1600)
                                ok=True;break
                        except Exception:continue
                    if ok:break
                clicked.append({"candidates":names,"clicked":ok})
                if ok:tab.wait_for_timeout(1200)
            after=snapshot("after_menu_navigation")
            return {"website":"www.g2b.go.kr","stages":[before,after],
                    "attempts":clicked,"search_verified":False}
        finally:
            cx.close();browser.close()
