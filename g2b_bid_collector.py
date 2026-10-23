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


def discover_visible_bids(page, limit=30):
    """Navigate observed public G2B menu and extract IDs ONLY from the results grid."""
    steps=(("입찰",),("입찰개찰/낙찰","입찰개찰·낙찰"),("개찰결과분류조회",))
    page.goto(BASE,wait_until="domcontentloaded",timeout=40000)
    page.wait_for_timeout(1700)
    actions=[]
    for names in steps:
        clicked=False
        for name in names:
            for fr in [page,*page.frames]:
                try:
                    matches=fr.get_by_text(name,exact=True)
                    for idx in range(min(matches.count(),12)):
                        loc=matches.nth(idx)
                        if loc.is_visible(timeout=700):
                            loc.click(timeout=3500)
                            clicked=True
                            actions.append(name)
                            page.wait_for_timeout(650)
                            break
                    if clicked: break
                except Exception:pass
            if clicked: break
        if not clicked:
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
    if response.status>=400:
        raise RuntimeError("g2b_web_http_"+str(response.status))
    try: result=response.json()
    except Exception:raise RuntimeError("g2b_web_not_json") from None
    if not isinstance(result,dict) or not isinstance(result.get("result"),dict):
        raise RuntimeError("g2b_web_unexpected_response")
    return result["result"]


def fetch_opening(context, bid_no, bid_ord="000", max_pages=2):
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
        payload={"dlSrchOnbsRsltBidInM":{
            "bidPbancNo":bid_no,"bidPbancOrd":bid_ord,"bidClsfNo":"0",
            "bidPrgrsOrd":"000","prcmBsneSeCd":"",
            "bidPgstCd":"개찰완료","bzmnRegNo":"","reOpenPbancYN":"",
            "currentPage":page_no,"recordCountPerPage":"100"}}
        response=context.request.post(OPENING_URL,data=json.dumps(payload),
            headers={"Content-Type":"application/json","Menu-Info":MENU_INFO,
                     "Referer":BASE},timeout=30000)
        result=_read_json(response)
        if not first_info:
            first_info={k:result.get(k) or {} for k in ("bidInfo","etcData")}
            logging.info("G2B_OPENING_DETAIL_STRUCTURE bid=%s keys=%s bid_info_fields=%s etc_fields=%s",
                         bid_no,sorted(result.keys()),
                         sorted(first_info["bidInfo"].keys()) if isinstance(first_info["bidInfo"],dict) else [],
                         sorted(first_info["etcData"].keys()) if isinstance(first_info["etcData"],dict) else [])
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
                                viewport={"width":1440,"height":900})
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
                    found=discover_visible_bids(page,limit)
                except Exception as exc:
                    result["errors"].append("discovery:"+type(exc).__name__+
                                            ":"+str(exc)[:85])
                    logging.warning("G2B_BID_DISCOVERY_ERROR reason=%s",str(exc)[:130])
            dedup={}
            for x in found:dedup[(x["bid_no"],x["bid_ord"])]=x
            found=list(dedup.values())[:limit]
            result["discovered"]=len(found)
            for item in found:
                bid_no,bid_ord=item["bid_no"],item["bid_ord"]
                try:
                    entry=fetch_opening(ctx,bid_no,bid_ord,max_pages)
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
                except Exception as exc:
                    reason=type(exc).__name__+":"+str(exc)[:100]
                    result["errors"].append("detail_"+bid_no+":"+reason)
                    logging.warning("G2B_BID_WEB_ERROR no=%s reason=%s",bid_no,reason)
                time.sleep(.5)
            result["status"]=("collected" if result["saved"] and not result["errors"]
                              else "partial" if result["saved"]
                              else "error")
        except Exception as exc:
            result["status"]="error"
            result["errors"].append("collector:"+type(exc).__name__+":"+str(exc)[:115])
        finally:
            ctx.close();browser.close()
    return result
