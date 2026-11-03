"""Safety/format CI for production nine-stage actual-source Worker and DOCX.

Only isolated unit inputs exercise output formatting. Deployed implementation
reads the original PostgreSQL and NEVER returns these CI values.
"""
import io,sys,zipfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from g2b_real_strategy import classify_public_preparation
from g2b_bid_package import draft_docx
from docx import Document

strategy={"status":"actual_opening_comparison_available",
  "target_notice":{"title":"선택 공고","agency":"기관","method":"소액수의견적",
                   "deadline_passed":True},
  "case_bid_no":"R26BK01787028","source_document_count":1,
  "document_clause_count":1,
  "observed":{"opening_rows":3,"observed_notice_rounds":2,
     "distinct_name_strings":2,"rows_with_numeric_amounts":1,
     "rank_one_openings_not_awards":1},
  "confirmed_award_observed":{"award_rows":0},
  "competitors_from_all_filtered_records":[
     {"company":"&#40;주&#41;원본기업","distinct_notice_rounds":1,
      "opening_rows":1,"rank_one_openings_not_awards":1}],
  "filters":{"start":"2026-01-01","end":"2026-10-22"},
  "analysis_limitations":["개찰 1순위는 낙찰 확정이 아닙니다."]
}
elig={"status":"unknown","passed":False}
price={"status":"blocked","missing":["cost_breakdown","price_rules"],
       "eligibility":"unknown","recommended_bid_price":None,
       "scenarios":[]}
package={"bid_no":"R26BK01787028","title":"선택 공고","agency":"기관",
         "date":"2026-10-22","deadline":"2026-10-29","method":"소액수의견적",
         "eligibility":elig,"price":price,
         "stage":"draft_only_not_a_g2b_submission",
         "document_index":[{"filename":"원본 공고문.hwp","sha256":"f"*64,
                            "extraction_state":"parsed"}],
         "evidence_references":[],
         "readiness":{"phases":[{"ready":False,"key":"eligibility",
                                  "missing_evidence":["company_registration"]}]}}
r=classify_public_preparation(strategy,elig,price,package)
assert r["status"]=="CLOSED_HISTORICAL_ANALYSIS_ONLY"
assert len(r["steps"])==9
assert r["steps"][3]["actual_opening_rows"]==3
assert r["analysis_warnings"] and any("10년" in s for s in r["analysis_warnings"])
assert all("10년" not in s for s in r["hard_blockers"])
assert any("원가" in s for s in r["hard_blockers"])
assert r["requires_human_final_approval"] and r["bid_submitted"] is False
assert r["price_recommendation"] is None
strategy["target_notice"]["deadline_passed"]=False
assert classify_public_preparation(strategy,elig,price,package)["status"]=="HOLD_REQUIREMENTS"
elig={"status":"ineligible","passed":False}
assert classify_public_preparation(strategy,elig,price,package)["status"]=="NO_BID"
verified=[{"evidence_type":x,"verified_source":True} for x in
          ("notice_official","required_forms","final_validation")]
package["evidence_references"]=verified
elig={"status":"eligible","passed":True}
price={"status":"draft_computed_not_approved","missing":[],
       "eligibility":"eligible","recommended_bid_price":None,
       "scenarios":[]}
out=classify_public_preparation(strategy,elig,price,package)
assert out["status"]=="MANUAL_FINAL_APPROVAL_REQUIRED"
assert out["hard_blockers"]==[]
assert out["requires_human_final_approval"] and out["bid_submitted"] is False

# Validate a Word document can actually be generated with the source-backed
# section, verified file hashes and clear draft-only warnings.
docx,data=draft_docx(contents=package,strategy=strategy,
       source_clauses=[{"category":"제출서류","original_filename":"원본 공고문.hwp",
                        "original_sha256":"f"*64,
                        "text":"전자견적서 제출방법은 원본 공고문에 명시됩니다."}])
assert docx[:2]==b"PK" and len(docx)>5000
document=Document(io.BytesIO(docx))
paragraphs="\n".join(p.text for p in document.paragraphs)
assert "원본 검증 과거 개찰" in paragraphs
assert "(주)원본기업" in paragraphs
assert "공식 확정 낙찰 기록: 0" in paragraphs
assert "원본 SHA256:" in paragraphs
assert "제출된 입찰서가 아니라" in paragraphs
assert "투찰금액 및 참가자격 검증 완료 전" in paragraphs
with zipfile.ZipFile(io.BytesIO(docx)) as z:
 assert "word/document.xml" in z.namelist()

from g2b_public_workflow import STEPS,DRAFT_MEDIA
assert len(STEPS)==9 and STEPS[9]=="manual_readiness"
assert "wordprocessingml" in DRAFT_MEDIA
print("REAL_PUBLIC_9_STAGE_READINESS_104_NOT_GATE_SOURCE_DOCX_SAFETY_CI_PASS")
