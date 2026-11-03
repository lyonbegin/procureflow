"""Search-first REAL procurement case retrieval; reuses existing G2B PostgreSQL.

One selected actual notice -> one cached original/document snapshot -> SQL filter
by verified 10-digit detail and dates -> existing opening/final-award records.
No fixture, 121-month bootstrap, fake awards, or bid submission.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
import re

from db import session
from g2b_case_10y import CASE_BID, CASE_ORD, SUB10, BEGIN, END

ID = re.compile(r"^(?:R\d{2}BK\d{8}|\d{11})$")
TEN = re.compile(r"^\d{10}$")
ALLOWED_KINDS = ("all", "opening", "award")
MAX_LIMIT = 200
# Only information available by the selected notice publication date may be
# used to reconstruct its competitive decision. Exclude later outcomes.
SELECTED_PUBLICATION_CUTOFF = date(2026, 10, 22)


@dataclass(frozen=True)
class Search:
    bid_no: str
    detail10: str
    start: date
    end: date
    kind: str = "all"
    agency: str = ""
    limit: int = 50
    offset: int = 0


def filters(bid_no=CASE_BID, detail10=SUB10, start=None, end=None,
            kind="all", agency="", limit=50, offset=0):
    # The current original case engine supports exactly one tender.
    # Never silently analyze a different tender under this case's evidence.
    if bid_no != CASE_BID or not ID.fullmatch(str(bid_no)):
        raise ValueError("SELECTED_TENDER_NOT_SUPPORTED_BY_EXISTING_ENGINE")
    if not isinstance(detail10, str) or not TEN.fullmatch(detail10) or detail10 != SUB10:
        raise ValueError("TEN_DIGIT_DETAIL_MUST_MATCH_SELECTED_CASE")
    first = date.fromisoformat(start) if isinstance(start, str) else (start or BEGIN)
    last = date.fromisoformat(end) if isinstance(end, str) else (end or min(END, SELECTED_PUBLICATION_CUTOFF))
    if not isinstance(first, date) or not isinstance(last, date) or first > last:
        raise ValueError("INVALID_SEARCH_PERIOD")
    if first < BEGIN or last > min(END, SELECTED_PUBLICATION_CUTOFF):
        raise ValueError("SEARCH_OUTSIDE_SELECTED_CASE_HISTORICAL_PERIOD")
    if kind not in ALLOWED_KINDS:
        raise ValueError("INVALID_RESULT_KIND")
    if not isinstance(agency, str) or len(agency) > 100 or any(ord(c) < 32 for c in agency):
        raise ValueError("INVALID_AGENCY_FILTER")
    if not isinstance(limit, int) or not 1 <= limit <= MAX_LIMIT:
        raise ValueError("INVALID_LIMIT")
    if not isinstance(offset, int) or not 0 <= offset <= 50000:
        raise ValueError("INVALID_OFFSET")
    return Search(bid_no, detail10, first, last, kind, agency.strip(), limit, offset)


def _where(s: Search):
    # Match exactly verified official original detail-10 first. An 8-digit
    # candidate alone is never part of these opening/award results.
    sql = """FROM procureflow.g2b_case_outcome_verification v
    JOIN procureflow.g2b_case_10yr_history h
      ON h.case_bid_no=v.case_bid_no
     AND h.hist_notice_no=v.bid_no AND h.hist_notice_ord=v.bid_ord
    JOIN procureflow.g2b_notice_categories c
      ON c.bid_no=v.bid_no AND c.bid_ord=v.bid_ord
     AND c.code_type='detail10' AND c.code=%s
     AND c.evidence_level='official_direct'
    JOIN procureflow.bid_results r
      ON r.source='g2b' AND r.bid_ntce_no=v.bid_no
     AND r.bid_ntce_ord=v.bid_ord
     AND r.result_kind IN ('opening','award')
    WHERE v.case_bid_no=%s AND v.expected_detail10=%s
      AND v.status='verified_exact_10'
      AND h.published_on BETWEEN %s AND %s
      AND h.hist_notice_no<>%s"""
    args = [s.detail10, s.bid_no, s.detail10, s.start, s.end, s.bid_no]
    if s.kind != "all":
        sql += " AND r.result_kind=%s"
        args.append(s.kind)
    if s.agency:
        # Escape LIKE wildcards so '%' entered by an operator is literal.
        escaped = s.agency.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        sql += r" AND h.agency ILIKE %s ESCAPE '\'"
        args.append("%" + escaped + "%")
    return sql, args


def _json_row(row):
    def plain(val):
        if isinstance(val, date): return val.isoformat()
        if isinstance(val, Decimal): return str(val)
        return val
    return {key: plain(value) for key, value in dict(row).items()}


def _cached_search(con, s: Search):
    where, args = _where(s)
    summary = con.execute("""SELECT COUNT(*)::int AS total_rows,
          COUNT(DISTINCT (v.bid_no,v.bid_ord))::int AS source_notice_rounds,
          COUNT(*) FILTER(WHERE r.result_kind='opening')::int AS opening_rows,
          COUNT(*) FILTER(WHERE r.result_kind='award')::int AS confirmed_award_rows,
          COUNT(DISTINCT r.company) FILTER(WHERE r.result_kind='opening')::int AS bidder_names
       """ + where, tuple(args)).fetchone()
    records = con.execute("""SELECT
           r.bid_ntce_no AS bid_no,r.bid_ntce_ord AS bid_ord,
           h.published_on AS notice_date,h.agency AS agency,
           h.title AS historical_title,r.result_kind AS result_kind,
           r.company AS company,r.amount AS amount,r.rate AS rate,
           r.rank AS bid_rank,r.result_status AS result_status,
           c.source_uri AS original_detail10_source,
           v.original_sha256 AS original_detail10_sha256
       """ + where +
       """ ORDER BY h.published_on DESC,r.bid_ntce_no,
           r.bid_ntce_ord,r.result_kind,r.rank,r.record_key
           LIMIT %s OFFSET %s""", tuple(args + [s.limit,s.offset])).fetchall()
    return _json_row(summary), [_json_row(x) for x in records]


def search_stored(s: Search, *, connection=None):
    """One filtered, paginated DB query of *real* collected G2B outcome rows.

    No external fetch is implied by the number of historical years selected.
    The function neither creates month windows nor collects unrelated notices.
    """
    if connection is None:
        with session() as con:
            return search_stored(s, connection=con)
    summary, records = _cached_search(connection,s)
    return {
      "case_bid_no":s.bid_no,"case_bid_ord":CASE_ORD,
      "exact_detail10":s.detail10,
      "filters":{"start":s.start.isoformat(),"end":s.end.isoformat(),
                 "kind":s.kind,"agency":s.agency,"limit":s.limit,"offset":s.offset},
      "source":"existing_procureflow_original_verified_10digit_outcomes",
      "real_records_only":True,"external_requests":0,
      "total":summary["total_rows"],"summary":summary,"rows":records,
      "has_more":s.offset+len(records)<summary["total_rows"],
      "official_ten_year_exhaustive":False,
      "note":"Only existing source-verified 10-digit original G2B rows. Search range is a filter, not a 10-year corpus-complete claim.",
      "bid_submitted":False
    }


def single_case_material(*, connection=None):
    """One query of selected notice + one query of already-acquired source files.

    The source-file text is parsed once by the existing g2b_documents collector.
    Reuse its indexed hashes and extract excerpts, never re-download same files
    for every field or each F001–F104 contract.
    """
    if connection is None:
        with session() as con:
            return single_case_material(connection=con)
    row=connection.execute("""SELECT external_id,title,agency,notice_date,
          deadline,method,raw,source_url
          FROM procureflow.tenders WHERE source='g2b' AND external_id=%s
          LIMIT 1""",(CASE_BID,)).fetchone()
    if not row:
        return {"status":"not_found","case_bid_no":CASE_BID,
                "source":"existing_procureflow_db","bid_submitted":False}
    files=connection.execute("""SELECT d.file_id,d.filename,d.sha256,
       d.source_verified,d.extraction_state,
       length(d.extracted_text) AS extracted_chars,
       LEFT(d.extracted_text,5000) AS excerpt,
       d.url AS original_url
       FROM procureflow.g2b_case_documents d
       WHERE d.bid_no=%s AND d.bid_ord=%s
       ORDER BY d.file_id LIMIT 80""",(CASE_BID,CASE_ORD)).fetchall()
    clean=_json_row(row)
    # The raw official notice may include unrelated/private fields. Return only
    # supported original field values, not a full raw JSON dump.
    raw=clean.pop("raw",{}) or {}
    clean["notice_fields"]={key:raw.get(key) for key in
       ("bidNtceNo","bidNtceOrd","bidNtceNm","bidNtceDt",
        "bidClseDt","dminsttNm","ntceInsttNm","cntrctCnclsMthdNm",
        "sucsfbidMthdNm","asignBdgtAmt","bdgtAmt","presmptPrce","prdctClsfcNo","dtilPrdctClsfcNo")
       if key in raw}
    return {"status":"found","case_bid_no":CASE_BID,"case_bid_ord":CASE_ORD,
       "notice":clean,"documents":[_json_row(x) for x in files],
       "retrieval":"one_cached_notice_query_and_one_cached_documents_query",
       "document_count":len(files),"redownloaded":False,
       "source":"existing_procureflow_db","bid_submitted":False}


def actual_case_workbench(start=None, end=None, kind="all", agency="",
                          limit=50, offset=0, *, connection=None):
    """One response containing notice, acquired file excerpts and filtered REAL history."""
    selection=filters(start=start,end=end,kind=kind,agency=agency,limit=limit,offset=offset)
    if connection is None:
        with session() as con:
            return actual_case_workbench(start,end,kind,agency,limit,offset,connection=con)
    case=single_case_material(connection=connection)
    results=search_stored(selection,connection=connection)
    return {"mode":"real_one_tender_search_first",
            "case":case,"history":results,
            "filtered_before_result_fetch":True,
            "original_documents_reused":True,
            "source":"existing_procureflow_postgresql",
            "no_simulated_records":True,
            "bid_participation_clicked":False,"bid_submitted":False}


def collect_filtered_gaps(s: Search, max_notices=3, *, collector=None,
                          connection=None):
    """Actually query G2B public opening for a FEW exact verified notice IDs.

    This reuses the working g2b_bid_collector.collect(bid_numbers=...), rather
    than discovering all notices for all months and filtering afterwards.
    Every attempt and actual outcome is persisted by the original collector.
    A lack of confirmed awards is never fabricated into successful results.
    Run this ONLY in the original authenticated Railway worker.
    """
    if not isinstance(max_notices,int) or not 1<=max_notices<=3:
        raise ValueError("MAX_THREE_SELECTED_NOTICES_PER_JOB")
    if connection is None:
        with session() as con:
            candidates=_filtered_gaps(con,s,max_notices)
    else:
        candidates=_filtered_gaps(connection,s,max_notices)
    if not candidates:
        return {"status":"no_uncollected_verified_records_in_filter",
            "case_bid_no":s.bid_no,"selected":0,"actual_g2b_requests":0,
            "results":[],"bid_submitted":False}
    if collector is None:
        from g2b_bid_collector import collect
        collector=collect
    selected=[x["bid_no"]+"-"+x["bid_ord"] for x in candidates]
    # A direct exact-ID opening query does not discover an unrelated listing,
    # even when the public site's general listing filters are weaker than SQL.
    out=collector(days=1,pages=1,bid_numbers=selected)
    if not isinstance(out,dict):
        raise ValueError("EXISTING_G2B_COLLECTOR_INVALID_RESPONSE")
    if connection is None:
        with session() as con:
            _save_filtered_attempts(con,candidates,out)
    else:
        _save_filtered_attempts(connection,candidates,out)
    return {"status":out.get("status","unknown"),
        "case_bid_no":s.bid_no,"exact_detail10":s.detail10,
        "selected":len(selected),"selected_notice_ids":selected,
        "actual_g2b_requests":len(selected),
        "actual_opening_rows_seen":out.get("examined",0),
        "actual_saved_records":out.get("saved",0),
        "new_records":out.get("new",0),
        "explicit_final_awards":out.get("final_winners",0),
        "source":"existing_real_g2b_bid_collector",
        "errors":out.get("errors",[]),
        "bid_submitted":False,
        "note":"Only real original-verified 10-digit selected notices; no entire ten-year loop."}


def _filtered_gaps(con, s: Search, limit: int):
    if s.detail10 != SUB10:
        raise ValueError("DETAIL_MISMATCH")
    sql="""SELECT v.bid_no,v.bid_ord,h.published_on
      FROM procureflow.g2b_case_outcome_verification v
      JOIN procureflow.g2b_case_10yr_history h
        ON h.case_bid_no=v.case_bid_no
       AND h.hist_notice_no=v.bid_no AND h.hist_notice_ord=v.bid_ord
      JOIN procureflow.g2b_notice_categories c
        ON c.bid_no=v.bid_no AND c.bid_ord=v.bid_ord
       AND c.code_type='detail10' AND c.code=%s
       AND c.evidence_level='official_direct'
      WHERE v.case_bid_no=%s AND v.expected_detail10=%s
        AND v.status='verified_exact_10'
        AND h.published_on BETWEEN %s AND %s
        AND h.hist_notice_no<>%s
        AND NOT EXISTS (
          SELECT 1 FROM procureflow.g2b_case_outcome_attempts a
          WHERE a.case_bid_no=v.case_bid_no AND a.bid_no=v.bid_no
            AND a.bid_ord=v.bid_ord AND a.stage='opening_collection'
            AND a.created_at>now()-interval '12 hours'
        )
        AND NOT EXISTS (
          SELECT 1 FROM procureflow.bid_results r
          WHERE r.source='g2b' AND r.bid_ntce_no=v.bid_no
            AND r.bid_ntce_ord=v.bid_ord AND r.result_kind='award'
        )"""
    args=[s.detail10,s.bid_no,s.detail10,s.start,s.end,s.bid_no]
    if s.agency:
        escaped=s.agency.replace("\\","\\\\").replace("%","\\%").replace("_","\\_")
        sql+=r" AND h.agency ILIKE %s ESCAPE '\'"
        args.append("%"+escaped+"%")
    sql+=" ORDER BY h.published_on DESC,v.bid_no LIMIT %s"
    args.append(limit)
    return [_json_row(x) for x in con.execute(sql,tuple(args)).fetchall()]


def _save_filtered_attempts(con, candidates, collector_output):
    """Persist *real* per-ID outcome, even when the public detail is unavailable.

    The original _filtered_gaps excludes attempts from the previous 12 hours.
    No inferred bidder/award is created when the official site has no detail.
    """
    saved={(x.get("bid_no"),x.get("bid_ord")):x
            for x in collector_output.get("bid_details",[])
            if isinstance(x,dict)}
    unavailable=set(collector_output.get("unavailable_details",[]))
    errors=collector_output.get("errors",[])
    for row in candidates:
        bid=row["bid_no"];ord_=row["bid_ord"]
        detail=saved.get((bid,ord_))
        if detail is not None:
            status="received_opening"
            body={"bid_no":bid,"bid_ord":ord_,
                  "actual_bidders":int(detail.get("bidders") or 0),
                  "saved":int(detail.get("saved") or 0),
                  "new":int(detail.get("new") or 0),
                  "winner_confirmed":bool(detail.get("winner_confirmed",False))}
        elif bid in unavailable:
            status="public_opening_unavailable"
            body={"bid_no":bid,"bid_ord":ord_,"actual_bidders":0,
                  "reason":"original_g2b_opening_detail_not_published"}
        else:
            status="error" if errors else "no_opening_rows"
            body={"bid_no":bid,"bid_ord":ord_,"actual_bidders":0,
                  "errors":[str(x)[:150] for x in errors[:3]]}
        from json import dumps
        con.execute("""INSERT INTO procureflow.g2b_case_outcome_attempts(
           case_bid_no,bid_no,bid_ord,stage,status,detail)
           VALUES (%s,%s,%s,'opening_collection',%s,%s::jsonb)""",
           (CASE_BID,bid,ord_,status,dumps(body,ensure_ascii=False)))
