"""N04. Selected notice opening list lookup, exclusively official G2B source.

No recent unrelated sample is presented as the selected tender's opening.
A zero-row response is a verified query, NOT proof of completed opening,
winner/competitor analysis, or ten-year matched classification history.
"""
from __future__ import annotations

from datetime import timedelta
from html import unescape
import re

G2B="https://www.g2b.go.kr"
OPENINGS=G2B+"/pb/pbo/pboc/OnbsRslt/selectOnbsRsltClsfList.do"
HEADERS={
    "Menu-Info":'{"menuNo":"01522","menuCangVal":"PBOC006_01","bsneClsfCd":"%EC%97%85130028","scrnNo":"02117"}',
    "submissionid":"mf_wfm_container_selectOnbsRsltClsfList",
    "Usr-Id":"null",
    "Referer":G2B+"/",
}
SELECTED_FIELDS=(
    "bidPbancNo","bidPbancOrd","bidPbancNm",
    "onbsYmd","onbsDt","onbsPrnmntDt",
    "prcmBsneSeCd","prcmBsneSeCdNm",
    "scsbdMthdCd","scsbdMthdNm","pbancSttsNm",
)
def lookup(opener,notice,json_post,now):
    if not isinstance(notice,dict):
        raise ValueError("N04_SELECTED_NOTICE_REQUIRED")
    bid=str(notice.get("bid_no") or "")
    order=str(notice.get("bid_ord") or "000")
    if not re.fullmatch(r"(?:R\d{2}BK\d{8}|\d{11})",bid) or not re.fullmatch(r"\d{3}",order):
        raise ValueError("N04_SELECTED_NOTICE_ID_INVALID")
    today=now()
    start=(today-timedelta(days=365)).strftime("%Y%m%d")
    end=today.strftime("%Y%m%d")
    query={
        "dlSrchOnbsRsltClsfListInM":{
            "bidPbancNo":bid,"bidPbancOrd":order,"bidPbancNm":"",
            "onbsYmdStr":start,"onbsYmdEnd":end,
            "prcmBsneSeCd":"0000 조070001 조070002 조070003 조070004 조070005",
            "frcpYn":"Y","rsrvYn":"Y","laseYn":"Y","chkBsneAllYn":"Y",
            "lastIndex":100,"firstIndex":1,"inqEnd":"","stepBarYn":"",
            "pbancKndCd":"공440002",
        }
    }
    result=json_post(opener,OPENINGS,query,HEADERS)
    rows=result.get("onbsRsltClsfList") if isinstance(result,dict) else None
    if not isinstance(rows,list):
        raise ValueError("N04_OFFICIAL_OPENING_LIST_SCHEMA_INVALID")
    # Fail closed; this is critical for competitor-award matching.
    verified=[]
    for row in rows:
        if not isinstance(row,dict):raise ValueError("N04_OFFICIAL_NON_OBJECT_ROW")
        actual=str(row.get("bidPbancNo") or "")
        actual_order=str(row.get("bidPbancOrd") or "")
        if actual!=bid or actual_order!=order:
            raise ValueError("N04_UNRELATED_OFFICIAL_OPENING_ROW")
        verified.append({k:unescape(str(row[k]))[:250] for k in SELECTED_FIELDS
                         if row.get(k) not in (None,"")})
    return {
        "source":OPENINGS,
        "retrieval_mode":"exact_selected_notice_only",
        "source_query_verified":True,
        "bid_no":bid,"bid_ord":order,
        "search_request_window":{"start":start,"end":end},
        "official_rows":len(verified),
        "matching_selected_notice":len(verified),
        "records":verified[:100],
        "query_result":"matching_notice_list_rows" if verified else "no_matching_rows_in_window",
        "selected_notice_opening_original_detail_verified":False,
        "original_tenderer_count":None,
        "original_award_winner":None,
        "exact_detail10_verified":False,
        "complete_ten_year_history":False,
        "next_required":"Retrieve verified selected opening detail and separately link 10-digit item classification to 10-year historical openings",
    }
