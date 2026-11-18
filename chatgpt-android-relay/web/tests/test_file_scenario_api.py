"""FastAPI synthetic HTTPS file scenario contract tests (no actual ChatGPT login)."""
from __future__ import annotations
import hashlib
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

_root=tempfile.TemporaryDirectory(prefix="hitel-synthetic-file-api-unit-")
os.environ["RELAY_DATA_DIR"]=_root.name
os.environ["PUBLIC_SMOKE_ONLY"]="1"
os.environ["WEB_SESSION_SIGNING_KEY"]="test-only-hitel-file-api-synthetic-signing-key-20261118"
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
import app
import file_scenario_api


class FileScenarioApiContractTests(unittest.TestCase):
    def setUp(self):
        self.client=TestClient(app.app,base_url="https://testserver")
        self.client.__enter__()
        self.identity=patch.object(file_scenario_api,
                                   "verify_file_scenario_identity",
                                   lambda token:token=="signed-unit-test-oidc")
        self.identity.start()
        self.headers={"Authorization":"Bearer signed-unit-test-oidc"}

    def tearDown(self):
        self.identity.stop()
        self.client.__exit__(None,None,None)

    def test_file_scenario_is_not_anonymous_mutation(self):
        url="/integrations/v1/scenarios/files/runs"
        self.assertEqual(self.client.post(url).status_code,401)
        self.assertEqual(self.client.post(url,headers={
          "Authorization":"Bearer forged-oidc"}).status_code,403)
        result=self.client.get("/integrations/v1/scenarios/files/latest")
        self.assertEqual(result.status_code,200)
        self.assertIn(result.json()["status"],("never_run","preparing","incomplete"))

    def test_actual_original_bytes_traverse_http_and_are_hash_checked(self):
        root="/integrations/v1/scenarios/files"
        created=self.client.post(root+"/runs",headers=self.headers)
        self.assertEqual(created.status_code,201,created.text)
        data=created.json()
        rid=data["run_id"]
        self.assertTrue(rid.startswith("frun_"))
        for role in ("txt","csv"):
            manifest=data["manifest"][role]
            b=manifest["body"].encode("utf-8")
            expected=hashlib.sha256(b).hexdigest()
            sent=self.client.post(
                root+"/runs/"+rid+"/files/"+role,
                headers=self.headers,
                files={"file":(manifest["name"],b,"application/octet-stream")})
            self.assertEqual(sent.status_code,200,sent.text)
            self.assertEqual(sent.json()["sha256"],expected)
            self.assertEqual(sent.json()["size"],len(b))
            read=self.client.get(root+"/runs/"+rid+"/files/"+role+"/content",
                                  headers=self.headers)
            self.assertEqual(read.status_code,200,read.text)
            self.assertEqual(read.content,b)
            self.assertEqual(read.headers["x-synthetic-sha256"],expected)
            self.assertEqual(self.client.get(
                root+"/runs/"+rid+"/files/"+role+"/content").status_code,401)
        self.assertEqual(self.client.post(
          root+"/runs/"+rid+"/files/csv",headers=self.headers,
          files={"file":("hitel_trial_generated.csv",b"wrong","text/csv")}
        ).status_code,409)
        cases=[
          {"id":id,"name":"Synthetic "+id,
           "status":"PASS" if id!="S11" else "BLOCKED",
           "detail":"VERIFIED_API_ROUNDTRIP" if id!="S11" else "BROWSER_DOWNLOAD_NOT_STARTED"}
          for id in ("S08","S09","S10","S15","S11")
        ]
        body={
          "github_run_id":"44300000001",
          "transport":{
            "uploaded_via_api":True,
            "downloaded_via_api":True,
            "sha256_match":True,
            "saved_chatgpt_account_verified":True},
          "results":cases}
        output=self.client.post(root+"/runs/"+rid+"/results",
                                headers=self.headers,json=body)
        self.assertEqual(output.status_code,200,output.text)
        report=output.json()
        self.assertEqual(report["status"],"incomplete")
        self.assertFalse(report["all_pass"])
        self.assertEqual(report["summary"]["PASS"],4)
        self.assertEqual(report["summary"]["BLOCKED"],1)
        self.assertEqual(self.client.get(root+"/runs/"+rid).json()["summary"]["BLOCKED"],1)
        self.assertEqual(self.client.post(root+"/runs/"+rid+"/results",
                              headers=self.headers,json=body).status_code,409)


if __name__=="__main__":
    unittest.main()
