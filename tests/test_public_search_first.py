"""Search-first source unit tests. Exercises production SQL/filter/controller code only.
No fake results are ever returned in deployed APIs; this stub is CI-only.
"""
import sys
from datetime import date
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import g2b_search_first as sf

class DB:
    def __init__(self):
        self.queries=[]
    def execute(self,sql,params=()):
        self.queries.append((sql,params))
        if "COUNT(*)::int AS total_rows" in sql:
            return Rows([{"total_rows":2,"source_notice_rounds":1,
                         "opening_rows":2,"confirmed_award_rows":0,"bidder_names":2}])
        if "r.bid_ntce_no AS bid_no" in sql:
            return Rows([{"bid_no":"R26BK01716629","bid_ord":"000",
                          "notice_date":date(2026,9,20),"agency":"실제 발주기관",
                          "historical_title":"공개된 개찰자료",
                          "result_kind":"opening","company":"실측업체",
                          "amount":"123000000","rate":"98.1","bid_rank":"1",
                          "result_status":"개찰","original_detail10_source":"https://www.g2b.go.kr/",
                          "original_detail10_sha256":"a"*64}])
        if "SELECT external_id,title,agency,notice_date" in sql:
            return Rows([{"external_id":"R26BK01787028","title":"원본 공고",
                          "agency":"전남테크노파크","notice_date":"2026-10-22",
                          "deadline":"2026-10-29 10:00","method":"소액수의",
                          "raw":{"bidNtceNo":"R26BK01787028",
                                 "dtilPrdctClsfcNo":"8111159901",
                                 "unrelated_secret":"must_not_return"},
                          "source_url":"https://www.g2b.go.kr/"}])
        if "FROM procureflow.g2b_case_documents" in sql:
            return Rows([{"file_id":"1","filename":"공고문.pdf","sha256":"b"*64,
                          "source_verified":True,"extraction_state":"parsed",
                          "extracted_chars":120,
                          "excerpt":"회사자격 및 제출요건을 포함하는 원본 공고문",
                          "original_url":"https://www.g2b.go.kr/"}])
        if "SELECT v.bid_no,v.bid_ord,h.published_on" in sql:
            return Rows([{"bid_no":"R26BK01716629","bid_ord":"000",
                          "published_on":date(2026,9,20)}])
        raise AssertionError("Unexpected SQL: "+sql[:100])

class Rows:
    def __init__(self,items): self.items=items
    def fetchone(self): return self.items[0] if self.items else None
    def fetchall(self): return self.items

s=sf.filters(start="2026-01-01",end="2026-10-22",
             kind="opening",agency=r"기관%_상세",limit=23,offset=10)
assert s.detail10=="8111159901"
db=DB()
response=sf.search_stored(s,connection=db)
assert response["real_records_only"] is True
assert response["total"]==2 and len(response["rows"])==1
assert response["official_ten_year_exhaustive"] is False
assert response["rows"][0]["bid_no"]=="R26BK01716629"
assert response["rows"][0]["notice_date"]=="2026-09-20"
query,params=db.queries[0]
assert "c.code_type='detail10'" in query
assert "c.evidence_level='official_direct'" in query
assert "h.published_on BETWEEN %s AND %s" in query
assert "r.result_kind=%s" in query
assert "h.agency ILIKE %s" in query
assert r"%\_\%" not in query
assert any(r"\%\_" in p for p in params if isinstance(p,str))
assert not any("기관%_상세" in sql for sql,_ in db.queries)
assert not any("g2b_case_10yr_windows" in sql for sql,_ in db.queries)
assert not any("120 months" in sql for sql,_ in db.queries)
assert db.queries[1][1][-2:]==(23,10)
assert response["has_more"] is False
source=sf.single_case_material(connection=db)
assert source["document_count"]==1 and source["redownloaded"] is False
assert source["notice"]["notice_fields"]["dtilPrdctClsfcNo"]=="8111159901"
assert "unrelated_secret" not in str(source)
assert len(db.queries)==4
combined=sf.actual_case_workbench(start="2026-01-01",end="2026-10-22",
                                  agency="전남",connection=DB())
assert combined["no_simulated_records"] is True
assert combined["filtered_before_result_fetch"] is True
assert combined["original_documents_reused"] is True
for kw in [{"detail10":"81111599"},
           {"detail10":"8111159902"},
           {"start":"2014-01-01"},
           {"end":"2026-11-03"},
           {"kind":"everything"},
           {"agency":"\x00"},
           {"limit":201},
           {"offset":50001},
           {"bid_no":"R26BK01787029"}]:
    try: sf.filters(**kw)
    except (ValueError, TypeError): pass
    else: raise AssertionError("Unsupported filter must be rejected: "+str(kw))
calls=[]
def actual_collector(**kwargs):
    calls.append(kwargs)
    return {"status":"collected","examined":2,"saved":2,"new":1,
            "final_winners":0,"errors":[]}
out=sf.collect_filtered_gaps(s,max_notices=1,collector=actual_collector,connection=DB())
assert out["source"]=="existing_real_g2b_bid_collector"
assert out["selected"]==1 and out["new_records"]==1
assert calls[0]["bid_numbers"]==["R26BK01716629-000"]
assert calls[0]["pages"]==1
assert out["explicit_final_awards"]==0 and out["bid_submitted"] is False
try:sf.collect_filtered_gaps(s,max_notices=999,collector=actual_collector,connection=DB())
except ValueError:pass
else:raise AssertionError("Unbounded collection allowed")
print("PUBLIC_REAL_SEARCH_FIRST_FILTERED_ORIGINAL_SQL_AND_ACTUAL_COLLECTOR_INTEGRATION_PASS")
