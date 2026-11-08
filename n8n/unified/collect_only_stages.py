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
    "ctrtTyCd","bidCtrtMthdCd","scsbdMthdCd","odnLmtLgdngCd",
    "fromBidDt","toBidDt","bdgtAmt","baseAmt","bidClseDt",
)
OPEN_FIELDS=("bidPbancNo","bidPbancOrd","bidPbancNm",
             "onbsYmd","onbsDt","onbsPrnmntDt","prcmBsneSeCd",
             "scsbdMthdCd","scsbdMthdNm","pbancSttsNm",
             "scsbdAmt","scsbdPrce","scsbidAmt","scsbidRate")
MAX_HISTORY_ROWS=400
MAX_HISTORY_PAGES_PER_YEAR=10
MAX_OPENING_LOOKUPS=30

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
def _year_back(day):
    try:return day.replace(year=day.year-10)
    except ValueError:return day.replace(year=day.year-10,day=28)
def _periods(day):
    start=_year_back(day)
    cursor=start
    while cursor<=day:
        try:nxt=cursor.replace(year=cursor.year+1)
        except ValueError:nxt=cursor.replace(year=cursor.year+1,day=28)
        end=min(day,nxt-timedelta(days=1))
        yield cursor.strftime("%Y%m%d"),end.strftime("%Y%m%d")
        cursor=end+timedelta(days=1)
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


def n04_history(opener,notice,n03,post,live,today,max_pages=MAX_HISTORY_PAGES_PER_YEAR):
    """Collect historical candidates without requiring a 10-digit class.
    Every official response is checked for the actual query predicate, because
    an HTTP 200 may mean that the official site ignored a search filter.
    """
    bid,order=_valid_notice(notice)
    mode,filter_fields,query=_history_query(notice,n03)
    periods=list(reversed(list(_periods(today))))
    value={"source":BID_LIST,"selected_bid_no":bid,"selected_bid_ord":order,
           "query_mode":mode,"query_value":query,"requested_detail10":(n03 or {}).get("detail10"),
           "requested_class8":(n03 or {}).get("class8"),"periods_requested":len(periods),
           "periods_checked":[],"records":[],"unverified_classification_count":0,
           "total_responses":0,"all_history_complete":False,
           "business_evaluation_performed":False,"gaps":[]}
    if mode=="no_supported_query":
        value["gaps"].append("no_official_item_code_title_or_agency_for_history")
        return "partial",value
    records={};truncated=False
    for date_start,date_end in periods:
        segment={"from":date_start,"to":date_end,"pages_checked":0,
                 "returned_rows":0,"candidate_rows":0,"complete":False}
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
                        continue  # The selected current notice is not historical evidence.
                    item={"bid_no":number,"bid_ord":ordr,"detail10":actual10,
                          "detail10_source_field":field10,"class8":actual8,
                          "class8_source_field":field8,"source":BID_LIST,
                          "match_basis":mode,"official_classification_confirmed":
                               mode in ("official_item8","official_item10"),
                          "query_period":{"from":date_start,"to":date_end},
                          "official_fields":_pick(row,PUBLIC_FIELDS)}
                    segment["candidate_rows"]+=1
                    if key not in records:
                        if len(records)<MAX_HISTORY_ROWS:records[key]=item
                        else:truncated=True
                if len(rows)<20:
                    segment["complete"]=True
                    break
            if not segment["complete"]:
                value["gaps"].append("history_period_page_limit:"+date_start+"-"+date_end)
        except Exception as exc:
            segment["error"]=type(exc).__name__+":"+str(exc)[:100]
            value["gaps"].append("history_period_lookup_failed:"+date_start+"-"+date_end)
        value["periods_checked"].append(segment)
    if value["unverified_classification_count"]:
        value["gaps"].append("source_rows_not_matching_query_predicate")
    if truncated:value["gaps"].append("history_records_exceed_inline_result_limit")
    if mode not in ("official_item8","official_item10"):
        value["gaps"].append("historical_candidates_unclassified_manual_or_final_ai_review")
    value["records"]=list(records.values())
    value["verified_record_count"]=len(records) if mode in ("official_item8","official_item10") else 0
    value["candidate_record_count"]=len(records)
    if not records:value["gaps"].append("no_historical_candidate_collected")
    value["records_truncated"]=truncated
    value["all_history_complete"]=(all(p["complete"] for p in value["periods_checked"])
        and len(value["periods_checked"])==len(periods) and not value["gaps"])
    return ("verified" if value["all_history_complete"] else "partial"),value

def _n05_bidder_details(opener,post,bid,order,source=None):
    """Read-only official WebSquare bid-result detail, never infer a winner."""
    source=source or {}
    errors=[]
    for code in ("","03","01"):
        query={"dlSrchOnbsRsltBidInM":{
            "bidPbancNo":bid,"bidPbancOrd":order,
            "bidClsfNo":str(source.get("bidClsfNo") or "0"),
            "bidPrgrsOrd":str(source.get("bidPrgrsOrd") or "000"),
            "prcmBsneSeCd":code,
            "bidPgstCd":str(source.get("bidPgstCd") or "개찰완료"),
            "bzmnRegNo":"","reOpenPbancYN":"",
            "currentPage":1,"recordCountPerPage":"999"}}
        try:
            result=post(opener,OPENING_DETAIL,query,DETAIL_HEADERS)
            if not isinstance(result,dict):
                raise ValueError("N05_OFFICIAL_BID_DETAIL_SCHEMA_INVALID")
            rows=result.get("successBidInfo") or []
            if not isinstance(rows,list):
                raise ValueError("N05_OFFICIAL_BID_DETAIL_ROWS_INVALID")
            kept=[]
            allowed=("onbsRnkg","bidprcRank","grpNm","fnlSucsfbdCorpNm",
                     "bdngAmt","sucsfbidAmt","bdrt","sucsfbidRate",
                     "bzmnRegNo","bidPgstCd","fnlBidWinnrNm","bidWinnrNm")
            for row in rows[:200]:
                if not isinstance(row,dict):
                    raise ValueError("N05_OFFICIAL_BID_DETAIL_ROW_INVALID")
                kept.append(_pick(row,allowed))
            return {"source":OPENING_DETAIL,"bid_no":bid,"bid_ord":order,
                    "query_business_code":code,"bidders":kept,
                    "source_rows":len(rows),
                    "rows_truncated":len(rows)>200,
                    "source_json_sha256":sha256(json.dumps(result,ensure_ascii=False,
                        sort_keys=True,separators=(",",":")).encode()).hexdigest(),
                    "bid_info_fields":_pick(result.get("bidInfo") or {},
                        ("fnlSucsfbdCorpNm","fnlBidWinnrNm","scsbdAmt","scsbdPrce")),
                    "business_evaluation_performed":False},errors
        except Exception as exc:
            errors.append(type(exc).__name__+":"+str(exc)[:90])
    return None,errors


def n05_openings(opener,history,post,today):
    """Collect opening-list source records; never guess bidder or winner data."""
    candidates=list((history or {}).get("records") or [])
    value={"source":OPENING_LIST,"opening_records":[],"bidder_detail_records":[],
           "candidates":len(candidates),
           "checked":0,"full_bidder_participation_records_verified":False,
           "all_candidate_openings_collected":False,"gaps":[],
           "business_evaluation_performed":False}
    if not candidates:value["gaps"].append("no_exact_10_digit_historical_candidates")
    for record in candidates[:MAX_OPENING_LOOKUPS]:
        bid,order=_valid_notice(record)
        date_from=_year_back(today).strftime("%Y%m%d")
        period=record.get("query_period") or {}
        if period.get("from"):date_from=period["from"]
        date_to=period.get("to") or today.strftime("%Y%m%d")
        payload={"dlSrchOnbsRsltClsfListInM":{
            "bidPbancNo":bid,"bidPbancOrd":order,"bidPbancNm":"",
            "onbsYmdStr":date_from,"onbsYmdEnd":date_to,
            "prcmBsneSeCd":"0000 조070001 조070002 조070003 조070004 조070005",
            "frcpYn":"Y","rsrvYn":"Y","laseYn":"Y","chkBsneAllYn":"Y",
            "lastIndex":100,"firstIndex":1,"inqEnd":"","stepBarYn":"",
            "pbancKndCd":"공440002"}}
        try:
            response=post(opener,OPENING_LIST,payload,OPEN_HEADERS)
            rows=response.get("onbsRsltClsfList") if isinstance(response,dict) else None
            if not isinstance(rows,list):raise ValueError("OFFICIAL_OPENING_SCHEMA_INVALID")
            value["checked"]+=1
            for row in rows:
                if not isinstance(row,dict):raise ValueError("OFFICIAL_OPENING_ROW_INVALID")
                if (_scalar(row.get("bidPbancNo")),_scalar(row.get("bidPbancOrd") or "000"))!=(bid,order):
                    raise ValueError("OFFICIAL_OPENING_UNRELATED_NOTICE")
                value["opening_records"].append({
                   "bid_no":bid,"bid_ord":order,
                   "detail10":record["detail10"],
                   "official_fields":_pick(row,OPEN_FIELDS),
                   "source":OPENING_LIST})
        except Exception as exc:
            value["gaps"].append("opening_lookup_failed:"+bid+"-"+order+":"+type(exc).__name__)
    # The official result-detail endpoint is independent of list pagination.
    # Attempt for every bounded candidate, even when a listing has no rows.
    for record in candidates[:MAX_OPENING_LOOKUPS]:
        bid,order=_valid_notice(record)
        detail,errors=_n05_bidder_details(opener,post,bid,order,
                                            (record.get("official_fields") or {}))
        if detail:
            value["bidder_detail_records"].append(detail)
            if detail["rows_truncated"]:
                value["gaps"].append("bidder_detail_rows_exceed_limit:"+bid)
        else:
            value["gaps"].append("bidder_detail_unavailable:"+bid+":"+
                                 ",".join(errors[:2])[:140])
    if len(candidates)>MAX_OPENING_LOOKUPS:
        value["gaps"].append("opening_lookup_limit_"+str(MAX_OPENING_LOOKUPS))
    # A successful empty list response is not a collected opening/bidder result.
    value["observed_bidder_row_count"]=sum(len(x.get("bidders") or [])
                                        for x in value["bidder_detail_records"])
    if not value["observed_bidder_row_count"]:
        value["gaps"].append("bidder_amounts_not_collected")
    # A winner field does not by itself prove a signed/final award.
    value["gaps"].append("final_signed_award_detail_not_verified")
    value["all_candidate_openings_collected"]=(
        value["checked"]==len(candidates) and bool(value["opening_records"])
        and not any("lookup_failed" in g for g in value["gaps"]))
    return "partial",value

def n06_supply_catalog(notice,n02,history,opening):
    """Register available official evidence + missing external source connectors."""
    files=[{"file_seq":f.get("file_seq"),
            "original_filename":f.get("original_filename"),
            "sha256":f.get("sha256"),"source":f.get("source"),
            "size_bytes":f.get("size_bytes")} for f in (n02 or {}).get("files") or []]
    value={"source":"N01_N02_N04_N05_collected_records_only",
           "official_originals_catalog":files,
           "bid_subject":(notice or {}).get("title"),
           "buyer":(notice or {}).get("agency"),
           "history_candidate_count":len((history or {}).get("records") or []),
           "opening_record_count":len((opening or {}).get("opening_records") or []),
           "supplier_quotation_original_count":0,"company_workforce_original_count":0,
           "source_connectors_checked":["official_N02_attached_originals"],
           "gaps":["independent_supplier_quotation_source_not_connected",
                   "actual_company_workforce_and_cost_source_not_connected"],
           "business_evaluation_performed":False}
    return "partial",value

def n07_price_sources(notice,metadata,history,opening,supply):
    """Collect source-backed numeric strings; NO cost assessment or bid price."""
    amount_fields=("alotBgtAmt","bidPrspPrce","bdgtAmt","baseAmt")
    fields=(metadata or {}).get("official_fields") or {}
    vals=[]
    for key in amount_fields:
        if fields.get(key):
            vals.append({"source":"N03_official_record","field":key,"raw":fields[key]})
    for key in ("budget",):
        if (notice or {}).get(key):
            vals.append({"source":"N01_official_bid_list","field":key,
                         "raw":_scalar(notice[key])})
    for record in (opening or {}).get("opening_records") or []:
        for field in ("scsbdAmt","scsbdPrce","scsbidAmt","scsbidRate"):
            raw=record.get("official_fields",{}).get(field)
            if raw:
                vals.append({"source":OPENING_LIST,"bid_no":record["bid_no"],
                             "field":field,"raw":raw})
    return "partial",{
      "source":"official_collected_amount_field_strings_only",
      "source_amounts":vals[:150],
      "source_amounts_truncated":len(vals)>150,
      "contract_source_fields":_pick(fields,
         ("bidCtrtMthdCd","ctrtTyCd","scsbdMthdCd","odnLmtLgdngCd")),
      "supplier_quotation_original_count":(supply or {}).get("supplier_quotation_original_count",0),
      "gaps":["verified_company_cost_inputs_unavailable",
              "bid_floor_rate_official_source_not_collected"],
      "recommended_bid":None,"business_evaluation_performed":False}

def n08_handoff(notice,previous):
    """Create bounded provenance-rich AI intake manifest; never draft a bid."""
    steps={}
    all_gaps=[]
    for stage in ("N01","N02","N03","N04","N05","N06","N07"):
        record=previous.get(stage) or {}
        steps[stage]={"source":record.get("source"),
          "records":record.get("file_count",record.get("verified_record_count",
            record.get("checked",record.get("source_amounts") and len(record["source_amounts"])))),
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
            "source_amount_fields":(previous.get("N07") or {}).get("source_amounts",[]),
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
