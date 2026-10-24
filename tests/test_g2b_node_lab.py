"""Safety and API-contract tests for standalone node test lab.

No production database needed; fixture execution must never create verified
evidence or silently dispatch an official source collector.
"""
from unittest.mock import patch
from io import BytesIO
import json
import unittest
from zipfile import ZipFile, ZIP_DEFLATED

from fastapi import FastAPI
from fastapi.testclient import TestClient
from fastapi import HTTPException

from g2b_node_lab import (
    Assertion, NodeTestRequest, _assert_one, _get_path,
    _safe_filename, _validate_document, _run_test, router, MAX_FILE_BYTES
)

BID = "R26BK01787028"


class NodeTestLabUnit(unittest.TestCase):
    def test_mock_is_test_only_and_never_collects(self):
        args = NodeTestRequest(mode="mock", mock_output={"status": "ready", "count": 3},
                               assertions=[Assertion(path="count",operator="gte",expected=2),
                                           Assertion(path="status",operator="eq",expected="ready")])
        with patch("g2b_feature_api.execute_one",side_effect=AssertionError("collector called")):
            result = _run_test(BID, 50, args)
        self.assertTrue(result["assertions_passed"])
        self.assertTrue(result["test_only"])
        self.assertFalse(result["production_acceptance_updated"])
        self.assertFalse(result["collector_was_executed"])
        self.assertEqual(result["mode"], "mock")

    def test_manual_data_cannot_be_called_original_evidence(self):
        args = NodeTestRequest(mode="manual", variables={
            "agency": "user edited agency", "detail10": "0000000000",
            "bid_no": "not selected bid"})
        result = _run_test(BID, 29, args)
        self.assertEqual(result["output"]["origin"],"unverified_user_test_fixture")
        self.assertFalse(result["is_official_evidence"])

    def test_official_mode_rejects_override(self):
        with self.assertRaises(HTTPException) as err:
            _run_test(BID, 50, NodeTestRequest(mode="official",
                       variables={"detail10":"forged"}))
        self.assertEqual(err.exception.status_code,422)

    def test_actual_official_observation_only_reads_source(self):
        with patch("g2b_node_lab.notice_context",return_value={
            "bid_no":BID,"official_detail10":["8111159901"],
            "original_notice_verified":True}),patch(
            "g2b_feature_data.feature_observation",return_value={
                "status":"observed", "data":{"count":6}}):
            output = _run_test(BID, 50, NodeTestRequest(mode="official"))
        self.assertEqual(output["output"]["observation"]["data"]["count"],6)
        self.assertFalse(output["collector_was_executed"])

    def test_assertions_work_with_json_paths(self):
        source={"items":[{"price":1200}],"ok":True}
        self.assertEqual(_get_path(source,"items[0].price"),(True,1200))
        self.assertFalse(_assert_one(source,Assertion(path="items[0].price",
                    operator="gte",expected=1300))["passed"])
        self.assertTrue(_assert_one(source,Assertion(path="ok",operator="eq",
                    expected=True))["passed"])
        self.assertFalse(_assert_one(source,Assertion(path="missing",operator="eq",
                    expected=None))["passed"])

    def test_unknown_function_or_wrong_bid_is_rejected(self):
        for bid,feature in [(BID,105),("not-a-real-selected-bid",50)]:
            with self.assertRaises(HTTPException) as ctx:
                _run_test(bid,feature,NodeTestRequest(mode="mock",mock_output={}))
            self.assertEqual(ctx.exception.status_code,404)

    def test_document_checks_block_mismatch_empty_and_excess(self):
        self.assertEqual(_safe_filename(r"C:\fakepath\document.pdf"),"document.pdf")
        with self.assertRaises(HTTPException):
            _safe_filename("script.exe")
        for raw in [b"not really a pdf",b"",b"a"*(MAX_FILE_BYTES+1)]:
            with self.assertRaises(HTTPException):
                _validate_document("document.pdf",raw)

    def test_protect_zip_bombs_and_mismatched_docx(self):
        stream=BytesIO()
        with ZipFile(stream,"w",ZIP_DEFLATED) as archive:
            archive.writestr("word/document.xml",b"a"*(3*1024*1024))
        with self.assertRaises(HTTPException) as err:
            _validate_document("report.docx",stream.getvalue())
        self.assertEqual(err.exception.status_code,413)
        with self.assertRaises(HTTPException):
            _validate_document("report.xlsx",stream.getvalue())


class NodeLabAPITest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app = FastAPI()
        app.include_router(router)
        cls.client=TestClient(app)

    def test_contract_is_authenticated(self):
        with patch("main.guard",side_effect=HTTPException(401,"unauthorized")):
            r=self.client.get(f"/api/g2b/cases/{BID}/features/50/test/contract")
        self.assertEqual(r.status_code,401)

    def test_mock_endpoint_requires_no_business_collector(self):
        class FakeConnection:
            def execute(self,query,arguments):
                if "INSERT INTO procureflow.g2b_node_test_runs" not in query:
                    raise AssertionError("unexpected production database mutation")
                class Result:
                    def fetchone(self):return {"id":123}
                return Result()
        from contextlib import contextmanager
        @contextmanager
        def fake_session():
            yield FakeConnection()
        with patch("main.guard",return_value=None),patch(
            "g2b_node_lab.session",fake_session):
            r=self.client.post(f"/api/g2b/cases/{BID}/features/50/test",json={
                "mode":"mock","mock_output":{"status":"success"},
                "assertions":[{"path":"status","operator":"eq","expected":"success"}]})
        self.assertEqual(r.status_code,200,r.text)
        self.assertTrue(r.json()["test_only"])
        self.assertEqual(r.json()["run_id"],123)

    def test_upload_denies_fake_pdf_before_database_touch(self):
        with patch("main.guard",return_value=None),patch(
             "g2b_node_lab.session",side_effect=AssertionError("must not touch DB")):
            r=self.client.post(f"/api/g2b/cases/{BID}/features/29/test/files",
                               files={"file":("attack.pdf",b"not pdf","application/pdf")})
        self.assertEqual(r.status_code,415)

    def test_openapi_routes_exist_for_file_mock_and_replay(self):
        from fastapi.openapi.utils import get_openapi
        schema=get_openapi(title="lab",version="1",routes=self.client.app.routes)
        root=f"/api/g2b/cases/{{bid_no}}/features/{{feature_no}}/test"
        self.assertIn("post",schema["paths"][root])
        self.assertIn("post",schema["paths"][root+"/files"])
        self.assertIn("get",schema["paths"][root+"/runs"])
        self.assertIn("put",schema["paths"][root+"/pin"])
        self.assertIn("delete",schema["paths"][root+"/pin"])


if __name__=="__main__":
    unittest.main()
