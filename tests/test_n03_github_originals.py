"""N03 must actually inspect verified N02 originals on the GitHub runner.

This deterministic suite never uses a fake procurement DB or claims bidder
eligibility from source-side requirements alone.
"""
import hashlib,os,sys,unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"n8n/unified"))
import n03_documents as documents
import n03_eligibility as eligibility
import github_node_worker as worker
import github_actions_bridge as bridge
import n01_auto
BID="R26BK01816186"
NOTICE={"bid_no":BID,"bid_ord":"000","business_code":"22"}
# Simulates older pypdf's observable concatenation, NOT an official result.
MERGED=("3. 입찰내용4. 입찰 참여 자격가. 「도시 및 주거환경정비법」"
        "제102조에 따른 정비사업전문관리업자나. 공동참여 불가"
        "다. 입찰 마감 전까지 나라장터 전자투찰 및 직접 제출"
        "라. 위 조건을 충족하고 입찰서류를 제출한 업체"
        "7. 입찰 방법 및 선정 방법"
        "【제3조】 입찰 참여 신청 서류"
        "1. 입찰 참여신청서2. 이행각서3. 정비사업수행실적서"
        "4. 정비사업전문관리업 등록증 사본5. 국세 및 지방세 완납 증명서"
        "【제4조】 입찰서류의 작성방법")
RAW=b"%PDF-TEST-N03"
def manifest(data=RAW):
    return {"file_seq":1,"original_filename":"입찰지침서.pdf",
            "source":"https://www.g2b.go.kr/official-original",
            "file_type":"pdf","size_bytes":len(data),
            "sha256":hashlib.sha256(data).hexdigest()}

class TestN03GitHubOriginals(unittest.TestCase):
    def test_normalized_pypdf_heading_and_numbered_document_lines(self):
        lines=eligibility._normalized_source_lines(MERGED)
        self.assertTrue(any("입찰 참여 자격" in x for x in lines),lines)
        self.assertTrue(any(x.startswith("가.") for x in lines),lines)
        self.assertTrue(any(x.startswith("나.") for x in lines),lines)
        self.assertTrue(any(x.startswith("1.") and "입찰 참여신청서" in x for x in lines),lines)
        self.assertTrue(any(x.startswith("4.") and "등록증" in x for x in lines),lines)
        out=eligibility.analyze([{**manifest(),"text_chars":len(MERGED)}],[MERGED])
        self.assertEqual(out["document_requirement_extraction"],"verified",out)
        self.assertGreaterEqual(out["qualification_rule_count"],3,out)
        self.assertGreaterEqual(out["required_document_count"],5,out)
        self.assertFalse(out["company_eligibility_verified"])
        self.assertEqual(out["evidence_line_basis"],"normalized_extracted_text")
    def test_n03_inspects_actual_bytes_and_anchors_sha_not_name_only(self):
        files=[manifest()]
        status,out=documents.extract_requirements(
            files,{1:RAW},lambda *_:(MERGED,"pdf"))
        self.assertEqual(status,"partial",out)
        self.assertTrue(out["analysis_performed"])
        self.assertTrue(out["originals_integrity_verified"])
        self.assertEqual(out["verified_original_count"],1)
        self.assertEqual(out["text_extracted_files"],1)
        self.assertGreaterEqual(out["required_document_count"],5)
        self.assertFalse(out["company_eligibility_verified"])
        self.assertFalse(out["final_bid_approval"])
        self.assertEqual(out["qualification_rules"][0]["source_file_sha256"],
                         files[0]["sha256"])
        self.assertEqual(out["file_inspection"][0]["original_filename"],"입찰지침서.pdf")
    def test_filename_must_never_control_whether_original_is_read(self):
        x=manifest()
        x["original_filename"]="숫자_내역.dat"
        status,out=documents.extract_requirements(
            [x],{1:RAW},lambda *_:(MERGED,"pdf"))
        self.assertEqual(status,"partial")
        self.assertEqual(out["text_extracted_files"],1)
    def test_original_sha_or_length_mismatch_fails_closed(self):
        m=manifest()
        for bad in ({1:b"wrong-bytes"},{}):
            with self.assertRaisesRegex(documents.N03SourceError,"INTEGRITY_FAILED|NOT_RECEIVED"):
                documents.extract_requirements([m],bad,lambda *_:(MERGED,"pdf"))
    def test_unsupported_file_is_recorded_not_called_parsed(self):
        m=manifest()
        status,out=documents.extract_requirements(
            [m],{1:RAW},lambda *_:(_ for _ in ()).throw(ValueError("UNSUPPORTED_OFFICIAL_ATTACHMENT_FORMAT")))
        self.assertEqual(status,"blocked")
        self.assertTrue(out["originals_integrity_verified"])
        self.assertFalse(out["analysis_performed"])
        self.assertEqual(out["text_extracted_files"],0)
        self.assertEqual(out["extraction_issues"][0]["file_seq"],1)
    def test_integrates_with_single_github_n03_job_without_railway_parsing(self):
        context={"run_id":"a"*32,"selected_notice":NOTICE,
                 "outputs":{"N02":{"files":[manifest()],
                                   "manifest_path":"/data/n01/bids/R26BK01816186-000/attachment_manifest.json"}}}
        with patch.object(worker,"_read_original_for_n03",return_value=RAW) as downloader, \
             patch("live_nine_test._extract",return_value=(MERGED,"pdf")):
            status,inp,out=worker.execute("N03",context,base="https://example.org")
        self.assertEqual(status,"partial")
        self.assertEqual(inp["N02_original_file_count"],1)
        self.assertEqual(inp["selected_bid_no"],BID)
        self.assertTrue(out["analysis_performed"])
        self.assertFalse(out["company_eligibility_verified"])
        downloader.assert_called_once()
    def test_missing_original_manifest_does_not_approve(self):
        ctx={"run_id":"a"*32,"selected_notice":NOTICE,"outputs":{"N02":{"files":[]}}}
        status,inp,out=worker.execute("N03",ctx)
        self.assertEqual(status,"blocked")
        self.assertFalse(out["company_eligibility_verified"])
    def test_only_pending_n03_or_n09_can_download_originals(self):
        with TemporaryDirectory() as tmp:
            with patch.object(bridge,"ROOT",Path(tmp)/"actions"), \
                 patch.object(bridge,"STORAGE_ROOT",Path(tmp)/"originals"), \
                 patch.object(n01_auto,"LEDGER_PATH",Path(tmp)/"ledger.json"), \
                 patch.dict(os.environ,{"PROCUREFLOW_GITHUB_DISPATCH_TOKEN":"test-only"}), \
                 patch.object(bridge,"verify",return_value={"run_id":"42"}), \
                 patch.object(bridge,"_dispatch",return_value={"requested_at":"test"}):
                run=bridge.begin("n03-stage-test",{"mode":"auto"})
                rid=run["run_id"]
                with self.assertRaisesRegex(ValueError,"ORIGINAL_READ_STAGE_NOT_AUTHORIZED"):
                    bridge.original("Bearer test",rid,1)
                no={"bid_no":BID,"bid_ord":"000","official_fields_verified":True,
                    "search_request_verified":True}
                bridge.receive("Bearer test",{"run_id":rid,"stage":"N01",
                    "status":"verified","input":{},"output":no})
                with self.assertRaisesRegex(ValueError,"ORIGINAL_READ_STAGE_NOT_AUTHORIZED"):
                    bridge.original("Bearer test",rid,1)
                raw=b"real file from prior N02"
                m=manifest(raw)
                import base64
                headers={"X-Procureflow-Run":rid,"X-Procureflow-Stage":"N02",
                  "X-Procureflow-File-Seq":"1","X-Procureflow-Chunk":"0",
                  "X-Procureflow-File-Name":base64.urlsafe_b64encode(m["original_filename"].encode()).decode(),
                  "X-Procureflow-File-Size":str(len(raw)),
                  "X-Procureflow-File-Sha256":m["sha256"]}
                bridge.upload("Bearer test",headers,raw)
                bridge.receive("Bearer test",{"run_id":rid,"stage":"N02",
                    "status":"verified","input":{},"output":{
                        "file_count":1,"files":[m],
                        "official_attachment_inventory_complete":True}})
                path=bridge.original("Bearer test",rid,1)
                self.assertEqual(path.read_bytes(),raw)
                bridge.receive("Bearer test",{"run_id":rid,"stage":"N03",
                    "status":"partial","input":{},
                    "output":{"document_requirement_extraction":"verified",
                              "company_eligibility_verified":False}})
                with self.assertRaisesRegex(ValueError,"ORIGINAL_READ_STAGE_NOT_AUTHORIZED"):
                    bridge.original("Bearer test",rid,1)

if __name__=="__main__":unittest.main()
