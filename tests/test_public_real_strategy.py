"""Real source-backed competitor and one-tender strategy contract tests.

Stubs replace SQL rows ONLY in isolated CI. Production uses live PostgreSQL,
never these values or simulated bidders/awards/strategy numbers.
"""
import sys
from pathlib import Path
from datetime import datetime, date
from zoneinfo import ZoneInfo
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from g2b_real_strategy import analyze_competition, _valid_deadline, _company_clean

class Rows:
    def __init__(self,rows): self.rows=rows
    def fetchone(self): return self.rows[0] if self.rows else None
    def fetchall(self): return self.rows

class SourceSQL:
    def __init__(self): self.queries=[]
    def execute(self,sql,params=()):
        self.queries.append((sql,params))
        if "SELECT external_id,title,agency,notice_date" in sql:
            return Rows([{"external_id":"R26BK01787028","title":"원본 입찰공고",
                 "agency":"재단법인전남테크노파크","notice_date":"2026-10-22",
                 "deadline":"2026-10-29 10:00","method":"소액수의견적",
                 "raw":{},"source_url":"https://bid24.kr/b/R26BK01787028"}])
        if "FROM procureflow.g2b_case_documents" in sql:
            return Rows([{"file_id":"1","filename":"공고문.hwp",
                 "sha256":"a"*64,"source_verified":True,
                 "extraction_state":"parsed","extracted_chars":80,
                 "excerpt":"입찰참가자격 및 견적서 제출방법을 확인하십시오.",
                 "content":"입찰참가자격 및 견적서 제출방법을 확인하십시오.",
                 "original_url":"https://www.g2b.go.kr/path"}])
        if "COUNT(*)::int AS total_rows" in sql:
            assert "r.result_kind=%s" in sql
            assert "award" in params
            return Rows([{"total_rows":0,"source_notice_rounds":0,
              "opening_rows":0,"confirmed_award_rows":0,"bidder_names":0}])
        if "r.bid_ntce_no AS bid_no" in sql:
            assert "award" in params
            return Rows([])
        if "GROUP BY r.company" in sql:
            return Rows([{"company":"&#40;주&#41;실제업체","opening_rows":3,
                 "distinct_notice_rounds":2,
                 "rank_one_openings_not_awards":1,
                 "rows_with_amount":2,
                 "latest_notice_date":date(2026,10,20)}])
        if "AS opening_rows" in sql and "COUNT(DISTINCT" in sql:
            # Distinguish same-agency audit from all-market aggregate.
            same="ILIKE" in sql
            return Rows([{"opening_rows":2 if same else 262,
                          "observed_notice_rounds":1 if same else 67,
                          "distinct_name_strings":1 if same else 206,
                          "rank_one_openings_not_awards":1 if same else 10,
                          "rows_with_numeric_amounts":1 if same else 156,
                          "rows_with_raw_rate":1 if same else 30}])
        raise AssertionError("Unexpected SQL: "+sql[:150])

now=datetime(2026,11,3,20,0,tzinfo=ZoneInfo("Asia/Seoul"))
con=SourceSQL()
result=analyze_competition("2026-01-01","2026-10-22",connection=con,now=now)
assert result["real_data_only"] and result["source"]=="existing_real_procureflow_g2b_openings"
assert result["observed"]["opening_rows"]==262
assert result["confirmed_award_observed"]["award_rows"]==0
assert result["observed"]["observed_notice_rounds"]==67
assert result["observed"]["rows_with_numeric_amounts"]==156
assert result["same_agency_filter"]=="전남테크노파크"
assert result["same_agency_observed"]["opening_rows"]==2
assert result["competitors_from_all_filtered_records"][0]["display_company"]=="(주)실제업체"
assert result["competitors_from_all_filtered_records"][0]["distinct_notice_rounds"]==2
assert result["strategy_inputs"]["recommended_bid_price"] is None
assert result["strategy_inputs"]["award_count_not_inferred_from_rank_one"] is True
assert result["full_decade_complete"] is False and result["bid_submitted"] is False
assert result["target_notice"]["deadline_passed"] is True
assert "소액수의견적" in result["strategy_inputs"]["document_type_guidance"]
assert any("개찰" in x for x in result["analysis_limitations"])
assert any("CASE WHEN r.amount" in q for q,_ in con.queries)
assert any("CASE WHEN r.rate" in q for q,_ in con.queries)
assert any("GROUP BY r.company" in q for q,_ in con.queries)
assert all("verified_exact_10" in q for q,_ in con.queries if "bid_results r" in q)
assert all("evidence_level='official_direct'" in q for q,_ in con.queries if "bid_results r" in q)
assert any("r.result_kind=%s" in q for q,_ in con.queries)
assert _valid_deadline("2026-10-29 10:00") is not None
assert _valid_deadline("abc") is None
assert _company_clean("&#40;주&#41;실제업체")=="(주)실제업체"
try:analyze_competition("2015-01-01","2026-10-22",connection=SourceSQL(),now=now)
except ValueError:pass
else:raise AssertionError("Outside-source-period strategy search accepted")
print("REAL_G2B_ALL_RESULT_COMPETITOR_AGGREGATION_SAME_AGENCY_SOURCE_BID_PREP_NO_FAKE_AWARD_PASS")
