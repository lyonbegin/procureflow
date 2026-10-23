"""Confirmed G2B final-winner web scraper (NO data.go.kr API key).

A bidder becomes a final winner ONLY if the public Nuri detail simultaneously
has bidPbancPgstCd=입160010 and exactly one oobsRsltList record whose
sfbrSlctnRsltCd equals '낙찰'. Rank 1 by itself is never an award.
"""
from datetime import datetime,timedelta,timezone
from html import unescape
import hashlib
import json
import logging
import time

from playwright.sync_api import sync_playwright
from g2b_award_web_collector import BASE,LIST_URL,DETAIL_URL,HEADERS,FINAL_STATUS,_request
from g2b_bid_collector import save_batch
from g2b_date_windows import window

CATEGORY_BY_CODE={"조070001":"goods","조070002":"service"}
DETAIL_HEADERS={k:v for k,v in HEADERS.items() if k not in ("Menu-Info","Target-Id")}
DETAIL_HEADERS["Target-Id"]="btnOnbsRslt"


def normalized_confirmed_award(listing,detail):
    """Normalize only a public, explicitly selected winner for this execution."""
    pbanc=detail.get("pbancMap") or {}
    if str(pbanc.get("bidPbancPgstCd") or "").strip()!=FINAL_STATUS:
        return None
    bidders=detail.get("oobsRsltList") or []
    if not isinstance(bidders,list):raise RuntimeError("award_bidder_list_invalid")
    winners=[b for b in bidders if isinstance(b,dict) and
             str(b.get("sfbrSlctnRsltCd") or "").strip()=="낙찰"]
    if len(winners)!=1:
        return None
    row=winners[0]
    company=unescape(str(row.get("ibxGrpNm") or "")).strip()
    if not company:return None
    bid_no=str(pbanc.get("bidPbancNo") or listing.get("bidPbancNo") or "")
    bid_ord=str(pbanc.get("bidPbancOrd") or listing.get("bidPbancOrd") or "000")
    clsfc=str(pbanc.get("bidClsfNo") or listing.get("bidClsfNo") or "0")
    progress=str(pbanc.get("bidPrgrsOrd") or listing.get("bidPrgrsOrd") or "000")
    if not (bid_no.startswith("R") and len(bid_no)>=12):return None
    # Composite execution identity rather than bidder name: if amended final
    # results later select another company, the latest verified result replaces it.
    key=hashlib.sha256(("g2b|final-award|"+bid_no+"|"+bid_ord+"|"+
                        clsfc+"|"+progress).encode()).hexdigest()[:40]
    amount=str(row.get("ibxBdngAmt") or "").strip()
    rank=str(row.get("ibxOnbsRnkg") or "").strip()
    raw={
        "evidence":"nuri_public_bid_status_and_explicit_winner_selection",
        "award_progress_code":FINAL_STATUS,"selection_result":"낙찰",
        "winner_company":company,
        "winner_bid_amount":amount,
        "bid_no":bid_no,"bid_ord":bid_ord,"bid_clsfc_no":clsfc,
        "bid_progress_ord":progress,
        "winner_rank":rank,
        "winner_bizno":str(row.get("ibxBzmnRegNo") or "")[:20],
        "website":"nuri.g2b.go.kr"
    }
    business=str(pbanc.get("prcmBsneSeCd") or listing.get("prcmBsneSeCd") or "")
    return {
        "source":"g2b","category":CATEGORY_BY_CODE.get(business,"unspecified"),
        "result_kind":"award","operation":"nuri_final_winner_web",
        "record_key":key,"bid_ntce_no":bid_no,
        "bid_ntce_ord":bid_ord,"bid_clsfc_no":clsfc,"rbid_no":progress,
        "title":unescape(str(pbanc.get("bidPbancNm") or listing.get("bidPbancNm") or ""))[:500],
        "agency":unescape(str(pbanc.get("pbancInstUntyGrpNoNm") or
                            listing.get("pbancInstUntyGrpNoNm") or ""))[:300],
        "company":company[:300],"amount":amount[:70],
        "participation_count":str(len(bidders)),
        "rate":str(row.get("bdrt") or row.get("ibxBdrt") or "")[:45],
        "rank":rank[:25],"result_status":"최종낙찰확정",
        "raw":raw
    }


def collect(days=21,pages=2,limit=30,start_date=None,end_date=None,page_start=1):
    """Read-only search of officially selected winners, bounded by date/pages."""
    days=max(1,min(int(days),60))
    pages=max(1,min(int(pages),5))
    limit=max(1,min(int(limit),100))
    first_day,last_day=window(days,start_date,end_date,max_span_days=60)
    pub_from=(first_day-timedelta(days=30)).strftime("%Y%m%d")
    open_from=first_day.strftime("%Y%m%d")
    today=last_day.strftime("%Y%m%d")
    page_start=max(1,min(int(page_start),10000))
    out={"source":"g2b","adapter":"g2b_nuri_web_final_awards",
         "status":"started","discovered":0,"checked":0,"confirmed":0,
         "saved":0,"new":0,"errors":[],"not_final":[],"pages":[],
         "window_start":first_day.isoformat(),"window_end":last_day.isoformat(),
         "page_start":page_start,"has_more":False,"last_page":page_start}
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True,args=["--no-sandbox","--disable-dev-shm-usage"])
        ctx=browser.new_context(locale="ko-KR",timezone_id="Asia/Seoul")
        page=ctx.new_page()
        try:
            r=page.goto(BASE,wait_until="domcontentloaded",timeout=35000)
            if not r or r.status>=400:raise RuntimeError("nuri_web_unavailable")
            params={"bidPbancNo":"","bidPbancOrd":"","bidPbancNm":"",
                "prcmBsneSeCd":"","bidPbancPgstCd":FINAL_STATUS,
                "bidMthdCd":"","pbancPstgStDt":pub_from,"pbancPstgEdDt":today,
                "onbsPrnmntStDt":open_from,"onbsPrnmntEdDt":today,
                "recordCountPerPage":"20","rowNum":"","kbrdrId":"",
                "pbancInstUntyGrpNo":"","pdngYn":"","currentPage":1,
                "pbancSttsCd":"","pbancKndCd":"","stdCtrtMthdCd":"",
                "scsbdMthdCd":"","untyGrpNo":"","usrTyCd":"",
                "pbancPstgYn":"Y","frgnrRprsvYn":""}
            seen=set()
            for page_no in range(page_start,page_start+pages):
                params["currentPage"]=page_no
                response=_request(ctx,LIST_URL,{"dlParamM":params},HEADERS)
                if isinstance(response,dict):
                    candidates=next((v for v in response.values()
                         if isinstance(v,list)),[])
                else:
                    candidates=response
                if not isinstance(candidates,list):
                    raise RuntimeError("invalid_award_list")
                out["pages"].append({"page":page_no,"returned":len(candidates)})
                out["last_page"]=page_no
                out["has_more"]=len(candidates)>=20
                for record in candidates:
                    if len(seen)>=limit:break
                    if not isinstance(record,dict):continue
                    if str(record.get("bidPbancPgstCd") or "") not in (FINAL_STATUS,"낙찰자선정"):
                        continue
                    bid_no=str(record.get("bidPbancNo") or "")
                    bid_ord=str(record.get("bidPbancOrd") or "000")
                    clsfc=str(record.get("bidClsfNo") or "0")
                    progress=str(record.get("bidPrgrsOrd") or "000")
                    key=(bid_no,bid_ord,clsfc,progress)
                    if not bid_no or key in seen:continue
                    seen.add(key)
                    out["discovered"]+=1
                    detail_request={"dlSrchCndtM":{
                        "bidPbancNo":bid_no,"bidPbancOrd":bid_ord,
                        "bidClsfNo":clsfc,"bidPrgrsOrd":progress,
                        "bidPbancPgstCd":str(record.get("bidPbancPgstCd") or ""),
                        "kbrdrId":"","etpsUntyGrpNo":"","prcrId":"","prcsRsn":"",
                        "cvlnOrbySeCd":"","cvlnEtpsSrngPgstCd":"","myBdonLisMovYn":""}}
                    try:
                        detail=_request(ctx,DETAIL_URL,detail_request,DETAIL_HEADERS)
                        if not isinstance(detail,dict):
                            raise RuntimeError("award_detail_not_object")
                        out["checked"]+=1
                        item=normalized_confirmed_award(record,detail)
                        if not item:
                            out["not_final"].append(bid_no)
                            continue
                        saved,new=save_batch([item])
                        out["saved"]+=saved
                        out["new"]+=new
                        out["confirmed"]+=1
                        logging.info("G2B_FINAL_AWARD_SAVED bid=%s ord=%s name=%s amount=%s new=%s",
                            bid_no,bid_ord,item["company"][:90],item["amount"],new)
                    except Exception as ex:
                        msg=bid_no+":"+type(ex).__name__+":"+str(ex)[:90]
                        out["errors"].append(msg)
                        logging.warning("G2B_FINAL_AWARD_ERROR %s",msg)
                    time.sleep(.18)
                logging.info("G2B_AWARD_PAGE page=%s items=%s checked=%s confirmed=%s",
                    page_no,len(candidates),out["checked"],out["confirmed"])
                if len(candidates)<20 or len(seen)>=limit:break
            out["status"]=("collected" if out["confirmed"] and not out["errors"]
                           else "partial" if out["confirmed"] else
                           "error" if out["errors"] else "empty")
        except Exception as e:
            out["status"]="error"
            out["errors"].append(type(e).__name__+":"+str(e)[:160])
        finally:
            ctx.close()
            browser.close()
    return out
