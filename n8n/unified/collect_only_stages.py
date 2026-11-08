"""Collection-only procurement stages N03–N08.

Never adjudicate bidder eligibility, competitor likelihood, cost suitability, bid
price or award probability before N09. Missing sources are explicit collection
gaps, NOT business decision blocks. No historical database reads.
"""
from __future__ import annotations
from datetime import date,timedelta
from hashlib import sha256
from html import unescape
import json,re
from urllib.error import HTTPError

G2B="https://www.g2b.go.kr"
BID_LIST=G2B+"/pn/pnp/pnpe/BidPbac/selectBidPbacScrollTypeList.do"
OPENING_LIST=G2B+"/pb/pbo/pboc/OnbsRslt/selectOnbsRsltClsfList.do"
OPENING_DETAIL=G2B+"/pb/pbo/pboc/OnbsRslt/selectOnbsRsltSbidGods.do"
DETAIL_HEADERS={"Menu-Info":'{"menuNo":"15620","scrnNo":"08542"}',
                "Referer":G2B+"/","User-Agent":"Mozilla/5.0"}
BID_HEADERS={
    "Menu-Info":'{"menuNo":"01175","menuCangVal":"PNPE001_01","bsneClsfCd":"%EC%97%85130026","scrnNo":"00941"}',
    "submissionid":"mf_wfm_container_tacBidPbancLst_contents_tab2_body_sbmPbancBidPbancLst",
    "Target-Id":"btnS0004","Usr-Id":"null","Origin":G2B,"Referer":G2B+"/",
}
OPEN_HEADERS={
    "Menu-Info":'{"menuNo":"01522","menuCangVal":"PBOC006_01","bsneClsfCd":"%EC%97%85130028","scrnNo":"02117"}',
    "submissionid":"mf_wfm_container_selectOnbsRsltClsfList",
    "Usr-Id":"null","Referer":G2B+"/",
}
CLASS_CODES=("dtlsPrnmNo","dtlsPrnmCd","prdlstDetlNo","prdlstDetlCd")
CLASS8_CODES=("prdlstClsfNo","prdlstClsfCd","prdctClsfNo","prodClsfNo")

PUBLIC_FIELDS=(
    "bidPbancUntyNo","bidPbancNo","bidPbancUntyOrd","bidPbancOrd",
    "bidPbancNm","pbancPstgDt","dmstNm","oderInstUntyGrpNm",
    "oderInstUntyGrpNo","prcmBsneSeCd","prcmBsneSeCdNm",
    "dtlsPrnmNo","dtlsPrnmNm","prdlstDetlNo","prdlstDetlNm",
    "prdlstClsfNo","prdlstClsfCd","prdctClsfNo","prodClsfNo",
    "alotBgtAmt","bidPrspPrce","bidDateType","pbancSttsNm",
    "qnty","quantity","bidQntty","bidQty","prdlstQty","itemQty","unit","unitNm",
    "ctrtTyCd","bidCtrtMthdCd","scsbdMthdCd","odnLmtLgdngCd",
    "fromBidDt","toBidDt","bdgtAmt","baseAmt","bidClseDt",
)
OPEN_FIELDS=("bidPbancNo","bidPbancOrd","bidPbancNm",
             "onbsYmd","onbsDt","onbsPrnmntDt","prcmBsneSeCd",
             "scsbdMthdCd","scsbdMthdNm","pbancSttsNm",
             "scsbdAmt","scsbdPrce","scsbidAmt","scsbidRate",
             "bidClsfNo","bidPrgrsOrd","bidPgstCd","dmstNm","demaInstNm",
             "prdlstClsfNo","dtlsPrnmNo","qnty","quantity","bidQntty",
             "bidQty","prdlstQty","itemQty","unit","unitNm","prdlstNm")
MAX_HISTORY_ROWS=400
MAX_HISTORY_PAGES_PER_YEAR=30
MAX_OPENING_LOOKUPS=50
MAX_OPENING_PAGES_PER_NOTICE=5
MAX_BIDDER_PAGES_PER_OPENING=5
MAX_BIDDER_ROWS_PER_NOTICE=1000
HISTORY_INITIAL_YEARS=3
HISTORY_MAX_YEARS=10
HISTORY_TARGET_RECORDS=50

def _scalar(x,limit=240):
    if x is None:return None
    if not isinstance(x,(str,int,float,bool)):return None
    return unescape(str(x)).strip()[:limit]
def _pick(item,keys):
    return {k:_scalar(item[k]) for k in keys if item.get(k) not in ("",None) and _scalar(item[k]) is not None}
def _classification(item):
    seen=[]
    for k in CLASS_CODES:
        v=_scalar(item.get(k))
        if v and re.fullmatch(r"\d{10}",v):
            seen.append((k,v))
    unique={v for _,v in seen}
    if len(unique)!=1:return None,None
    return next(iter(unique)),next(k for k,v in seen if v in unique)
def _classification8(item):
    """Extract an 8-digit official item classification, never a business type code."""
    if not isinstance(item,dict):return None,None
    found=[(k,_scalar(item.get(k))) for k in CLASS8_CODES
           if _scalar(item.get(k)) and re.fullmatch(r"\d{8}",_scalar(item.get(k)))]
    detail10,source=_classification(item)
    if detail10:found.append((source+":prefix8",detail10[:8]))
    if len({v for _,v in found})!=1:return None,None
    return found[0][1],found[0][0]

def _ident(item):
    bid=_scalar(item.get("bidPbancUntyNo") or item.get("bidPbancNo"))
    order=_scalar(item.get("bidPbancUntyOrd") or item.get("bidPbancOrd") or "000")
    return bid,order.zfill(3) if order and order.isdigit() else order
def _valid_notice(notice):
    if not isinstance(notice,dict):raise ValueError("COLLECTION_SELECTED_NOTICE_REQUIRED")
    bid=str(notice.get("bid_no") or "")
    order=str(notice.get("bid_ord") or "000")
    if not re.fullmatch(r"(?:R\d{2}BK\d{8}|\d{11})",bid) or not re.fullmatch(r"\d{3}",order):
        raise ValueError("COLLECTION_SELECTED_NOTICE_ID_INVALID")
    return bid,order
def _year_back(day,years=10):
    try:return day.replace(year=day.year-years)
    except ValueError:return day.replace(year=day.year-years,day=28)

def _periods(day,years=HISTORY_MAX_YEARS):
    """Exactly 'years' contiguous nonoverlapping annual windows, oldest first."""
    if not isinstance(years,int) or not 1<=years<=HISTORY_MAX_YEARS:
        raise ValueError("INVALID_HISTORY_YEARS")
    for age in range(years,0,-1):
        start=_year_back(day,age)
        end=day if age==1 else _year_back(day,age-1)-timedelta(days=1)
        yield start.strftime("%Y%m%d"),end.strftime("%Y%m%d")
def _g2b_rows(opener,post,live,start,end,bid="",code="",page=1):
    payload=live._g2b_bid_list_payload(start,end,bid,page)
    payload["dlBidPbancLstM"]["dtlsPrnmNo"]=code
    rows=post(opener,BID_LIST,payload,BID_HEADERS)
    if not isinstance(rows,list) or len(rows)>20 or any(not isinstance(r,dict) for r in rows):
        raise ValueError("COLLECTION_OFFICIAL_BID_RESPONSE_SCHEMA_INVALID")
    return rows

def n03_metadata(opener,notice,post,live,today):
    """Collect selected notice metadata; item classification is optional evidence."""
    bid,order=_valid_notice(notice)
    # A single 10-year first page cannot prove that a specific notice is absent.
    # Search the most recent windows first, preserving exact bid number/order.
    windows=list(reversed(list(_periods(today))))
    checked=[]
    matching=[]
    for start,end in windows:
        for page in range(1,MAX_HISTORY_PAGES_PER_YEAR+1):
            response=_g2b_rows(opener,post,live,start,end,bid=bid,page=page)
            checked.append({"start":start,"end":end,"page":page,"rows":len(response)})
            matching.extend(row for row in response if _ident(row)==(bid,order))
            if matching or len(response)<20:
                break
        if matching:
            break
    # Multiple returned rows may represent duplicate exact notice records.
    # Reject incompatible values rather than silently selecting a row.
    distinct={json.dumps(row,sort_keys=True,ensure_ascii=False) for row in matching}
    if len(distinct)>1:raise ValueError("N03_OFFICIAL_SELECTED_NOTICE_AMBIGUOUS")
    found=matching[0] if matching else None
    fields=_pick(found,PUBLIC_FIELDS) if found else {}
    code,source_field=_classification(found) if found else (None,None)
    code8,source8=_classification8(found) if found else (None,None)
    gaps=[]
    if not found:gaps.append("selected_notice_not_returned_by_official_exact_number_query")
    if not code8:gaps.append("official_8_digit_item_class_not_in_listing")
    if not fields.get("pbancPstgDt"):gaps.append("official_publication_date_not_in_selected_record")
    return ("verified" if found and fields else "partial"),{
       "source":BID_LIST,"retrieval_mode":"selected_notice_exact_number",
       "selected_bid_no":bid,"selected_bid_ord":order,
       "query_windows_checked":checked,
       "query_window":{"start":checked[-1]["start"],"end":checked[-1]["end"]} if checked else None,
       "official_selected_record_found":bool(found),
       "official_fields":fields,
       "class8":code8,"class8_source_field":source8,
       "class8_verified":bool(code8),
       "detail10":code,"detail10_source_field":source_field,
       "detail10_verified":bool(code),
       "source_record_sha256":sha256(json.dumps(found or {},sort_keys=True,ensure_ascii=False).encode()).hexdigest(),
       "gaps":gaps,"business_evaluation_performed":False}

def _history_query(notice,n03):
    """Choose official item code first; otherwise a bounded source-grounded search.
    Business category ('prcmBsneSeCd') is NOT an eight-digit item classification.
    """
    metadata=(n03 or {}).get("official_fields") or {}
    code8=(n03 or {}).get("class8") if (n03 or {}).get("class8_verified") else None
    if code8 and re.fullmatch(r"\d{8}",str(code8)):
        return "official_item8",{"prdlstClsfNo":code8},code8
    detail=(n03 or {}).get("detail10") if (n03 or {}).get("detail10_verified") else None
    if detail and re.fullmatch(r"\d{10}",str(detail)):
        return "official_item10",{"dtlsPrnmNo":detail},detail
    title=str(metadata.get("bidPbancNm") or notice.get("title") or "")
    # Prefer a non-generic word already present in the official title.
    # Place names/numbered project prefixes frequently match only the current
    # announcement, while agency-name form filters may be ignored by G2B.
    tokens=[x for x in re.findall(r"[가-힣A-Za-z]{4,}",title)
            if x not in {"입찰공고","재공고","정정공고","긴급공고","용역공고","제안요청서"}]
    if tokens:
        token=max(tokens,key=len)
        # A unique project phrase can return just the selected bid. The last
        # four chars are still a literal substring of the official title,
        # and every official response is separately matched and provenance-tagged.
        term=token[-3:] if len(token)>5 else token
        return "official_title_keyword",{"bidPbancNm":term},term
    agency=str(metadata.get("dmstNm") or notice.get("agency") or "").strip()
    if len(agency)>=3:return "official_agency_name",{"dmstNm":agency},agency
    return "no_supported_query",{},None


def n04_history(opener,notice,n03,post,live,today,max_pages=MAX_HISTORY_PAGES_PER_YEAR,
                initial_years=HISTORY_INITIAL_YEARS,target_records=HISTORY_TARGET_RECORDS,
                max_years=HISTORY_MAX_YEARS):
    """Search recent 3 years first; expand one year at a time until 50 genuine
    distinct source records or 10 years. Source match != business evaluation.
    """
    bid,order=_valid_notice(notice)
    if not (1<=initial_years<=max_years<=HISTORY_MAX_YEARS):
        raise ValueError("INVALID_HISTORICAL_WINDOW_POLICY")
    if not (1<=target_records<=MAX_HISTORY_ROWS):
        raise ValueError("INVALID_HISTORICAL_TARGET")
    if not (1<=max_pages<=100):
        raise ValueError("INVALID_HISTORICAL_PAGE_LIMIT")
    mode,filter_fields,query=_history_query(notice,n03)
    # Most recent annual window first: [2025-11-08,2026-11-08], then older.
    periods=list(reversed(list(_periods(today,years=max_years))))
    value={
        "source":BID_LIST,"selected_bid_no":bid,"selected_bid_ord":order,
        "query_mode":mode,"query_value":query,
        "requested_detail10":(n03 or {}).get("detail10"),
        "requested_class8":(n03 or {}).get("class8"),
        "initial_years":initial_years,"max_years":max_years,
        "target_records":target_records,"periods_requested":initial_years,
        "periods_available":len(periods),"periods_checked":[],
        "years_expanded":initial_years,"records":[],
        "unverified_classification_count":0,"total_responses":0,
        "candidate_record_count":0,"target_reached":False,
        "all_history_complete":False,"business_evaluation_performed":False,
        "gaps":[]
    }
    if mode=="no_supported_query":
        value["gaps"].append("no_official_item_code_title_or_agency_for_history")
        return "partial",value
    records={}
    truncated=False
    for index,(date_start,date_end) in enumerate(periods):
        # Finish the initial three yearly windows before applying target policy.
        if index>=initial_years and len(records)>=target_records:
            break
        # Extend exactly one further year when the cumulative total is below 50.
        if index>=initial_years:
            value["years_expanded"]=index+1
        segment={"from":date_start,"to":date_end,"pages_checked":0,
                 "returned_rows":0,"candidate_rows":0,"new_unique_records":0,
                 "cumulative_records":len(records),"complete":False}
        try:
            for page in range(1,max_pages+1):
                payload=live._g2b_bid_list_payload(date_start,date_end,"",page)
                payload["dlBidPbancLstM"].update(filter_fields)
                rows=post(opener,BID_LIST,payload,BID_HEADERS)
                if not isinstance(rows,list) or len(rows)>20 or any(not isinstance(x,dict) for x in rows):
                    raise ValueError("COLLECTION_OFFICIAL_BID_RESPONSE_SCHEMA_INVALID")
                segment["pages_checked"]+=1
                segment["returned_rows"]+=len(rows)
                value["total_responses"]+=len(rows)
                for row in rows:
                    actual8,field8=_classification8(row)
                    actual10,field10=_classification(row)
                    rowtitle=str(_scalar(row.get("bidPbancNm")) or "")
                    agency=str(_scalar(row.get("dmstNm")) or "")
                    if mode=="official_item8":
                        matched=actual8==query
                    elif mode=="official_item10":
                        matched=actual10==query
                    elif mode=="official_title_keyword":
                        matched=query.replace(" ","") in re.sub(r"\s+","",rowtitle)
                    else:
                        matched=(agency==query)
                    if not matched:
                        value["unverified_classification_count"]+=1
                        continue
                    number,ordr=_ident(row)
                    if not number or not re.fullmatch(r"(?:R\d{2}BK\d{8}|\d{11})",number):
                        continue
                    key=(number,ordr)
                    if key==(bid,order):
                        continue  # Never count selected notice as past evidence.
                    segment["candidate_rows"]+=1
                    if key not in records:
                        if len(records)<target_records:
                            records[key]={
                                "bid_no":number,"bid_ord":ordr,"detail10":actual10,
                                "detail10_source_field":field10,"class8":actual8,
                                "class8_source_field":field8,"source":BID_LIST,
                                "match_basis":mode,"official_classification_confirmed":
                                    mode in ("official_item8","official_item10"),
                                "query_period":{"from":date_start,"to":date_end},
                                "official_fields":_pick(row,PUBLIC_FIELDS)}
                            segment["new_unique_records"]+=1
                        else:
                            truncated=True  # Target achieved; not claiming exhaustive history.
                if len(rows)<20:
                    segment["complete"]=True
                    break
            if not segment["complete"]:
                value["gaps"].append("history_period_page_limit:"+date_start+"-"+date_end)
        except Exception as exc:
            segment["error"]=type(exc).__name__+":"+str(exc)[:100]
            value["gaps"].append("history_period_lookup_failed:"+date_start+"-"+date_end)
        segment["cumulative_records"]=len(records)
        value["periods_checked"].append(segment)
    if value["unverified_classification_count"]:
        value["gaps"].append("source_rows_not_matching_query_predicate")
    if truncated:
        value["gaps"].append("additional_history_rows_excluded_after_target_50")
    if mode not in ("official_item8","official_item10"):
        value["gaps"].append("historical_candidates_unclassified_final_ai_review")
    value["records"]=list(records.values())
    value["verified_record_count"]=len(records) if mode in ("official_item8","official_item10") else 0
    value["candidate_record_count"]=len(records)
    value["collected_record_count"]=len(records)
    value["target_reached"]=len(records)>=target_records
    value["periods_requested"]=len(value["periods_checked"])
    value["years_searched"]=len(value["periods_checked"])
    value["records_truncated"]=truncated
    if not value["target_reached"]:
        value["gaps"].append("historical_target_not_reached:"+str(len(records))+"/"+str(target_records))
        if value["years_searched"]>=max_years:
            value["gaps"].append("historical_max_years_exhausted")
    # Collection of 50 candidates is not the same as exhaustive 10-year coverage.
    value["all_history_complete"]=(
        value["target_reached"] and all(x["complete"] for x in value["periods_checked"])
        and not any(g.startswith("history_period_") for g in value["gaps"]))
    # The collection-stage success criterion is 50 source-backed DISTINCT
    # notices, not AI relevance classification or an exhaustive archive scan.
    # The source match basis and missing classification remain explicit.
    value["collection_target_complete"]=bool(
        value["target_reached"]
        and not any(g.startswith("history_period_lookup_failed:") for g in value["gaps"]))
    # A 50-record collection target can succeed without claiming every page
    # of the last three years was scanned or the class was AI-confirmed.
    return ("verified" if value["collection_target_complete"] else "partial"),value

def _n05_error(exc):
    """Stable, non-sensitive error reason (never serialize response body)."""
    if isinstance(exc,HTTPError):
        code=int(getattr(exc,"code",0) or 0)
        if code==422:
            # Only an explicit official "no opening data" message establishes
            # that status. A bare 422 could equally be a malformed WebSquare
            # payload, so it remains an unresolved source error.
            try:
                raw=exc.read(4096)
                body=json.loads(raw.decode("utf-8","replace"))
                message=str(body.get("ErrorMsg") or body.get("errorMsg") or "")
                if "개찰결과 데이터가 존재하지 않습니다" in message:
                    return "official_422_no_published_opening_detail"
            except (ValueError,TypeError,AttributeError,UnicodeError):
                pass
            return "official_http_422_unclassified"
        return "official_http_"+str(code)
    return type(exc).__name__+":"+str(exc)[:110]


def _n05_opening_list(opener,post,bid,order,date_from,date_to,max_pages=MAX_OPENING_PAGES_PER_NOTICE):
    """Search official G2B opening-list pages and trust only exact bid+order.
    Merely getting HTTP 200 or unrelated rows is NOT evidence for this tender.
    """
    matched=[]
    seen=set()
    count_rows=0
    pages=0
    complete=False
    ignored_filter_rows=0
    for page in range(1,max_pages+1):
        first=1+(page-1)*10
        query={"dlSrchOnbsRsltClsfListInM":{
            "bidPbancNo":bid,"bidPbancOrd":order,"bidPbancNm":"",
            "onbsYmdStr":date_from,"onbsYmdEnd":date_to,
            "prcmBsneSeCd":"0000 조070001 조070002 조070003 조070004 조070005",
            "frcpYn":"Y","rsrvYn":"Y","laseYn":"Y","chkBsneAllYn":"Y",
            "firstIndex":first,"lastIndex":first+9,
            "inqEnd":"","stepBarYn":"","pbancKndCd":"공440002"}}
        response=post(opener,OPENING_LIST,query,OPEN_HEADERS)
        rows=response.get("onbsRsltClsfList") if isinstance(response,dict) else None
        if not isinstance(rows,list):
            raise ValueError("N05_OFFICIAL_OPENING_LIST_SCHEMA_INVALID")
        if len(rows)>10:
            raise ValueError("N05_OFFICIAL_OPENING_LIST_PAGE_SIZE_INVALID")
        pages+=1
        count_rows+=len(rows)
        for row in rows:
            if not isinstance(row,dict):
                raise ValueError("N05_OFFICIAL_OPENING_LIST_ROW_INVALID")
            row_no=_scalar(row.get("bidPbancNo"))
            row_ord=_scalar(row.get("bidPbancOrd") or "000")
            if row_ord and row_ord.isdigit():row_ord=row_ord.zfill(3)
            if (row_no,row_ord)!=(bid,order):
                ignored_filter_rows+=1
                continue
            key=(row_no,row_ord,_scalar(row.get("bidClsfNo") or "0"),
                 _scalar(row.get("bidPrgrsOrd") or "000"))
            if key not in seen:
                seen.add(key)
                matched.append(row)
        if len(rows)<10:
            complete=True
            break
    return {"matched":matched,"pages":pages,"response_rows":count_rows,
            "ignored_filter_rows":ignored_filter_rows,"pages_complete":complete}


def _n05_bidder_details(opener,post,bid,order,source):
    """Only request official bid details using class/progress/status from an
    exact matched opening-list row. Never synthesize '개찰완료' or class '0'.
    """
    required=("bidClsfNo","bidPrgrsOrd","prcmBsneSeCd","bidPgstCd")
    missing=[k for k in required if source.get(k) in (None,"")]
    if missing:
        return None,["official_opening_detail_keys_missing:"+",".join(missing)]
    errors=[]
    all_rows=[]
    sha=[]
    info={}
    completed=False
    seen=set()
    for page in range(1,MAX_BIDDER_PAGES_PER_OPENING+1):
        query={"dlSrchOnbsRsltBidInM":{
            "bidPbancNo":bid,"bidPbancOrd":order,
            "bidClsfNo":str(source["bidClsfNo"]),
            "bidPrgrsOrd":str(source["bidPrgrsOrd"]),
            "prcmBsneSeCd":str(source["prcmBsneSeCd"]),
            "bidPgstCd":str(source["bidPgstCd"]),
            "bzmnRegNo":"","reOpenPbancYN":"",
            "currentPage":page,"recordCountPerPage":"999"}}
        try:
            result=post(opener,OPENING_DETAIL,query,DETAIL_HEADERS)
        except Exception as exc:
            errors.append(_n05_error(exc))
            break
        if not isinstance(result,dict):
            errors.append("N05_OFFICIAL_BID_DETAIL_SCHEMA_INVALID")
            break
        rows=result.get("successBidInfo")
        if not isinstance(rows,list):
            errors.append("N05_OFFICIAL_BID_DETAIL_ROWS_INVALID")
            break
        sha.append(sha256(json.dumps(result,ensure_ascii=False,sort_keys=True,
                                    separators=(",",":")).encode()).hexdigest())
        if page==1:
            bid_info=result.get("bidInfo") or {}
            if isinstance(bid_info,dict):
                info=_pick(bid_info,("fnlSucsfbdCorpNm","fnlBidWinnrNm",
                                     "scsbdAmt","scsbdPrce"))
        if not rows:
            completed=True
            break
        allowed=("onbsRnkg","bidprcRank","grpNm","fnlSucsfbdCorpNm",
                 "bdngAmt","sucsfbidAmt","bdrt","sucsfbidRate",
                 "bzmnRegNo","bidPgstCd","fnlBidWinnrNm","bidWinnrNm",
                 "nextRowYn","totCnt",
                 "qnty","quantity","bidQntty","bidQty","prdlstQty",
                 "itemQty","unit","unitNm","prdlstNm","dtlsPrnmNm",
                 "prdlstClsfNo","dtlsPrnmNo")
        for row in rows:
            if not isinstance(row,dict):
                errors.append("N05_OFFICIAL_BID_DETAIL_ROW_INVALID")
                break
            cleaned=_pick(row,allowed)
            key=json.dumps(cleaned,sort_keys=True,ensure_ascii=False)
            if key not in seen and len(all_rows)<MAX_BIDDER_ROWS_PER_NOTICE:
                seen.add(key)
                all_rows.append(cleaned)
        if errors:
            break
        if str(rows[-1].get("nextRowYn") or "N").upper()!="Y":
            completed=True
            break
    detail={"source":OPENING_DETAIL,"bid_no":bid,"bid_ord":order,
            "query_origin":"exact_official_opening_list_row",
            "bidClsfNo":str(source["bidClsfNo"]),
            "bidPrgrsOrd":str(source["bidPrgrsOrd"]),
            "prcmBsneSeCd":str(source["prcmBsneSeCd"]),
            "bidPgstCd":str(source["bidPgstCd"]),
            "bidders":all_rows,"source_rows":len(all_rows),
            "pages_complete":completed,"pages_checked":len(sha),
            "source_page_sha256":sha,
            "bid_info_fields":info,
            "business_evaluation_performed":False}
    if not completed:
        errors.append("bidder_detail_pagination_unfinished")
    return detail if sha else None,errors


def n05_openings(opener,history,post,today):
    """Collect source-backed opening and bidder records for up to 50 historical
    candidates. No participant scoring, final-award inference, or AI evaluation.
    """
    candidates=list((history or {}).get("records") or [])
    value={"source":OPENING_LIST,"opening_records":[],
           "bidder_detail_records":[],"candidates":len(candidates),
           "checked":0,"attempted":0,"opening_list_pages":0,
           "opening_list_response_rows":0,"unrelated_response_rows":0,
           "not_published_count":0,"detail_requests_completed":0,
           "full_bidder_participation_records_verified":False,
           "all_candidate_openings_collected":False,"per_notice":[],
           "gaps":[],"business_evaluation_performed":False}
    if not candidates:
        value["gaps"].append("no_historical_candidates")
    for record in candidates[:MAX_OPENING_LOOKUPS]:
        bid,order=_valid_notice(record)
        period=record.get("query_period") or {}
        date_from=period.get("from") or _year_back(today).strftime("%Y%m%d")
        date_to=period.get("to") or today.strftime("%Y%m%d")
        if date_to>today.strftime("%Y%m%d"):date_to=today.strftime("%Y%m%d")
        entry={"bid_no":bid,"bid_ord":order,"opening_list_rows":0,
               "bidder_rows":0,"status":"unverified"}
        value["attempted"]+=1
        try:
            listing=_n05_opening_list(opener,post,bid,order,date_from,date_to)
            value["checked"]+=1
            value["opening_list_pages"]+=listing["pages"]
            value["opening_list_response_rows"]+=listing["response_rows"]
            value["unrelated_response_rows"]+=listing["ignored_filter_rows"]
            entry["opening_list_rows"]=len(listing["matched"])
            entry["listing_pages_complete"]=listing["pages_complete"]
            if not listing["pages_complete"]:
                entry["status"]="pagination_incomplete"
                value["gaps"].append("opening_listing_page_limit:"+bid+"-"+order)
            if not listing["matched"]:
                entry["status"]="not_published_or_not_returned" if listing["pages_complete"] else entry["status"]
                value["not_published_count"]+=1
                value["per_notice"].append(entry)
                continue
            all_details_completed=True
            for source_row in listing["matched"]:
                value["opening_records"].append({
                    "bid_no":bid,"bid_ord":order,
                    "detail10":record.get("detail10"),
                    "official_fields":_pick(source_row,OPEN_FIELDS),
                    "source":OPENING_LIST,
                    "source_row_sha256":sha256(json.dumps(source_row,ensure_ascii=False,
                        sort_keys=True).encode()).hexdigest()})
                detail,errors=_n05_bidder_details(opener,post,bid,order,source_row)
                if detail:
                    value["bidder_detail_records"].append(detail)
                    entry["bidder_rows"]+=len(detail["bidders"])
                    if detail["pages_complete"]:
                        value["detail_requests_completed"]+=1
                    else:
                        all_details_completed=False
                else:
                    all_details_completed=False
                for problem in errors:
                    value["gaps"].append("opening_detail:"+bid+"-"+order+":"+problem)
            entry["status"]="collected" if all_details_completed and listing["pages_complete"] else "partial"
        except Exception as exc:
            entry["status"]="source_error"
            entry["error"]=_n05_error(exc)
            value["gaps"].append("opening_lookup_failed:"+bid+"-"+order+":"+entry["error"])
        value["per_notice"].append(entry)
    if len(candidates)>MAX_OPENING_LOOKUPS:
        value["gaps"].append("opening_lookup_limit_"+str(MAX_OPENING_LOOKUPS))
    value["observed_bidder_row_count"]=sum(
        len(d.get("bidders") or []) for d in value["bidder_detail_records"])
    value["full_bidder_participation_records_verified"]=bool(
        value["bidder_detail_records"] and
        all(x.get("pages_complete") for x in value["bidder_detail_records"]))
    value["all_candidate_openings_collected"]=bool(
        candidates and len(candidates)<=MAX_OPENING_LOOKUPS
        and value["checked"]==len(candidates)
        and all(e["status"]=="collected" for e in value["per_notice"]))
    if not value["opening_records"]:
        value["gaps"].append("no_official_opening_records_collected")
    if not value["observed_bidder_row_count"]:
        value["gaps"].append("bidder_amounts_not_collected")
    # Successful lookup of a bidder list is not proof of a signed final award.
    value["gaps"].append("final_signed_award_detail_not_verified")
    return ("verified" if value["all_candidate_openings_collected"]
            and value["observed_bidder_row_count"]>0 else "partial"),value

def _bid_identity(row):
    """Source-backed company grouping; avoid merging unnamed competitors."""
    business=_scalar(row.get("bzmnRegNo"))
    name=_scalar(row.get("grpNm") or row.get("fnlSucsfbdCorpNm"))
    if business:
        return "registration:"+business,"registration_number",business,name
    if name:
        return "name_unverified:"+name,"unverified_name",None,name
    return None,"unidentified",None,None


def n06_supply_catalog(notice,n02,history,opening):
    """Organize every N05 bidder/tender observation BY COMPANY, unchanged.
    No new supplier quotation or workforce search. No business evaluation.
    """
    details=list((opening or {}).get("bidder_detail_records") or [])
    companies={}
    ledger=[]
    award_evidence=[]
    unidentified=0
    for detail_index,detail in enumerate(details):
        bid,order=_valid_notice(detail)
        notice_key=bid+"-"+order
        provenance={"source":detail.get("source") or OPENING_DETAIL,
                    "source_page_sha256":list(detail.get("source_page_sha256") or []),
                    "bidClsfNo":detail.get("bidClsfNo"),
                    "bidPrgrsOrd":detail.get("bidPrgrsOrd")}
        for bidder_index,raw in enumerate(detail.get("bidders") or []):
            if not isinstance(raw,dict):
                continue
            key,ident,regno,name=_bid_identity(raw)
            if not key:
                unidentified+=1
                key="unidentified:"+bid+"-"+order+":"+str(len(ledger))
            rec={"bid_no":bid,"bid_ord":order,
                 "company_key":key,"company_name":name,
                 "registration_number":regno,
                 "company_identity_basis":ident,
                 "bid_amount":_scalar(raw.get("bdngAmt") or raw.get("sucsfbidAmt")),
                 "bid_rate":_scalar(raw.get("bdrt") or raw.get("sucsfbidRate")),
                 "bid_rank":_scalar(raw.get("onbsRnkg") or raw.get("bidprcRank")),
                 "source_detail_index":detail_index,
                 "source_bidder_index":bidder_index,
                 "source":provenance["source"]}
            index=len(ledger)
            ledger.append(rec)
            if key not in companies:
                companies[key]={"company_key":key,"company_name":name,
                    "registration_number":regno,"identity_basis":ident,
                    "bid_record_indexes":[],"participated_notice_keys":[],
                    "award_source_record_indexes":[]}
            company=companies[key]
            company["bid_record_indexes"].append(index)
            if notice_key not in company["participated_notice_keys"]:
                company["participated_notice_keys"].append(notice_key)
        # Explicit source fields are stored without asserting award finality.
        fields=detail.get("bid_info_fields") or {}
        if fields:
            evidence={"bid_no":bid,"bid_ord":order,
                      "source":provenance["source"],
                      "source_page_sha256":provenance["source_page_sha256"],
                      "raw_award_result_fields":dict(fields),
                      "final_award_verified":False}
            award_evidence.append(evidence)
            names={v for k,v in fields.items()
                   if k in ("fnlSucsfbdCorpNm","fnlBidWinnrNm") and v}
            if len(names)==1:
                target=next(iter(names))
                for company in companies.values():
                    if company["company_name"]==target and notice_key in company["participated_notice_keys"]:
                        company["award_source_record_indexes"].append(len(award_evidence)-1)
    files=[{"file_seq":f.get("file_seq"),"sha256":f.get("sha256"),
            "source":f.get("source"),"size_bytes":f.get("size_bytes")}
           for f in (n02 or {}).get("files") or []]
    gaps=[]
    if not ledger:gaps.append("no_N05_bidder_rows_to_organize")
    if unidentified:gaps.append("bidder_identity_missing:"+str(unidentified))
    if any(c["identity_basis"]=="unverified_name" for c in companies.values()):
        gaps.append("company_names_not_verified_as_unique_registration_ids")
    if not award_evidence:gaps.append("final_award_and_contract_source_records_not_observed_in_N05")
    # N05 only covers the selected sample; do not claim a company's lifetime history.
    gaps.append("company_all_time_bid_history_not_proven_beyond_N05_sample")
    return ("verified" if ledger else "partial"),{
        "source":"N05_official_bidder_detail_records",
        "company_records":list(companies.values()),
        "company_count":len(companies),"bid_history_records":ledger,
        "bid_history_record_count":len(ledger),
        "award_result_source_records":award_evidence,
        "award_result_source_count":len(award_evidence),
        "official_originals_catalog":files,
        "N05_opening_document_count":len(details),
        "registration_information_enriched":False,
        "all_time_company_history_verified":False,
        "gaps":gaps,
        "business_evaluation_performed":False}


def _field_sources(record,fields,source,bid=None,order=None,class8=None,detail10=None):
    """Keep original numeric/quantity fields and labels, never calculate price."""
    out=[]
    for key in fields:
        if record.get(key) not in (None,""):
            out.append({"source":source,"bid_no":bid,"bid_ord":order,
                        "class8":class8,"detail10":detail10,
                        "field":key,"raw":_scalar(record[key])})
    return out


def n07_price_sources(notice,metadata,history,opening,supply):
    """Organize N05 PRICE / QUANTITY / ITEM evidence by item classification.
    N06 is a separate company view; neither stage predicts a winning bid.
    """
    historical=list((history or {}).get("records") or [])
    history_map={(x.get("bid_no"),x.get("bid_ord") or "000"):x
                 for x in historical if isinstance(x,dict)}
    group_map={}
    amounts=[]
    quantities=[]
    missing_class=0
    amount_fields=("scsbdAmt","scsbdPrce","scsbidAmt","scsbidRate",
                   "bidPrspPrce","alotBgtAmt","bdgtAmt","baseAmt")
    quantity_fields=("qnty","quantity","bidQntty","bidQty","prdlstQty",
                     "itemQty","unit","unitNm","prdlstNm","dtlsPrnmNm")
    bidder_price_fields=("bdngAmt","sucsfbidAmt","bdrt","sucsfbidRate")
    fields=(metadata or {}).get("official_fields") or {}
    amounts.extend(_field_sources(fields,amount_fields,"N03_official_record"))
    amounts.extend(_field_sources(notice or {},("budget",),"N01_official_bid_list"))
    # Some notices publish an opening/award row but no bidder detail.
    # Keep their price, item and quantity fields rather than dropping them.
    for origin in (opening or {}).get("opening_records") or []:
        if not isinstance(origin,dict):continue
        bid=origin.get("bid_no")
        order=origin.get("bid_ord") or "000"
        history_row=history_map.get((bid,order)) or {}
        official=history_row.get("official_fields") or {}
        raw=origin.get("official_fields") or {}
        code8=history_row.get("class8") or _classification8(official)[0] or _classification8(raw)[0]
        code10=history_row.get("detail10") or _classification(official)[0] or _classification(raw)[0]
        classification=code8 or "unclassified"
        group=group_map.setdefault(classification,{
            "class8":code8,"classification_basis":
                "official_record" if code8 else "unclassified_N04_candidate",
            "notice_keys":[],"price_record_indexes":[],
            "quantity_record_indexes":[]})
        key=bid+"-"+order
        if key not in group["notice_keys"]:group["notice_keys"].append(key)
        for a in _field_sources(raw,amount_fields,OPENING_LIST,bid,order,code8,code10):
            group["price_record_indexes"].append(len(amounts));amounts.append(a)
        for q in _field_sources(raw,quantity_fields,OPENING_LIST,bid,order,code8,code10):
            group["quantity_record_indexes"].append(len(quantities));quantities.append(q)
    for detail in (opening or {}).get("bidder_detail_records") or []:
        if not isinstance(detail,dict):continue
        bid,order=_valid_notice(detail)
        history_row=history_map.get((bid,order)) or {}
        official=history_row.get("official_fields") or {}
        code8=history_row.get("class8") or _classification8(official)[0]
        code10=history_row.get("detail10") or _classification(official)[0]
        classification=code8 or "unclassified"
        if not code8:missing_class+=1
        group=group_map.setdefault(classification,{
            "class8":code8,"classification_basis":
                "official_record" if code8 else "unclassified_N04_candidate",
            "notice_keys":[],"price_record_indexes":[],
            "quantity_record_indexes":[]})
        nkey=bid+"-"+order
        if nkey not in group["notice_keys"]:group["notice_keys"].append(nkey)
        # Preserve official winning-result price fields, if actually present.
        # These remain raw source values, not verified signed contract awards.
        result_fields=detail.get("bid_info_fields") or {}
        for a in _field_sources(result_fields,amount_fields,
                    detail.get("source") or OPENING_DETAIL,bid,order,code8,code10):
            a["evidence_kind"]="unverified_official_award_result_field"
            group["price_record_indexes"].append(len(amounts));amounts.append(a)
        for raw in detail.get("bidders") or []:
            if not isinstance(raw,dict):continue
            identity=_scalar(raw.get("bzmnRegNo") or raw.get("grpNm") or raw.get("fnlSucsfbdCorpNm"))
            for a in _field_sources(raw,bidder_price_fields,
                detail.get("source") or OPENING_DETAIL,bid,order,code8,code10):
                a["source_company_identifier"]=identity
                group["price_record_indexes"].append(len(amounts));amounts.append(a)
            for q in _field_sources(raw,quantity_fields,
                detail.get("source") or OPENING_DETAIL,bid,order,code8,code10):
                group["quantity_record_indexes"].append(len(quantities));quantities.append(q)
        for a in _field_sources(official,amount_fields,
                               history_row.get("source") or BID_LIST,
                               bid,order,code8,code10):
            group["price_record_indexes"].append(len(amounts));amounts.append(a)
        for q in _field_sources(official,quantity_fields,
                               history_row.get("source") or BID_LIST,
                               bid,order,code8,code10):
            group["quantity_record_indexes"].append(len(quantities));quantities.append(q)
    gaps=[]
    if not group_map:gaps.append("no_N05_price_or_classification_history")
    if missing_class:gaps.append("N05_opening_records_without_verified_item8_classification:"+str(missing_class))
    if not quantities:gaps.append("item_quantity_not_provided_in_collected_N05_records")
    # Historic bid amounts and opening/award fields must never be silently
    # promoted to final winning prices. Preserve original field names.
    gaps.append("signed_final_award_price_not_verified_from_N05_bidder_rows")
    n05_price_fields=sum(1 for x in amounts if x.get("bid_no") and x.get("source") in
        (OPENING_LIST,OPENING_DETAIL))
    if not n05_price_fields:
        gaps.append("N05_item_price_fields_not_collected")
    return ("verified" if n05_price_fields and group_map else "partial"),{
        "source":"N05_openings_and_N04_item_classification",
        "N05_item_price_field_count":n05_price_fields,
        "classification_groups":list(group_map.values()),
        "classification_group_count":len(group_map),
        "source_amounts":amounts,"source_amount_count":len(amounts),
        "price_quantity_records":quantities,"quantity_source_count":len(quantities),
        "awarded_price_records_verified":0,
        "historical_opening_records":len((opening or {}).get("opening_records") or []),
        "bidder_price_source_records":sum(len(x.get("bidders") or [])
                         for x in (opening or {}).get("bidder_detail_records") or []),
        "contract_source_fields":_pick(fields,
            ("bidCtrtMthdCd","ctrtTyCd","scsbdMthdCd","odnLmtLgdngCd")),
        "source_amounts_truncated":False,"recommended_bid":None,
        "gaps":gaps,"business_evaluation_performed":False}


def n08_handoff(notice,previous):
    """Create bounded provenance-rich AI intake manifest; never draft a bid."""
    steps={}
    all_gaps=[]
    for stage in ("N01","N02","N03","N04","N05","N06","N07"):
        record=previous.get(stage) or {}
        steps[stage]={"source":record.get("source"),
          "records":record.get("bid_history_record_count",record.get("source_amount_count",
             record.get("collected_record_count",record.get("file_count",
             record.get("verified_record_count",record.get("checked",
               record.get("source_amounts") and len(record["source_amounts"]))))))),
          "gaps":list(record.get("gaps") or [])[:40]}
        all_gaps.extend(stage+":"+str(x) for x in record.get("gaps") or [])
    files=[{"file_seq":x.get("file_seq"),"original_filename":x.get("original_filename"),
            "sha256":x.get("sha256"),"size_bytes":x.get("size_bytes"),
            "source":x.get("source")} for x in (previous.get("N02") or {}).get("files") or []]
    bundle={"selected_notice":{
              k:notice.get(k) for k in ("bid_no","bid_ord","title","agency",
                  "business_code","publication","budget") if notice},
            "originals":files,"stage_catalog":steps,
            "exact_detail10":(previous.get("N03") or {}).get("detail10"),
            "historical_notice_records":(previous.get("N04") or {}).get("records",[]),
            "opening_records":(previous.get("N05") or {}).get("opening_records",[]),
            "bidder_detail_records":(previous.get("N05") or {}).get("bidder_detail_records",[]),
            "company_records":(previous.get("N06") or {}).get("company_records",[]),
            "company_bid_history_records":(previous.get("N06") or {}).get("bid_history_records",[]),
            "company_award_result_source_records":(previous.get("N06") or {}).get("award_result_source_records",[]),
            "item_classification_groups":(previous.get("N07") or {}).get("classification_groups",[]),
            "source_amount_fields":(previous.get("N07") or {}).get("source_amounts",[]),
            "item_quantity_source_fields":(previous.get("N07") or {}).get("price_quantity_records",[]),
            "collection_gaps":all_gaps[:200]}
    raw=json.dumps(bundle,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()
    if len(raw)>1_200_000:
        return "partial",{"source":"N01_N07_unassessed_sources",
          "bundle_error":"BUNDLE_EXCEEDS_RELAY_LIMIT_NO_SILENT_TRUNCATION",
          "bundle_bytes":len(raw),"gaps":all_gaps[:40],
          "business_evaluation_performed":False}
    # N08's own task is to assemble a faithful collection handoff, not
    # decide whether the upstream collection was exhaustive. Preserve every
    # upstream gap in the bundle; the handoff itself can be verified.
    return ("verified" if files else "partial"),{
        "source":"N01_N07_unassessed_sources",
        "handoff_bundle":bundle,
        "bundle_bytes":len(raw),
        "bundle_sha256":sha256(raw).hexdigest(),
        "source_originals":len(files),
        "collection_gaps":all_gaps[:200],
        "handoff_assembled":True,
        "upstream_collection_incomplete":bool(all_gaps) or not bool(files),
        "business_evaluation_performed":False,
        "ai_analysis_performed":False,
        "word_draft_generated":False}
