"""Actual ten-year per-year coverage for the selected G2B 8111159901 outcome case.

Only original-document-verified detail code AND a real opening/award record
qualifies. Unsearched periods are unknown, NEVER presented as zero bids.
"""
from db import session
from g2b_exact_outcome_history import DETAIL,CASE_BID,BEGIN,END,ensure_schema

def coverage_by_year():
    ensure_schema()
    with session() as db:
        rows=db.execute("""SELECT EXTRACT(YEAR FROM h.published_on)::int AS year,
                 count(DISTINCT (v.bid_no,v.bid_ord)) AS exact_notices,
                 count(DISTINCT (v.bid_no,v.bid_ord))
                    FILTER(WHERE r.result_kind='opening') AS notices_with_opening,
                 count(*) FILTER(WHERE r.result_kind='opening') AS bidder_rows,
                 count(*) FILTER(WHERE r.result_kind='opening'
                    AND r.amount IS NOT NULL AND r.amount<>'') AS bid_price_rows,
                 count(*) FILTER(WHERE r.result_kind='award') AS final_award_rows
               FROM procureflow.g2b_case_outcome_verification v
               JOIN procureflow.g2b_notice_categories c ON
                 c.bid_no=v.bid_no AND c.bid_ord=v.bid_ord
                 AND c.code_type='detail10' AND c.code=%s
                 AND c.evidence_level='official_direct'
               JOIN procureflow.g2b_case_10yr_history h ON
                 h.case_bid_no=v.case_bid_no
                 AND h.hist_notice_no=v.bid_no AND h.hist_notice_ord=v.bid_ord
               LEFT JOIN procureflow.bid_results r ON
                 r.source='g2b' AND r.bid_ntce_no=v.bid_no
                 AND r.bid_ntce_ord=v.bid_ord
                 AND r.result_kind IN ('opening','award')
               WHERE v.case_bid_no=%s AND v.status='verified_exact_10'
                 AND h.published_on BETWEEN %s AND %s AND v.bid_no<>%s
               GROUP BY 1 ORDER BY 1""",
               (DETAIL,CASE_BID,BEGIN,END,CASE_BID)).fetchall()
        windows=db.execute("""SELECT count(*) FILTER(WHERE status='completed') AS completed,
                  count(*) AS total FROM procureflow.g2b_case_10yr_windows
                  WHERE case_bid_no=%s""",(CASE_BID,)).fetchone()
        classes=db.execute("""SELECT count(*) AS n
                  FROM procureflow.g2b_case_10yr_history
                  WHERE case_bid_no=%s AND classification8='81111599'
                  AND published_on BETWEEN %s AND %s""",
                  (CASE_BID,BEGIN,END)).fetchone()
    index={int(x["year"]):x for x in rows}
    years=[]
    for year in range(2016,2027):
        row=index.get(year,{})
        years.append({"year":year,
            "verified_exact10_notice_rounds":int(row.get("exact_notices") or 0),
            "notices_with_opening":int(row.get("notices_with_opening") or 0),
            "actual_bidder_rows":int(row.get("bidder_rows") or 0),
            "actual_bid_price_rows":int(row.get("bid_price_rows") or 0),
            "confirmed_award_rows":int(row.get("final_award_rows") or 0),
            "comprehensive_year_coverage":False,
            "zero_means_no_verified_result_not_zero_actual_bids":True})
    return {"bid_no":CASE_BID,"detail_product_code":DETAIL,
            "from":BEGIN.isoformat(),"to":END.isoformat(),
            "years":years,
            "category8_candidate_notices_excluded_from_results":classes["n"],
            "official_complete_months":int(windows["completed"] or 0),
            "official_total_months":int(windows["total"] or 0),
            "ten_year_outcome_coverage_complete":False,
            "proof_required":["original ten-digit item code",
                              "exact bid number and revision",
                              "official opening bidder list",
                              "explicit final award status and final winner"]}
