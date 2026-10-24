"""Official public G2B category-field discovery for previously collected bid IDs.

Read-only diagnostic. A valid 8/10-digit category code must appear in the
official response under an explicit classification field; do not guess one
from the notice title or use a company ID as an item category.
"""
from __future__ import annotations

import re
from playwright.sync_api import sync_playwright
from db import session
from g2b_award_web_collector import BASE, DETAIL_URL, HEADERS, _request


DETAIL_HEADERS={k:v for k,v in HEADERS.items() if k not in ("Menu-Info","Target-Id")}
DETAIL_HEADERS["Target-Id"]="btnOnbsRslt"
FIELD=re.compile(r"(prdlst|clsfc|goods|item|prod|lics|indty|industry|category|bzmn|업종|품명|분류)",re.I)
NUM=re.compile(r"^\d{8}(?:\d{2})?$")

def inspect_tree(obj, prefix="", depth=0, limit=90):
    result=[]
    if depth>4:return result
    if isinstance(obj,dict):
        for k,v in obj.items():
            key=str(k)
            path=prefix+"."+key if prefix else key
            if FIELD.search(key):
                txt=str(v or "").strip()
                result.append({"path":path,"value":txt[:120] if not isinstance(v,(list,dict)) else "<nested>",
                               "looks_like_category":bool(NUM.fullmatch(txt))})
            if isinstance(v,(dict,list)) and len(result)<limit:
                result.extend(inspect_tree(v,path,depth+1,limit-len(result)))
            if len(result)>=limit:break
    elif isinstance(obj,list):
        for i,v in enumerate(obj[:2]):
            result.extend(inspect_tree(v,prefix+"["+str(i)+"]",depth+1,limit-len(result)))
    return result[:limit]

def probe_categories(max_samples=3):
    with session() as con:
        records=con.execute("""SELECT DISTINCT ON (bid_ntce_no,bid_ntce_ord)
                 bid_ntce_no,bid_ntce_ord,bid_clsfc_no,rbid_no,category,title
                 FROM procureflow.bid_results
                 WHERE source='g2b' AND result_kind='award'
                 ORDER BY bid_ntce_no,bid_ntce_ord,first_seen DESC LIMIT %s""",
                 (max(1,min(5,max_samples)),)).fetchall()
    out={"samples":[],"source_url":DETAIL_URL,"tested_count":len(records),
         "fields":"public nuri opening/award details, not bid-notice attachments"}
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True,args=["--no-sandbox","--disable-dev-shm-usage"])
        context=browser.new_context(locale="ko-KR",timezone_id="Asia/Seoul")
        page=context.new_page()
        try:
            r=page.goto(BASE,wait_until="domcontentloaded",timeout=35000)
            out["homepage_status"]=r.status if r else None
            for bid in records:
                payload={"dlSrchCndtM":{
                    "bidPbancNo":bid["bid_ntce_no"],"bidPbancOrd":bid["bid_ntce_ord"],
                    "bidClsfNo":bid["bid_clsfc_no"] or "0",
                    "bidPrgrsOrd":bid["rbid_no"] or "000",
                    "bidPbancPgstCd":"입160010","kbrdrId":"","etpsUntyGrpNo":"",
                    "prcrId":"","prcsRsn":"","cvlnOrbySeCd":"",
                    "cvlnEtpsSrngPgstCd":"","myBdonLisMovYn":""}}
                try:
                    data=_request(context,DETAIL_URL,payload,DETAIL_HEADERS)
                    out["samples"].append({
                        "bid_no":bid["bid_ntce_no"],"title":bid["title"][:130],
                        "existing_category":bid["category"],
                        "response_keys":sorted(data.keys())[:45] if isinstance(data,dict) else [],
                        "notice_keys":sorted((data.get("pbancMap") or {}).keys())[:90] if isinstance(data,dict) else [],
                        "category_field_candidates":inspect_tree(data,limit=70)})
                except Exception as exc:
                    out["samples"].append({"bid_no":bid["bid_ntce_no"],
                          "error":type(exc).__name__+":"+str(exc)[:160]})
        finally:
            context.close();browser.close()
    return out
