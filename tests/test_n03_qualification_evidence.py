"""N03: official document requirements, source provenance, no fake company eligibility."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"n8n/unified"))
import n03_eligibility as n03
import live_nine_test as live

SOURCE="https://www.g2b.go.kr/pn/pnp/pnpe/UntyAtchFile/downloadFile.do"
HASH="a04c1319dd635fb1d8f6135f2ea13362acba6baf35b1e3ccac1c9a4bc4294189"
RAW="""3. 입찰내용
다. 입찰방법 : 전자입찰에 따른 일반경쟁입찰(컨소시엄 불가)
4. 입찰 참여 자격
가. 「도시 및 주거환경정비법」제102조의 규정에 의한 정비사업전문관리업자
나. 공동참여 불가
다. 입찰 마감 전까지 국가종합전자조달시스템에 입찰가격 투찰을 완료하고,
주민대표단에 입찰서류를 직접 제출한 업체(우편 및 팩스 접수 불가)
라. 위 조건을 충족하고 입찰 마감 전까지 입찰서류를 제출한 업체
7. 입찰 방법 및 선정 방법
입찰 마감 2026년 11월 16일(월요일) 10시
【제3조】 입찰 참여 신청 서류
① 입찰자는 발주자가 지정한 기간 안에 나라장터에서 투찰한다.
1. 입찰 참여신청서 (별지 서식 1)
2. 이행각서 (별지 서식 2)
3. 정비사업수행실적서
4. 정비사업전문관리업 등록증 사본 1부
5. 국세 및 지방세 완납 증명서
※ 모든 제출서류가 포함된 전자파일을 USB로 제출
【제4조】 입찰서류의 작성방법
"""
def manifest(text=RAW):
    return [{"file_seq":2,"source":SOURCE,
             "sha256":HASH,"text_chars":len(text),"format":"pdf"}]

class TestN03(unittest.TestCase):
    def test_structures_official_qualification_and_documents_with_line_provenance(self):
        out=n03.analyze(manifest(),[RAW])
        self.assertEqual(out["document_requirement_extraction"],"verified")
        self.assertGreaterEqual(out["qualification_rule_count"],3)
        self.assertEqual(out["required_document_count"],5)
        self.assertTrue(any("정비사업전문관리업자" in r["text"] for r in out["qualification_rules"]))
        self.assertTrue(any(r["number"]==4 and "등록증" in r["text"] for r in out["required_documents"]))
        self.assertTrue(any("2026년 11월 16일" in x["text"] for x in out["bid_deadlines"]))
        for row in out["qualification_rules"]+out["required_documents"]:
            self.assertEqual(row["file_seq"],2)
            self.assertEqual(row["source_file_sha256"],HASH)
            self.assertGreater(row["line_start"],0)
            self.assertGreaterEqual(row["line_end"],row["line_start"])

    def test_cannot_claim_company_is_eligible_from_public_attachments(self):
        out=n03.analyze(manifest(),[RAW])
        self.assertEqual(out["company_eligibility"],"NOT_VERIFIED_NO_COMPANY_ORIGINAL")
        self.assertFalse(out["company_eligibility_verified"])
        self.assertEqual(out["reason"],"OFFICIAL_DOCUMENT_REQUIREMENTS_EXTRACTED_COMPANY_EVIDENCE_UNAVAILABLE")

    def test_missing_qualification_heading_does_not_invent_rules(self):
        content="수행계획서\n일정\n별지 서식"
        out=n03.analyze(manifest(content),[content])
        self.assertEqual(out["qualification_rules"],[])
        self.assertEqual(out["document_requirement_extraction"],"not_verified")
        self.assertFalse(out["company_eligibility_verified"])

    def test_manifest_mismatch_is_a_real_error(self):
        with self.assertRaisesRegex(ValueError,"N03_TEXT_AND_ORIGINAL_MANIFEST_COUNT_MISMATCH"):
            n03.analyze(manifest(),[])
        with self.assertRaisesRegex(ValueError,"N03_INVALID_OFFICIAL_DOCUMENT_HASH"):
            n03.analyze([{"file_seq":1,"sha256":"garbage","text_chars":10}],["abcde"])

    def test_n03_is_connected_to_real_nine_stage_runner_only(self):
        from tempfile import TemporaryDirectory
        import n01_auto
        from unittest.mock import patch
        with TemporaryDirectory() as tmp, patch.object(n01_auto,"LEDGER_PATH",Path(tmp)/"progress.json"):
            job={"run_id":"a"*32,"status":"running","mode":"on_demand_live_no_database",
                 "case_bid_no":None,"case_bid_ord":None,"completed_steps":0,
                 "partial_steps":0,"steps":[],"db_reads":0,"worker_calls":0,
                 "bid_submitted":False}
            notice={"bid_no":"R26BK01816186","bid_ord":"000","title":"실제 공고",
                    "agency":"실제 발주기관","notice_list":"AVAILABLE",
                    "official_fields_verified":True,"selection_reason":"newest_unprocessed"}
            files=manifest()
            with patch.object(live,"_client",return_value=None), \
                 patch.object(live,"_once"), \
                 patch.object(live,"_live_notice",return_value=notice), \
                 patch.object(live,"_live_attachments",return_value=(files,[RAW])), \
                 patch.object(live,"_live_openings",return_value={"official_rows":0}), \
                 patch.object(live,"_document",return_value=b"docx"):
                live._execute(job)
            record=next(x for x in job["steps"] if x["node"]=="N03")
            self.assertEqual(record["status"],"partial")
            self.assertGreaterEqual(record["output"]["required_document_count"],5)
            self.assertFalse(record["output"]["company_eligibility_verified"])
            self.assertNotIn("requirement_keywords",record["output"])
            self.assertFalse(job["completion_checkpoint"]["fully_completed"])
            self.assertEqual(job["case_bid_no"],notice["bid_no"])

if __name__=="__main__":unittest.main()
