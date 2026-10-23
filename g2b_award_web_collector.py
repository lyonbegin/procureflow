"""Public nuri.g2b.go.kr award-status probe, no data.go.kr credentials.

Separates the '낙찰자선정' final status from '개찰완료' bid ranking.
The actual winner needs explicit selection evidence in a completed award
response; the probe does not assert that any rank-1 bidder is the winner.
"""
import json
import logging
from datetime import datetime,timezone,timedelta
from playwright.sync_api import sync_playwright

BASE="https://nuri.g2b.go.kr/"
LIST_URL=BASE+"nn/nnb/nnba/selectBidPbancList.do"
DETAIL_URL=BASE+"nn/nnb/nnbd/selectOobsRsltDetl.do"
HEADERS={
    "Accept":"application/json",
    "Content-Type":"application/json;charset=UTF-8",
    "Menu-Info":'{"menuNo":"15401","menuCangVal":"NNBA001_01","bsneClsfCd":"%EC%97%85130031","scrnNo":"00777"}',
    "Target-Id":"btnS0001","Usr-Id":"null",
    "Origin":"https://nuri.g2b.go.kr","Referer":BASE
}
FINAL_STATUS="입160010"
SAFE_WINNER_FIELDS=("sfbrSlctnRsltCd","sfbrSlctnRsltCdNm","sfbrSlctnOrd","ibxGrpNm",
                    "ibxOnbsRnkg","ibxBdngAmt","bidUfnsRsnNm","ibxBzmnRegNo")
BID_FIELDS=("bidPbancNo","bidPbancOrd","bidClsfNo","bidPrgrsOrd",
            "bidPbancNm","bidPbancPgstCd","bidPbancPgstCdNm",
            "prcmBsneSeCd","pbancInstUntyGrpNoNm")

def _request(ctx,url,payload,headers):
    response=ctx.request.post(url,data=json.dumps(payload,ensure_ascii=False),
                              headers=headers,timeout=30000)
    if response.status!=200:
        try:
            txt=response.text()[:150]
            logging.warning("G2B_AWARD_WEB_HTTP status=%s msg=%s",response.status,txt)
        except Exception:pass
        raise RuntimeError("award_web_http_"+str(response.status))
    try:data=response.json()
    except ValueError:raise RuntimeError("award_web_non_json") from None
    if not isinstance(data,dict):
        raise RuntimeError("award_web_bad_schema")
    if data.get("ErrorCode") not in (None,0,"0"):
        raise RuntimeError("award_web_result_error_"+str(data.get("ErrorCode"))[:20])
    if not isinstance(data.get("result"),(dict,list)):
        logging.warning("G2B_AWARD_RESPONSE_DIAG keys=%s code=%s msg=%s",
                        sorted(data.keys())[:20],str(data.get("ErrorCode"))[:20],
                        str(data.get("ErrorMsg"))[:130])
        raise RuntimeError("award_web_bad_schema")
    return data["result"]

def probe(days=21,max_list=15,max_details=3):
    now=datetime.now(timezone(timedelta(hours=9)))
    pub_from=(now-timedelta(days=max(7,min(60,int(days)+30)))).strftime("%Y%m%d")
    open_from=(now-timedelta(days=max(1,min(60,int(days))))).strftime("%Y%m%d")
    today=now.strftime("%Y%m%d")
    out={"source":"g2b_nuri_web","status":"started","final_status_filter":FINAL_STATUS,
         "result_count":0,"samples":[],"details":[],"errors":[],"persisted":0}
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True,args=["--no-sandbox","--disable-dev-shm-usage"])
        ctx=browser.new_context(locale="ko-KR",timezone_id="Asia/Seoul")
        page=ctx.new_page()
        try:
            resp=page.goto(BASE,wait_until="domcontentloaded",timeout=35000)
            if not resp or resp.status>=400:raise RuntimeError("nuri_homepage_unavailable")
            request={"bidPbancNo":"","bidPbancOrd":"","bidPbancNm":"","prcmBsneSeCd":"",
                     "bidPbancPgstCd":FINAL_STATUS,"bidMthdCd":"",
                     "pbancPstgStDt":pub_from,"pbancPstgEdDt":today,
                     "onbsPrnmntStDt":open_from,"onbsPrnmntEdDt":today,
                     "recordCountPerPage":"20","rowNum":"","kbrdrId":"",
                     "pbancInstUntyGrpNo":"","pdngYn":"","currentPage":1,
                     "pbancSttsCd":"","pbancKndCd":"","stdCtrtMthdCd":"",
                     "scsbdMthdCd":"","untyGrpNo":"","usrTyCd":"","pbancPstgYn":"Y",
                     "frgnrRprsvYn":""}
            result=_request(ctx,LIST_URL,{"dlParamM":request},HEADERS)
            if isinstance(result,list):
                list_key,items="result",result
            else:
                lists=[(key,value) for key,value in result.items()
                       if isinstance(value,list) and value and isinstance(value[0],dict)]
                if not lists:
                    out["status"]="empty"
                    out["reason"]="no_award_rows_in_date_range"
                    out["response_keys"]=sorted(result.keys())[:30]
                    return out
                list_key,items=max(lists,key=lambda entry:len(entry[1]))
            logging.info("G2B_AWARD_LIST_STRUCTURE result_type=%s selected_key=%s items=%s",
                         type(result).__name__,list_key,len(items))
            if not items:
                out["status"]="empty"
                out["reason"]="no_award_rows_in_date_range"
                return out
            out["response_list_key"]=list_key
            out["result_count"]=len(items)
            out["list_field_names"]=sorted(items[0].keys())[:80]
            candidates=[]
            for row in items[:max_list]:
                no=str(row.get("bidPbancNo") or "")
                if not (no.startswith("R") and len(no)>=12):continue
                sample={k:str(row.get(k) or "")[:130] for k in BID_FIELDS
                        if row.get(k) is not None}
                out["samples"].append(sample)
                # The list can contain other statuses despite filtering.
                if str(row.get("bidPbancPgstCd") or "") in (FINAL_STATUS,"낙찰자선정"):
                    candidates.append(row)
            logging.info("G2B_AWARD_LIST_FOUND total=%s shortlisted=%s samples=%s",
                         len(items),len(candidates),
                         json.dumps(out["samples"][:2],ensure_ascii=False)[:760])
            for row in candidates[:max_details]:
                bid_no=str(row["bidPbancNo"])
                detail_payload={"dlSrchCndtM":{
                    "bidPbancNo":bid_no,
                    "bidPbancOrd":str(row.get("bidPbancOrd") or "000"),
                    "bidClsfNo":str(row.get("bidClsfNo") or "0"),
                    "bidPrgrsOrd":str(row.get("bidPrgrsOrd") or "000"),
                    "bidPbancPgstCd":str(row.get("bidPbancPgstCd") or ""),
                    "kbrdrId":"","etpsUntyGrpNo":"","prcrId":"","prcsRsn":"",
                    "cvlnOrbySeCd":"","cvlnEtpsSrngPgstCd":"","myBdonLisMovYn":""}}
                dh={k:v for k,v in HEADERS.items() if k not in ("Menu-Info","Target-Id")}
                dh["Target-Id"]="btnOnbsRslt"
                try:
                    info=_request(ctx,DETAIL_URL,detail_payload,dh)
                    pmap=info.get("pbancMap") or {}
                    bidders=info.get("oobsRsltList") or []
                    flags={}
                    for bidder in bidders[:50]:
                        raw=str(bidder.get("sfbrSlctnRsltCd") or "")
                        flags[raw]=flags.get(raw,0)+1
                    award={"bid_no":bid_no,"bid_ord":detail_payload["dlSrchCndtM"]["bidPbancOrd"],
                           "field_names":sorted(info.keys())[:30],
                           "bid_status":str(pmap.get("bidPbancPgstCd") or "")[:45],
                           "bidder_count":len(bidders),
                           "selection_codes":flags,
                           "selection_field_names":sorted(k for k in bidders[0]
                                   if "sfbr" in k.lower() or "slctn" in k.lower()) if bidders else []}
                    out["details"].append(award)
                    logging.info("G2B_AWARD_DETAIL_FOUND %s",json.dumps(award,ensure_ascii=False)[:1000])
                except Exception as exc:
                    err=bid_no+":"+type(exc).__name__+":"+str(exc)[:100]
                    out["errors"].append(err)
                    logging.warning("G2B_AWARD_DETAIL_ERROR %s",err)
            out["status"]="probed" if out["details"] else "partial" if out["samples"] else "empty"
        except Exception as exc:
            out["status"]="error"
            out["errors"].append(type(exc).__name__+":"+str(exc)[:130])
        finally:
            ctx.close();browser.close()
    return out
