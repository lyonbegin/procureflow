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

def n04_history(opener,notice,n03,post,live,today,max_pages=MAX_HISTORY_PAGES_PER_YEAR):
    """10 calendar years of filtered official notices; strict field-by-field proof."""
    bid,order=_valid_notice(notice)
    code=(n03 or {}).get("detail10") if (n03 or {}).get("detail10_verified") else None
    periods=list(_periods(today))
    result={"source":BID_LIST,"selected_bid_no":bid,"selected_bid_ord":order,
            "requested_detail10":code,"periods_requested":len(periods),
            "periods_checked":[],"records":[],"unverified_classification_count":0,
            "total_responses":0,"all_history_complete":False,
            "business_evaluation_performed":False,"gaps":[]}
    if not code:
        result["gaps"].append("exact_10_digit_class_required_for_10_year_search")
        return "partial",result
    records=[];truncated=False
    for start,end in periods:
        segment={"from":start,"to":end,"pages_checked":0,"returned_rows":0,
                 "exact_code_rows":0,"complete":False}
        try:
            for page in range(1,max_pages+1):
                rows=_g2b_rows(opener,post,live,start,end,code=code,page=page)
                segment["pages_checked"]+=1
                segment["returned_rows"]+=len(rows)
                result["total_responses"]+=len(rows)
                for row in rows:
                    actual,field=_classification(row)
                    if actual!=code:
                        result["unverified_classification_count"]+=1
                        continue
                    number,ordr=_ident(row)
                    if not number or not re.fullmatch(r"(?:R\d{2}BK\d{8}|\d{11})",number):
                        continue
                    record={"bid_no":number,"bid_ord":ordr,"detail10":actual,
                            "detail10_source_field":field,"source":BID_LIST,
                            "query_period":{"from":start,"to":end},
                            "official_fields":_pick(row,PUBLIC_FIELDS)}
                    segment["exact_code_rows"]+=1
                    if len(records)<MAX_HISTORY_ROWS:records.append(record)
                    else:truncated=True
                if len(rows)<20:
                    segment["complete"]=True
                    break
            if not segment["complete"]:
                result["gaps"].append("history_period_page_limit:"+start+"-"+end)
        except Exception as exc:
            segment["error"]=type(exc).__name__+":"+str(exc)[:100]
            result["gaps"].append("history_period_lookup_failed:"+start+"-"+end)
        result["periods_checked"].append(segment)
    if result["unverified_classification_count"]:
        result["gaps"].append("official_rows_without_verified_matching_10_digit_code")
    if truncated:result["gaps"].append("history_records_exceed_inline_result_limit")
    result["records"]=records
    result["verified_record_count"]=len(records)
    result["records_truncated"]=truncated
    result["all_history_complete"]=(all(x["complete"] for x in result["periods_checked"])
        and not result["gaps"] and len(result["periods_checked"])==len(periods))
    return ("verified" if result["all_history_complete"] else "partial"),result

def n05_openings(opener,history,post,today):
    """Collect opening-list source records; never guess bidder or winner data."""
    candidates=list((history or {}).get("records") or [])
    value={"source":OPENING_LIST,"opening_records":[],"candidates":len(candidates),
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
    if len(candidates)>MAX_OPENING_LOOKUPS:
        value["gaps"].append("opening_lookup_limit_"+str(MAX_OPENING_LOOKUPS))
    # An opening list alone does not enumerate bidders or establish the award.
    value["gaps"].append("bidder_tender_amounts_and_signed_award_detail_not_yet_collected")
    value["all_candidate_openings_collected"]=(value["checked"]==len(candidates)
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
