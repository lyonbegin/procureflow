"""Read-only G2B opening and award web scraper; never requires OpenAPI keys.

Collects the public WebSquare 개찰결과분류조회 screen and its own same-origin
detail request. Browser sessions are ephemeral and no tenders are submitted.
Only explicit final-award fields can be classified as final winners.
"""
from __future__ import annotations
from datetime import datetime, timezone, timedelta
import hashlib
import json
import logging
import re
import time

from playwright.sync_api import sync_playwright
from db import session

BASE = "https://www.g2b.go.kr/"
OPENING_URL = "https://www.g2b.go.kr/pb/pbo/pboc/OnbsRslt/selectOnbsRsltSbidGods.do"
MENU_INFO = json.dumps({"menuNo":"15620","scrnNo":"08542"},separators=(",",":"))
GRID_ID = "#mf_wfm_container_onbsRsltClsfInqyGrd"
G2B_BID_RE = re.compile(r"(?<![A-Z0-9])(?:R\d{2}BK\d{8}|\d{11})(?:[-－](\d{3}))?(?![A-Z0-9])")
ID_ONLY_RE = re.compile(r"(?:R\d{2}BK\d{8}|\d{11})")
WINNER_KEYS = ("fnlSucsfbdCorpNm","bidWinnrNm","fnlBidWinnrNm")
COMPLETE_SIGNALS = ("최종낙찰","낙찰자확정","낙찰자 선정 완료")
SERVER_ERROR_SIGNS = ("죄송합니다","서비스 점검","요청하신 페이지에")


def configured() -> bool:
    """Unlike the earlier official-API adapter, web scraping needs no key."""
    return True


def normalize_id(value: str):
    value = str(value or "").strip().upper()
    m = re.fullmatch(r"(R\d{2}BK\d{8}|\d{11})(?:[-－](\d{3}))?", value)
    return (m.group(1),m.group(2) or "000") if m else None


# G2B's actual public WebSquare opening-list submission (not data.go.kr).
# Field names / Menu-Info observed in a publicly documented G2B web client.
LIST_URL = "https://www.g2b.go.kr/pb/pbo/pboc/OnbsRslt/selectOnbsRsltClsfList.do"
LIST_MENU = '{"menuNo":"01522","menuCangVal":"PBOC006_01","bsneClsfCd":"%EC%97%85130028","scrnNo":"02117"}'
LIST_SUBMISSION = "mf_wfm_container_selectOnbsRsltClsfList"


def fetch_opening_listing(context, days=7, pages=1, max_results=60):
    """Read an actual dated G2B opening-results list via its public web form.

    Avoid WebSquare GNB navigation: Railway Chrome can load a blank document
    even when the same-origin JSON submission is available. Errors are not
    indistinguishable from a legitimate empty search.
    """
    now=datetime.now(timezone(timedelta(hours=9)))
    start=(now-timedelta(days=max(1,min(int(days),31)))).strftime("%Y%m%d")
    end=now.strftime("%Y%m%d")
    # WebSquare firstIndex/lastIndex bounds: use 10 distinct records per page.
    batch=10
    output=[]
    total=None
    for page_number in range(1,max(1,min(int(pages),10))+1):
        first=1+(page_number-1)*batch
        payload={"dlSrchOnbsRsltClsfListInM":{
            "bidPbancNo":"","bidPbancOrd":"","bidPbancNm":"",
            "onbsYmdStr":start,"onbsYmdEnd":end,
            "prcmBsneSeCd":"0000 조070001 조070002 조070003 조070004 조070005",
            "frcpYn":"Y","rsrvYn":"Y","laseYn":"Y","chkBsneAllYn":"Y",
            "lastIndex":first+batch-1,"firstIndex":first,
            "inqEnd":"","stepBarYn":"","pbancKndCd":"공440002"
        }}
        response=context.request.post(LIST_URL,data=json.dumps(payload),
            headers={"Accept":"application/json",
                     "Content-Type":"application/json;charset=UTF-8",
                     "Menu-Info":LIST_MENU,
                     "submissionid":LIST_SUBMISSION,
                     "Usr-Id":"null","Referer":BASE},
            timeout=35000)
        if response.status!=200:
            # Only bounded non-sensitive response text is allowed in logs.
            logging.warning("G2B_LIST_HTTP status=%s summary=%s",
                            response.status,response.text()[:190])
            raise RuntimeError("g2b_web_listing_http_"+str(response.status))
        try: result=response.json()
        except Exception:raise RuntimeError("g2b_web_listing_not_json") from None
        data=result.get("result") if isinstance(result,dict) else None
        if not isinstance(data,dict):
            raise RuntimeError("g2b_web_listing_bad_schema")
        items=data.get("onbsRsltClsfList")
        if not isinstance(items,list):
            raise RuntimeError("g2b_web_listing_missing_items")
        count_before=len(output)
        for rec in items:
            if not isinstance(rec,dict):continue
            original=str(rec.get("bidPbancNo") or "")
            if not ID_ONLY_RE.fullmatch(original):continue
            ord_no=str(rec.get("bidPbancOrd") or "000")
            if not re.fullmatch(r"\d{3}",ord_no):continue
            status=str(rec.get("bidPgstCd") or "")
            raw={k:rec.get(k) for k in (
                "bidPbancNm","dmstNm","demaInstNm","bidPgstCd",
                "onbsPrnmntDt","bidPbancNo","bidPbancOrd",
                "bidClsfNo","bidPrgrsOrd","prcmBsneSeCd")
                 if rec.get(k) is not None}
            output.append({
                "bid_no":original,"bid_ord":ord_no,
                "bid_clsfc_no":str(rec.get("bidClsfNo") or "0"),
                "bid_progress_ord":str(rec.get("bidPrgrsOrd") or "000"),
                "business_code":str(rec.get("prcmBsneSeCd") or ""),
                "status":status,"title":str(rec.get("bidPbancNm") or ""),
                "agency":str(rec.get("dmstNm") or rec.get("demaInstNm") or ""),
                "raw_listing":raw,
            })
            if len(output)>=max_results:break
        logging.info("G2B_LIST_PAGE from=%s to=%s page=%s returned=%s accepted=%s keys=%s",
                     start,end,page_number,len(items),len(output)-count_before,
                     sorted(data.keys())[:12])
        if items and page_number==1:
            logging.info("G2B_LIST_SAMPLE_FIELD_NAMES keys=%s progress_sample=%s",
                         sorted(items[0].keys())[:85],
                         {k:items[0].get(k) for k in ("bidPgstCd","prcmBsneSeCd",
                                                      "bidClsfNo","bidPrgrsOrd")})
        if len(output)>=max_results or len(items)<batch:break
    dedup={}
    for item in output:
        composite=(item["bid_no"],item["bid_ord"],
                   item["bid_clsfc_no"],item["bid_progress_ord"])
        dedup[composite]=item
    return list(dedup.values())[:max_results]


def discover_visible_bids(page, limit=30):
    """Navigate observed public G2B menu and extract IDs ONLY from the results grid."""
    steps=(("입찰",),("입찰개찰/낙찰","입찰개찰·낙찰"),("개찰결과분류조회",))
    page.goto(BASE,wait_until="domcontentloaded",timeout=40000)
    page.wait_for_timeout(1000)
    actions=[]
    def scan_click(name):
        # Match exact text of *navigation controls*, not arbitrary page copy.
        script="""(target) => {
          const all=[...document.querySelectorAll('a,button,[role="button"]')];
          const matches=all.filter(e=>(e.textContent||'').replace(/\\s+/g,' ').trim()===target);
          const ranked=matches.map(e=>{
            const id=e.id||'';
            const rects=e.getClientRects();
            const visible=rects.length>0;
            let score=(id.includes('gnbMenu')?50:0)+(id.includes('genMenu')?25:0)+
                      (visible?15:0)+(id.includes('btn_menuLvl')?10:0);
            return {e,score};
          }).sort((a,b)=>b.score-a.score);
          if(!ranked.length)return {clicked:false,count:0};
          const e=ranked[0].e;
          e.click();
          return {clicked:true,count:matches.length,id:(e.id||'').slice(0,100)};
        }"""
        for fr in page.frames:
            try:
                out=fr.evaluate(script,name)
                if out.get("clicked"):
                    logging.info("G2B_OPENING_MENU label=%s target=%s",name,out["id"])
                    return True
            except Exception:pass
        return False

    def open_sitemap():
        selectors=('button:has-text("사이트맵")','a:has-text("사이트맵")',
                   'button[title*="사이트맵"]','a[title*="사이트맵"]',
                   'button[title*="전체메뉴"]','a[title*="전체메뉴"]')
        for fr in page.frames:
            for css in selectors:
                try:
                    loc=fr.locator(css)
                    for i in range(min(loc.count(),3)):
                        if loc.nth(i).is_visible():
                            loc.nth(i).click(timeout=1800)
                            logging.info("G2B_OPENING_SITEMAP_OPENED selector=%s",css)
                            return True
                except Exception:pass
        return False

    for names in steps:
        clicked=False
        # G2B asynchronously initializes WebSquare GNB; wait for its DOM
        # instead of requiring immediate visually accessible labels.
        for attempt in range(18):
            for name in names:
                if scan_click(name):
                    actions.append(name)
                    clicked=True
                    page.wait_for_timeout(900)
                    break
            if clicked:break
            if attempt==7:open_sitemap()
            page.wait_for_timeout(350)
        if not clicked:
            visible=[]
            for fr in page.frames:
                try:
                    visible+=fr.locator('a,button').evaluate_all(
                        """els=>els.filter(e=>/입찰|개찰|낙찰/.test(e.textContent||''))
                        .slice(0,12).map(e=>({text:(e.textContent||'').trim().slice(0,30),
                                             id:(e.id||'').slice(0,75)}))""")
                except Exception:pass
            logging.warning("G2B_OPENING_NAV_DIAG target=%s title=%s body=%s controls=%s",
                            names[0],page.title()[:100],
                            (page.locator("body").inner_text(timeout=1200)[:220]
                             if page.locator("body").count() else ""),
                            json.dumps(visible,ensure_ascii=False)[:1500])
            raise RuntimeError("g2b_opening_menu_not_visible_"+names[0])
    frame=None
    for fr in [page,*page.frames]:
        if fr.locator(GRID_ID).count():
            frame=fr
            break
    if frame is None:
        raise RuntimeError("g2b_opening_result_grid_missing")
    # Click the visible search action nearest the actual grid, not global
    # navigation search. Clicking must not bid or transmit any application.
    try:
        search=frame.get_by_role("button",name="검색",exact=True)
        candidates=[search.nth(i) for i in range(min(8,search.count()))]
        if candidates:
            for loc in reversed(candidates):
                if loc.is_visible(timeout=600):
                    loc.click(timeout=3500)
                    break
    except Exception:
        pass
    page.wait_for_timeout(1900)
    grid=frame.locator(GRID_ID)
    if not grid.is_visible(timeout=4000):
        raise RuntimeError("g2b_opening_result_grid_not_visible")
    text=grid.inner_text(timeout=5000)
    if not text or not G2B_BID_RE.search(text):
        raise RuntimeError("g2b_opening_grid_no_bid_rows")
    results=[]
    seen=set()
    # Read grid rows for public status, notice title and ordering.
    rows=grid.locator("tr, [role=row], .w2grid_dataRow, .w2grid_dataLayer").all()
    for row in rows[:min(len(rows),500)]:
        try: raw=row.inner_text(timeout=600)
        except Exception:continue
        m=G2B_BID_RE.search(raw)
        if not m:continue
        parsed=normalize_id(m.group(0))
        if not parsed or parsed in seen:continue
        seen.add(parsed)
        status=next((v for v in ("개찰완료","재입찰","유찰","개찰진행")
                     if v in raw),"")
        results.append({"bid_no":parsed[0],"bid_ord":parsed[1],
                        "status":status,"listing_text":raw[:1200]})
        if len(results)>=limit:break
    if not results:
        for m in G2B_BID_RE.finditer(text):
            parsed=normalize_id(m.group(0))
            if parsed and parsed not in seen:
                seen.add(parsed)
                results.append({"bid_no":parsed[0],"bid_ord":parsed[1],
                                "status":"","listing_text":""})
                if len(results)>=limit:break
    logging.info("G2B_OPENING_DISCOVERY steps=%s grid_rows=%s bid_ids=%s",
                 actions,len(rows),len(results))
    return results


def _read_json(response):
    if response.status==422:
        try:
            msg=str(response.json().get("ErrorMsg") or "")
            if "개찰결과 데이터가 존재하지 않습니다" in msg:
                raise LookupError("opening_details_not_published")
        except (ValueError,TypeError,AttributeError):
            pass
    if response.status>=400:
        # WorkSquare may answer HTTP 422 when a required runtime/form field
        # is missing. Only log bounded non-secret diagnostic text.
        try:
            info=response.text()[:320]
            logging.warning("G2B_BID_WEB_HTTP_DIAG status=%s body=%s",
                            response.status,re.sub(r"\\s+"," ",info))
        except Exception:pass
        raise RuntimeError("g2b_web_http_"+str(response.status))
    try: result=response.json()
    except Exception:raise RuntimeError("g2b_web_not_json") from None
    if not isinstance(result,dict) or not isinstance(result.get("result"),dict):
        raise RuntimeError("g2b_web_unexpected_response")
    return result["result"]


def fetch_opening(context, bid_no, bid_ord="000", max_pages=2, listing=None):
    """Reissue same-origin read-only JSON request used by official G2B WebSquare.

    Session is established by a real browser page first. The request format
    was observed on the public detail screen, not public-data OpenAPI.
    """
    if not ID_ONLY_RE.fullmatch(bid_no) or not re.fullmatch(r"\d{3}",bid_ord):
        raise ValueError("invalid_bid_identifier")
    first_info={}
    bidders=[]
    total=0
    for page_no in range(1,max(1,min(max_pages,5))+1):
        listing=listing or {}
        payload={"dlSrchOnbsRsltBidInM":{
            "bidPbancNo":bid_no,"bidPbancOrd":bid_ord,
            "bidClsfNo":listing.get("bid_clsfc_no","0"),
            "bidPrgrsOrd":listing.get("bid_progress_ord","000"),
            "prcmBsneSeCd":listing.get("business_code",""),
            "bidPgstCd":listing.get("status") or "개찰완료",
            "bzmnRegNo":"","reOpenPbancYN":"",
            "currentPage":page_no,"recordCountPerPage":"999"}}
        result=None
        # Public WebSquare returns an explicit 'no opening data' response
        # for some procurement classes. Try the site's known goods/service
        # classification codes before treating the detail as unavailable.
        for business_code in dict.fromkeys((listing.get("business_code") or "", "", "01", "03")):
            payload["dlSrchOnbsRsltBidInM"]["prcmBsneSeCd"]=business_code
            response=context.request.post(OPENING_URL,data=json.dumps(payload),
                headers={"Content-Type":"application/json","Menu-Info":MENU_INFO,
                         "User-Agent":"Mozilla/5.0","Referer":BASE},timeout=30000)
            try:
                result=_read_json(response)
                logging.info("G2B_BID_CLASS_MATCH no=%s code=%s",
                             bid_no,business_code or "default")
                break
            except LookupError:
                continue
        if result is None:
            raise LookupError("opening_details_not_published")
        if not first_info:
            first_info={k:result.get(k) or {} for k in ("bidInfo","etcData")}
            relevant=re.compile(r"scsbd|sfbr|winner|wncr|award|sucsf|slctn|pgst|stts",re.I)
            bid_fields=(sorted(k for k in first_info["bidInfo"] if relevant.search(k))
                        if isinstance(first_info["bidInfo"],dict) else [])
            logging.info("G2B_OPENING_DETAIL_STRUCTURE bid=%s response_keys=%s winner_related_fields=%s",
                         bid_no,sorted(result.keys()),bid_fields[:45])
        if page_no==1 and result.get("successBidInfo"):
            example=result["successBidInfo"][0]
            logging.info("G2B_OPENING_BIDDER_FIELDS bid=%s keys=%s winner_related_values=%s",
                         bid_no,sorted(example.keys())[:95],
                         {k:str(v)[:70] for k,v in example.items()
                          if re.search(r"sfbr|slctn|sucsf|winn|scsbd|pgst|stts",k,re.I)})
        records=result.get("successBidInfo") or []
        if not isinstance(records,list):
            raise RuntimeError("g2b_opening_invalid_bidder_structure")
        bidders.extend(x for x in records if isinstance(x,dict))
        if records and page_no==1:
            try:total=int(records[0].get("totCnt") or len(records))
            except (ValueError,TypeError):total=len(records)
        if not records or str(records[-1].get("nextRowYn") or "N").upper()!="Y":break
        time.sleep(.25)
    return {"bid_no":bid_no,"bid_ord":bid_ord,
            "bidders":bidders,"total":total or len(bidders),
            "bid_info":first_info.get("bidInfo") or {},
            "etc_data":first_info.get("etcData") or {}}


def normalize_item(record, category, kind, operation, index):
    """Store bidders by execution key and bidder identity, not search order."""
    if kind not in ("opening","award"):raise ValueError("unsupported_result_kind")
    bid_no=str(record.get("bid_no") or record.get("bidNtceNo") or "")
    if not ID_ONLY_RE.fullmatch(bid_no):return None
    bid_ord=str(record.get("bid_ord") or record.get("bidNtceOrd") or "000")
    clsfc=str(record.get("bidClsfNo") or record.get("bidClsfcNo") or "0")
    rebid=str(record.get("bidPrgrsOrd") or record.get("rbidNo") or "000")
    rank=str(record.get("onbsRnkg") or record.get("bidprcRank") or "").strip()
    bizno=str(record.get("bzmnRegNo") or record.get("bidprcCorpBizno") or "").strip()
    name=str(record.get("grpNm") or record.get("fnlSucsfbdCorpNm") or record.get("company") or "")
    amount=str(record.get("bdngAmt") or record.get("sucsfbidAmt") or record.get("amount") or "")
    rate=str(record.get("bdrt") or record.get("sucsfbidRate") or "")
    identifier="|".join((category,kind,bid_no,bid_ord,clsfc,rebid,
                          rank,bizno,name,str(index) if not (rank or bizno or name) else ""))
    key=hashlib.sha256(identifier.encode()).hexdigest()[:40]
    safe={"bid_no":bid_no,"bid_ord":bid_ord,"bid_clsfc_no":clsfc,"rbid_no":rebid,
          "bidder_rank":rank,"bidder_business_no":bizno,"bidder_name":name,
          "bid_amount":amount,"bid_rate":rate,
          "remarks":str(record.get("etc") or "")[:240],
          "bid_time":str(record.get("slprRcptnDt") or "")[:45],
          "source":"g2b_public_web"}
    return {
        "source":"g2b","category":category,"result_kind":kind,
        "operation":operation,"record_key":key,"bid_ntce_no":bid_no,
        "bid_ntce_ord":bid_ord,"bid_clsfc_no":clsfc,"rbid_no":rebid,
        "title":str(record.get("bid_name") or record.get("bidNtceNm") or "")[:500],
        "agency":str(record.get("agency") or "")[:300],
        "company":name[:300],"amount":amount[:70],
        "participation_count":str(record.get("participant_count") or "")[:40],
        "rate":rate[:45],"rank":rank[:25],
        "result_status":str(record.get("result_status") or "")[:100],
        "raw":safe,
    }


def normalize_public_listing(item):
    """Store an observed grid status, not an invented bidder or winner."""
    no=str(item.get("bid_no") or "")
    ord_no=str(item.get("bid_ord") or "000")
    if not normalize_id(no):return None
    raw_line=str(item.get("listing_text") or "").strip()[:1200]
    status=str(item.get("status") or "")
    marker="|".join(("g2b","opening_status",no,ord_no,
                     str(item.get("bid_clsfc_no") or "0"),
                     str(item.get("bid_progress_ord") or "000")))
    return {
        "source":"g2b","category":"unspecified",
        "result_kind":"opening_status","operation":"g2b_web_opening_grid",
        "record_key":hashlib.sha256(marker.encode()).hexdigest()[:40],
        "bid_ntce_no":no,"bid_ntce_ord":ord_no,
        "bid_clsfc_no":str(item.get("bid_clsfc_no") or ""),
        "rbid_no":str(item.get("bid_progress_ord") or ""),
        "title":str(item.get("title") or "")[:500],
        "agency":str(item.get("agency") or "")[:300],
        "company":"","amount":"",
        "participation_count":"","rate":"","rank":"",
        "result_status":status,
        "raw":{"source":"g2b_public_web_grid","bid_no":no,"bid_ord":ord_no,
               "row_excerpt":raw_line,"status":status,
               "listing":item.get("raw_listing") or {}}
    }


def save_batch(items):
    items=[x for x in items if x]
    if not items:return 0,0
    saved=new=0
    with session() as db:
        for x in items:
            item={**x,"raw":json.dumps(x["raw"],ensure_ascii=False)}
            row=db.execute("""
                INSERT INTO procureflow.bid_results
                (source,category,result_kind,operation,record_key,bid_ntce_no,
                 bid_ntce_ord,bid_clsfc_no,rbid_no,title,agency,company,amount,
                 participation_count,rate,rank,result_status,raw)
                VALUES (%(source)s,%(category)s,%(result_kind)s,%(operation)s,
                        %(record_key)s,%(bid_ntce_no)s,%(bid_ntce_ord)s,
                        %(bid_clsfc_no)s,%(rbid_no)s,%(title)s,%(agency)s,
                        %(company)s,%(amount)s,%(participation_count)s,
                        %(rate)s,%(rank)s,%(result_status)s,%(raw)s::jsonb)
                ON CONFLICT(source,record_key) DO UPDATE SET
                    title=excluded.title,agency=excluded.agency,
                    company=excluded.company,amount=excluded.amount,
                    participation_count=excluded.participation_count,
                    rate=excluded.rate,rank=excluded.rank,
                    result_status=excluded.result_status,
                    raw=excluded.raw,last_seen=now()
                RETURNING (xmax=0) AS inserted
            """,item).fetchone()
            saved+=1;new+=int(row["inserted"])
    return saved,new


def _final_award(bid_info, etc_data):
    """Only recognize explicitly final winner fields in an official web response."""
    for obj in (bid_info,etc_data):
        if not isinstance(obj,dict):continue
        for field in WINNER_KEYS:
            winner=str(obj.get(field) or "").strip()
            if winner and any(s in str(obj) for s in COMPLETE_SIGNALS):
                return winner
    return None


def collect(days=7,pages=1,categories=None,kinds=None,bid_numbers=None):
    """Scrape public opening results; official public-data API not used."""
    limit=max(1,min(60,int(pages)*10))
    max_pages=max(1,min(3,int(pages)))
    result={"source":"g2b","adapter":"g2b_public_web","status":"started",
            "examined":0,"saved":0,"new":0,"pages_checked":0,
            "discovered":0,"errors":[],"bid_details":[],"final_winners":0}
    with sync_playwright() as driver:
        browser=driver.chromium.launch(headless=True,args=[
            "--no-sandbox","--disable-dev-shm-usage"])
        ctx=browser.new_context(locale="ko-KR",timezone_id="Asia/Seoul",
                                viewport={"width":1440,"height":900},
                                user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                            "AppleWebKit/537.36 (KHTML, like Gecko) "
                                            "Chrome/154.0.0.0 Safari/537.36"))
        page=ctx.new_page()
        try:
            response=page.goto(BASE,wait_until="domcontentloaded",timeout=45000)
            if not response or response.status>=400:
                raise RuntimeError("g2b_homepage_unavailable")
            found=[]
            if bid_numbers:
                for raw in bid_numbers[:60]:
                    parsed=normalize_id(raw)
                    if parsed:
                        found.append({"bid_no":parsed[0],"bid_ord":parsed[1],
                                      "status":"","listing_text":""})
            else:
                try:
                    found=fetch_opening_listing(ctx,days=days,pages=pages,
                                                 max_results=limit)
                except Exception as exc:
                    result["errors"].append("discovery:"+type(exc).__name__+
                                            ":"+str(exc)[:85])
                    logging.warning("G2B_BID_DISCOVERY_ERROR reason=%s",str(exc)[:130])
            dedup={}
            for x in found:dedup[(x["bid_no"],x["bid_ord"])]=x
            found=list(dedup.values())[:limit]
            result["discovered"]=len(found)
            # Persist only website-observed grid statuses. Directly supplied
            # sample numbers are NOT evidence of a current opening listing.
            if not bid_numbers and found:
                status_rows=[normalize_public_listing(x) for x in found]
                ls,ln=save_batch(status_rows)
                result["saved"]+=ls
                result["new"]+=ln
                result["listing_rows_saved"]=ls
                logging.info("G2B_OPENING_GRID_SAVED seen=%s saved=%s new=%s",
                             len(found),ls,ln)
            for item in found:
                bid_no,bid_ord=item["bid_no"],item["bid_ord"]
                try:
                    entry=fetch_opening(ctx,bid_no,bid_ord,max_pages,
                                        listing=item)
                    bidders=entry["bidders"]
                    bid_info=entry["bid_info"] if isinstance(entry["bid_info"],dict) else {}
                    etc=entry["etc_data"] if isinstance(entry["etc_data"],dict) else {}
                    result["pages_checked"]+=1
                    result["examined"]+=len(bidders)
                    title=str(bid_info.get("bidPbancNm") or "")[:400]
                    status=item.get("status") or "개찰결과"
                    raw_items=[]
                    for i,row in enumerate(bidders):
                        sample={**row,"bid_no":bid_no,"bid_ord":bid_ord,
                                "bid_name":title,"result_status":status,
                                "participant_count":entry["total"]}
                        raw_items.append(normalize_item(sample,"unspecified","opening",
                                        "g2b_web_opening",i))
                    winner=_final_award(bid_info,etc)
                    if winner:
                        match=next((x for x in raw_items if x and x["company"]==winner),None)
                        if match:
                            award={**match,"result_kind":"award",
                                   "operation":"g2b_web_confirmed_award",
                                   "result_status":"최종낙찰확정"}
                            award["record_key"]=hashlib.sha256(
                                (match["record_key"]+"|award").encode()).hexdigest()[:40]
                            raw_items.append(award)
                            result["final_winners"]+=1
                    saved,new=save_batch(raw_items)
                    result["saved"]+=saved;result["new"]+=new
                    result["bid_details"].append({"bid_no":bid_no,
                        "bid_ord":bid_ord,"bidders":len(bidders),"saved":saved,
                        "new":new,"winner_confirmed":bool(winner)})
                    logging.info("G2B_BID_WEB_RESULT no=%s ord=%s bidders=%s saved=%s new=%s winner=%s",
                                 bid_no,bid_ord,len(bidders),saved,new,bool(winner))
                except LookupError:
                    result.setdefault("unavailable_details",[]).append(bid_no)
                    logging.info("G2B_BID_WEB_UNAVAILABLE no=%s",bid_no)
                except Exception as exc:
                    reason=type(exc).__name__+":"+str(exc)[:100]
                    result["errors"].append("detail_"+bid_no+":"+reason)
                    logging.warning("G2B_BID_WEB_ERROR no=%s reason=%s",bid_no,reason)
                time.sleep(.5)
            result["status"]=("collected" if result["saved"] and not result["errors"]
                              else "partial" if result["saved"]
                              else "error")
            result["published_opening_records"]=sum(1 for x in result["bid_details"]
                                                  if x["bidders"]>0)
        except Exception as exc:
            result["status"]="error"
            result["errors"].append("collector:"+type(exc).__name__+":"+str(exc)[:115])
        finally:
            ctx.close();browser.close()
    return result
