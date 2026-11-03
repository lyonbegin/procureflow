"""Real (not fabricated) G2B source-records presentation contract, offline CI."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"n8n/strategy-runtime"))
import procurement_actual_records as actual
case="R26BK01787028"
fixture={
 "outcomes":{
  "target_bid_no":case,"exact_detail_product_code":"8111159901",
  "period_start":"2016-10-24","period_end":"2026-10-24",
  "candidate_notice_count_not_results":444,
  "verified_exact_code_history_and_result_counts":{
    "verified_notice_rounds":238,"opening_bidder_rows":246,
    "opening_amount_rows":156,"confirmed_award_rows":0},
  "verification_states":[{"status":"verified_exact_10","n":238}],
  "ten_year_coverage_completed":False,
  "actual_opening_and_award_rows":[{"bid_ntce_no":"R26BK01779514",
    "bid_ntce_ord":"000","result_kind":"opening","company":"주식회사 액츠원",
    "amount":"168500000","rate":"99.763","rank":"1",
    "detail_code_original_url":"https://www.g2b.go.kr/pn/pnp/pnpe/UntyAtchFile/downloadFile.do?bidPbancNo=R26BK01779514",
    "detail_code_original_sha256":"c4c759f977b18630529b1966f10b57f2c92fa3fefaf43c35325ea69dcd6f17cc"}],
 },
 "documents":{"bid_no":case,"files_listed":4,"files_downloaded":4,
   "original_index":[{"file_label":"1. 공고문.pdf",
     "source_url":"https://www.g2b.go.kr/pn/pnp/pnpe/UntyAtchFile/downloadFile.do?bidPbancNo=R26BK01787028",
     "content_sha":"a"*64,"bytes_size":600000,"state":"parsed"}]},
 "schedule":{"official_api_key_present":False},
 "price":{"status":"blocked","missing":["cost_breakdown","price_rules","supplier_quotes"],
          "eligibility":"unknown","recommended_bid_price":None},
 "context":{"bid_no":case,"bid_ord":"000","title":"원본 기록으로 수집한 SW 개발 용역",
            "agency":"재단법인전남테크노파크","deadline":"2026-10-29 10:00",
            "method":"소액수의견적","original_notice_verified":False,"official_detail10":[]}
}
calls=[]
def fetch(key):
    calls.append(key)
    return fixture[key]
value=actual.read_actual(fetcher=fetch)
assert set(calls)==set(actual.PATHS)
assert all(path.startswith("/api/") for path in actual.PATHS.values())
assert len(calls)==5
assert value["mode"]=="actual_existing_g2b_records"
assert value["candidate_notices_not_results"]==444
assert value["actual_counts"]["verified_notice_rounds"]==238
assert value["actual_counts"]["opening_bidder_rows"]==246
assert value["actual_counts"]["opening_amount_rows"]==156
assert value["actual_counts"]["confirmed_award_rows"]==0
assert value["official_api_key_present"] is False
assert value["ten_year_coverage_complete"] is False
assert value["real_recommended_price"] is None
assert value["documents_downloaded"]==4
assert len(value["actual_opening_rows"])==1
assert value["actual_opening_rows"][0]["company"]=="주식회사 액츠원"
assert value["actual_opening_rows"][0]["kind"]=="opening"
assert value["new_collection_started"] is False and value["bid_submitted"] is False
for kind in ("evil","full/run","../api"):
 try:actual._get(kind)
 except ValueError:pass
 else:raise AssertionError("Disallowed API path")
import copy
wrong=copy.deepcopy(fixture);wrong["context"]["bid_no"]="R26BK01787029"
try:actual.read_actual(fetcher=lambda key:wrong[key])
except ValueError as e:assert "CROSS_TENDER" in str(e)
else:raise AssertionError("Cross-case leak")
wrong=copy.deepcopy(fixture);wrong["outcomes"]["verified_exact_code_history_and_result_counts"]["confirmed_award_rows"]=-1
try:actual.read_actual(fetcher=lambda key:wrong[key])
except ValueError as e:assert "INVALID_REAL_COUNT" in str(e)
else:raise AssertionError("Bad count accepted")
class Resp:
 status=200
 headers={"content-type":"application/json"}
 def __enter__(self):return self
 def __exit__(self,*args):pass
 def read(self,n):return b'{"bid_no":"R26BK01787028"}'
class Open:
 def open(self,request,timeout):
    assert request.get_method()=="GET"
    assert request.full_url==actual.API+actual.PATHS["documents"]
    return Resp()
assert actual._get("documents",opener=Open())=={"bid_no":case}
print("ACTUAL_G2B_444_CANDIDATE_238_VERIFIED_246_OPENING_156_AMOUNT_4_SOURCE_FILES_NO_FAKE_NOR_BID_PASS")
