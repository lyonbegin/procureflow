"""Enrich ONLY code-matched selected G2B historical notices with official Nuri opening details.

This is a bounded 4-notice batch. Official G2B data is accepted only when
the returned bid number matches exactly. Never infer a final award from rank 1.
"""
from __future__ import annotations
import json,logging
from playwright.sync_api import sync_playwright
from db import session
from g2b_case_10y import CASE_BID
from g2b_award_web_collector import BASE,DETAIL_URL,_request
from g2b_final_award_collector import DETAIL_HEADERS,normalized_confirmed_award,FINAL_STATUS
from g2b_bid_collector import normalize_item,save_batch

def ensure_schema():
    with session() as con:
        con.execute("""CREATE TABLE IF NOT EXISTS procureflow.g2b_case_opening_enrich_audit(
          bid_no text PRIMARY KEY,
          source text NOT NULL DEFAULT 'nuri_official_public_detail',
          status text NOT NULL DEFAULT 'pending',
          bidders int NOT NULL DEFAULT 0,
          winner_verified boolean NOT NULL DEFAULT false,
          error text NOT NULL DEFAULT '',
          updated_at timestamptz NOT NULL DEFAULT now())""")

def _payload(no,ord_):
    return {"dlSrchCndtM":{
      "bidPbancNo":no,"bidPbancOrd":ord_,"bidClsfNo":"0",
      "bidPrgrsOrd":"000","bidPbancPgstCd":FINAL_STATUS,
      "kbrdrId":"","etpsUntyGrpNo":"","prcrId":"","prcsRsn":"",
      "cvlnOrbySeCd":"","cvlnEtpsSrngPgstCd":"","myBdonLisMovYn":""}}

def run(limit=4):
    ensure_schema()
    limit=max(1,min(8,int(limit)))
    with session() as con:
        notices=con.execute("""SELECT h.hist_notice_no AS bid_no,
              h.hist_notice_ord AS bid_ord,h.title AS title
            FROM procureflow.g2b_case_10yr_history h
            LEFT JOIN procureflow.g2b_case_opening_enrich_audit audit
               ON audit.bid_no=h.hist_notice_no
            WHERE h.case_bid_no=%s AND h.classification8='81111599'
              AND h.hist_notice_no ~ '^R[0-9]{2}BK[0-9]{8}$'
              AND audit.bid_no IS NULL
            ORDER BY h.published_on DESC,h.hist_notice_no DESC LIMIT %s""",
            (CASE_BID,limit)).fetchall()
    result={"selected_bid":CASE_BID,"attempted":0,"saved_bidder_rows":0,
            "new_bidder_rows":0,"confirmed_winners":0,"notices":[],"errors":[],
            "source":"nuri.g2b.go.kr official detail; exact category match"}
    if not notices:return {**result,"status":"no_unchecked_historical_notices"}
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True,args=["--no-sandbox","--disable-dev-shm-usage"])
        context=browser.new_context(locale="ko-KR",timezone_id="Asia/Seoul")
        page=context.new_page()
        try:
            homepage=page.goto(BASE,wait_until="domcontentloaded",timeout=34000)
            if not homepage or homepage.status>=400:
                return {**result,"status":"official_nuri_unavailable"}
            for notice in notices:
                no,ord_=notice["bid_no"],notice["bid_ord"]
                result["attempted"]+=1
                status="no_official_opening_detail";error="";total=0;is_winner=False
                try:
                    data=_request(context,DETAIL_URL,_payload(no,ord_),DETAIL_HEADERS)
                    pbanc=data.get("pbancMap") or {}
                    if str(pbanc.get("bidPbancNo") or "")!=no:
                        raise ValueError("official_detail_notice_id_mismatch")
                    bidders=data.get("oobsRsltList") or []
                    if not isinstance(bidders,list):
                        raise ValueError("official_bidder_list_bad_schema")
                    rec=[]
                    for i,b in enumerate(bidders):
                        if not isinstance(b,dict) or not str(b.get("ibxGrpNm") or "").strip():
                            continue
                        item={"bid_no":no,"bid_ord":ord_,
                              "bidClsfNo":pbanc.get("bidClsfNo") or "0",
                              "bidPrgrsOrd":pbanc.get("bidPrgrsOrd") or "000",
                              "onbsRnkg":b.get("ibxOnbsRnkg"),
                              "bzmnRegNo":b.get("ibxBzmnRegNo"),
                              "grpNm":b.get("ibxGrpNm"),
                              "bdngAmt":b.get("ibxBdngAmt"),
                              "bdrt":b.get("ibxBdrt"),
                              "bid_name":pbanc.get("bidPbancNm") or notice["title"],
                              "agency":pbanc.get("pbancInstUntyGrpNoNm"),
                              "result_status":pbanc.get("bidPbancPgstCdNm"),
                              "bidUfnsRsnCd":b.get("bidUfnsRsnCd")}
                        parsed=normalize_item(item,"service","opening",
                                               "g2b_nuri_historical_detail",i)
                        if parsed:rec.append(parsed)
                    saved,new=save_batch(rec)
                    result["saved_bidder_rows"]+=saved
                    result["new_bidder_rows"]+=new
                    total=len(rec)
                    winner=normalized_confirmed_award(
                        {"bidPbancNo":no,"bidPbancOrd":ord_},data)
                    if winner:
                        _,awards_new=save_batch([winner])
                        is_winner=True
                        result["confirmed_winners"]+=awards_new
                    status="official_opening_saved" if rec else "official_no_bidder_rows"
                except Exception as exc:
                    status="error"
                    error=type(exc).__name__+":"+str(exc)[:160]
                    if len(result["errors"])<12:result["errors"].append(no+":"+error)
                with session() as db:
                    db.execute("""INSERT INTO procureflow.g2b_case_opening_enrich_audit
                        (bid_no,status,bidders,winner_verified,error)
                        VALUES (%s,%s,%s,%s,%s)
                        ON CONFLICT(bid_no) DO UPDATE SET
                          status=excluded.status,bidders=excluded.bidders,
                          winner_verified=excluded.winner_verified,
                          error=excluded.error,updated_at=now()
                        """,(no,status,total,is_winner,error))
                result["notices"].append({"bid_no":no,"status":status,
                                          "bidders":total,"confirmed_winner":is_winner})
        finally:context.close();browser.close()
    result["status"]="partial" if result["errors"] else "checked"
    return result
