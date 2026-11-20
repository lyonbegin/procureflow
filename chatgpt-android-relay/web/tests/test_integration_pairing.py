"""Synthetic browser owner + signed GitHub Chrome attestation onboarding contract."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

_tmp=tempfile.TemporaryDirectory(prefix="hitel-signed-pairing-qa-")
os.environ["RELAY_DATA_DIR"]=_tmp.name
os.environ["PUBLIC_SMOKE_ONLY"]="1"
os.environ["WEB_SESSION_SIGNING_KEY"]="test-only-pairing-signing-key-20261119"
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
import api_v1
import app
import integration_pairing

class PairingContract(unittest.TestCase):
    def setUp(self):
        self.client=TestClient(app.app,base_url="https://testserver")
        self.client.__enter__()
        self.csrf=self.client.get("/web/api/bootstrap").json()["csrf"]
        self.auth={"X-Web-Csrf":self.csrf}
        self.headers={"Authorization":"Bearer signed-gh-oidc-test"}
        self.mock=patch.object(integration_pairing,"verify_pairing_identity",
                    lambda tok:tok=="signed-gh-oidc-test")
        self.mock.start()
        api_v1.on_new_job=None
        app.web2api_device=None

    def tearDown(self):
        self.mock.stop()
        app.web2api_device=None
        self.client.__exit__(None,None,None)

    def test_real_browser_requires_csrf_and_signed_workflow(self):
        path="/web/api/integrations/pairing/request"
        self.assertEqual(self.client.post(path).status_code,403)
        made=self.client.post(path,headers=self.auth)
        self.assertEqual(made.status_code,201,made.text)
        token=made.json()["pairing_code"]
        self.assertTrue(token.startswith("hitelpair_"))
        url="/integrations/v1/registration/pair"
        payload={"pairing_code":token,
                 "verified_session_email":"verified.account@example.invalid"}
        self.assertEqual(self.client.post(url,json=payload).status_code,401)
        self.assertEqual(self.client.post(url,headers={
            "Authorization":"Bearer forged-oidc"},json=payload).status_code,403)
        registered=self.client.post(url,headers=self.headers,json=payload)
        self.assertEqual(registered.status_code,201,registered.text)
        self.assertTrue(registered.json()["account_id"].startswith("oai_"))
        self.assertEqual(self.client.post(url,headers=self.headers,json=payload).status_code,409)
        status=self.client.get("/web/api/integrations/pairing/status")
        self.assertTrue(status.json()["ready_to_issue_key"])
        self.assertNotIn("verified.account@example.invalid",status.text)

        key=self.client.post("/web/api/integrations/keys",
            headers=self.auth,json={"name":"Owned GitHub profile app key"})
        self.assertEqual(key.status_code,200,key.text)
        k=key.json()["api_key"]
        self.assertEqual(key.json()["account_id"],registered.json()["account_id"])
        rooms=self.client.post("/integrations/v1/rooms",
            headers={"Authorization":"Bearer "+k},
            json={"title":"Owner-bound first room"})
        self.assertEqual(rooms.status_code,201,rooms.text)
        room=rooms.json()["room_id"]
        text={"room_id":room,"account_id":key.json()["account_id"],
              "text":"synthetic test","attachment_ids":[]}
        auth={"Authorization":"Bearer "+k,
              "Idempotency-Key":"owner-pair-unit-test-0001"}
        self.assertEqual(self.client.post("/integrations/v1/chat",
            headers=auth,json=text).status_code,503)
        with patch.object(app,"web2api_device",object()):
            accepted=self.client.post("/integrations/v1/chat",
                headers=auth,json=text)
        self.assertEqual(accepted.status_code,202,accepted.text)
        self.assertFalse(accepted.json()["sent_to_chatgpt"])
        self.assertTrue(accepted.json()["job_id"].startswith("job_"))
        self.assertEqual(self.client.get(
            "/integrations/v1/jobs/"+accepted.json()["job_id"],
            headers={"Authorization":"Bearer "+k}).json()["status"],"queued")


if __name__=="__main__":
    unittest.main()
