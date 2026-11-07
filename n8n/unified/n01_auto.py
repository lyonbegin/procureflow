"""N01 automated newest-first selection and durable nine-stage completion checkpoints.

Only official G2B listing rows are tender discovery. This JSON journal is NEW
workflow state, NOT a historical procurement database, and never sources
notice content. A tender is skippable only when ALL N01..N09 are verified.
"""
from __future__ import annotations
from datetime import datetime
from pathlib import Path
from threading import RLock
from zoneinfo import ZoneInfo
import json
import os
import re
import uuid

LEDGER_PATH=Path(os.environ.get("PROCUREFLOW_N01_LEDGER_PATH","/data/n01/procureflow_n01_progress.json"))
LOCK=RLock()
ID=re.compile(r"(?:R\d{2}BK\d{8}|\d{11})$")
MAX_PAGES=100
STAGE_IDS=tuple("N%02d"%i for i in range(1,10))

def _now():
    return datetime.now(ZoneInfo("Asia/Seoul")).isoformat()

def _key(bid_no,bid_ord):
    bid_no=str(bid_no or "").strip()
    bid_ord=str(bid_ord or "").strip()
    if not ID.fullmatch(bid_no) or not re.fullmatch(r"\d{3}",bid_ord):
        raise ValueError("INVALID_OFFICIAL_NOTICE_ID")
    return bid_no+"-"+bid_ord

def _load():
    if not LEDGER_PATH.exists():
        return {"version":1,"records":{}}
    data=json.loads(LEDGER_PATH.read_text(encoding="utf-8"))
    if (not isinstance(data,dict) or data.get("version")!=1
        or not isinstance(data.get("records"),dict)):
        raise ValueError("N01_COMPLETION_JOURNAL_UNREADABLE")
    return data

def _store(data):
    LEDGER_PATH.parent.mkdir(parents=True,exist_ok=True)
    tmp=LEDGER_PATH.with_name(LEDGER_PATH.name+"."+uuid.uuid4().hex+".tmp")
    try:
        tmp.write_text(json.dumps(data,ensure_ascii=False,separators=(",",":")),
                       encoding="utf-8")
        os.replace(tmp,LEDGER_PATH)
    finally:
        try:tmp.unlink(missing_ok=True)
        except OSError:pass

def completed(record):
    """Never skip 'completed_with_missing_evidence', partial or interrupted runs."""
    if not isinstance(record,dict):return False
    stages=record.get("stage_status")
    return (record.get("state")=="fully_verified"
            and isinstance(stages,dict)
            and all(stages.get(stage)=="verified" for stage in STAGE_IDS))

def select(fetch_page):
    """Return newest not fully verified, retrying previous incomplete entries.

    fetch_page(page_number) MUST perform a fresh official G2B request.
    All returned notices are eligible for this ordering rule; status alone
    does not mark a tender as completed or safe to skip.
    """
    with LOCK:
        journal=_load()
        records=journal["records"]
    seen=set()
    skipped=[]
    first_page=[]
    checked_pages=0
    for page in range(1,MAX_PAGES+1):
        rows=fetch_page(page)
        checked_pages=page
        if not isinstance(rows,list):
            raise ValueError("N01_OFFICIAL_LIST_BAD_SCHEMA")
        if page==1:first_page=rows[:20]
        for row in rows:
            if not isinstance(row,dict):continue
            key=_key(row.get("bid_no"),row.get("bid_ord"))
            if key in seen:continue
            seen.add(key)
            prior=records.get(key)
            if completed(prior):
                skipped.append(key)
                continue
            return {
              "selected":dict(row),
              "selection_reason":"retry_incomplete" if prior else "newest_unprocessed",
              "existing_checkpoint":({
                "state":prior.get("state"),
                "stage_status":dict(prior.get("stage_status") or {}),
                "attempts":int(prior.get("attempts") or 0)
              } if prior else None),
              "skipped_fully_verified":skipped,
              "skipped_completed_count":len(skipped),
              "scanned_pages":checked_pages,
              "latest_notice_rows":first_page,
              "latest_notice_count":len(first_page),
              "notice_list":"AVAILABLE",
              "search_request_verified":True,
              "verified_by":"official_g2b_websquare_list",
            }
        if len(rows)<20:
            raise ValueError("N01_ALL_DISCOVERED_NOTICES_FULLY_VERIFIED")
    raise ValueError("N01_SCAN_PAGE_LIMIT_REACHED_NO_UNFINISHED_NOTICE")

def record_stage(run,index,status):
    """Durable stage checkpoint. Only nine verified stages qualify as complete."""
    row=run.get("selected_notice")
    if not isinstance(row,dict):return
    key=_key(row.get("bid_no"),row.get("bid_ord"))
    if index not in range(1,10):raise ValueError("INVALID_N01_STAGE")
    stage="N%02d"%index
    with LOCK:
        ledger=_load()
        prior=ledger["records"].get(key) or {}
        same_run=prior.get("last_run_id")==run.get("run_id")
        status_map=dict(prior.get("stage_status") or {}) if same_run else {}
        status_map[stage]=status
        complete=all(status_map.get(k)=="verified" for k in STAGE_IDS)
        record={
          "bid_no":row["bid_no"],"bid_ord":row["bid_ord"],
          "title":str(row.get("title") or "")[:350],
          "agency":str(row.get("agency") or "")[:180],
          "source":"official_g2b_websquare_list",
          "first_seen_at":prior.get("first_seen_at") or _now(),
          "last_updated_at":_now(),
          "last_run_id":run.get("run_id"),
          "attempts":int(prior.get("attempts") or 0)+(0 if same_run else 1),
          "stage_status":status_map,
          "state":"fully_verified" if complete else "incomplete",
          "last_stage":stage,
        }
        ledger["records"][key]=record
        _store(ledger)
    run["completion_checkpoint"]={
        "key":key,"state":record["state"],
        "verified_stage_count":sum(s=="verified" for s in status_map.values()),
        "total_required_stages":9,
        "attempts":record["attempts"],
        "fully_completed":complete
    }
