"""Contract and isolation tests for programmatic HITEL integrations (synthetic only)."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

_temp=tempfile.TemporaryDirectory(prefix="hitel-m2m-api-")
os.environ["RELAY_DATA_DIR"]=_temp.name
os.environ["PUBLIC_SMOKE_ONLY"]="1"
os.environ["WEB_SESSION_SIGNING_KEY"]="hitel-m2m-unit-test-signing-key-20261118"
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
import app
import api_v1
import web_chat
import integration_api


class IntegrationContract(unittest.TestCase):
    def setUp(self):
        self.a=TestClient(app.app,base_url="https://testserver")
        self.b=TestClient(app.app,base_url="https://testserver")
        self.a.__enter__()
        self.b.__enter__()
        self.ca=self.a.get("/web/api/bootstrap").json()["csrf"]
        self.cb=self.b.get("/web/api/bootstrap").json()["csrf"]
        app.web2api_device=None
        app.active_job_id=None
        api_v1.on_new_job=None

    def tearDown(self):
        self.a.__exit__(None,None,None)
        self.b.__exit__(None,None,None)

    def link(self, client, account=None):
        raw=web_chat._unpack(client.cookies.get(web_chat.COOKIE))
        self.assertTrue(raw)
        owner=web_chat._owner_hash(raw)
        aid=account or ("oai_"+api_v1.new_id())
        with api_v1.connection() as db:
            db.execute("""
                INSERT INTO hitel_verified_chatgpt_accounts
                (id,browser_owner,issuer,client_id,subject,email,display_name,active,verified_at)
                VALUES(?,?,?,?,?,?,?,?,?)
            """,(aid,owner,"https://auth.openai.com","oaiapp_test",
                 api_v1.new_id(),"test@example.invalid","Synthetic Test Account",
                 1,api_v1.clock()))
        return aid

    def key(self,client,csrf):
        r=client.post("/web/api/integrations/keys",json={"name":"Automated synthetic test"},
                      headers={"X-Web-Csrf":csrf})
        self.assertEqual(r.status_code,200,r.text)
        return r.json()

    def headers(self,token,idempotency=None):
        h={"Authorization":"Bearer "+token}
        if idempotency:h["Idempotency-Key"]=idempotency
        return h

    def test_public_capabilities_never_claim_files_or_sync_completion(self):
        c=self.a.get("/integrations/v1/capabilities")
        self.assertEqual(c.status_code,200)
        j=c.json()
        self.assertTrue(j["async_job_api"])
        self.assertFalse(j["remote_binary_file_attachment"]["supported"])
        self.assertFalse(j["generated_file_download"]["supported"])
        self.assertFalse(j["worker_connected"])

    def test_key_requires_selected_verified_identity_and_csrf(self):
        self.assertEqual(self.a.post("/web/api/integrations/keys",
                         json={"name":"test"}).status_code,403)
        self.assertEqual(self.a.post("/web/api/integrations/keys",
                         json={"name":"test"},
                         headers={"X-Web-Csrf":self.ca}).status_code,409)
        self.link(self.a)
        self.assertEqual(self.b.post("/web/api/integrations/keys",
                         json={"name":"test"},
                         headers={"X-Web-Csrf":self.cb}).status_code,409)
        self.assertEqual(self.a.post("/web/api/integrations/keys",
                         json={"name":"test"},
                         headers={"X-Web-Csrf":self.ca,"Origin":"https://attacker.invalid"}
                        ).status_code,403)
        key=self.key(self.a,self.ca)
        self.assertTrue(key["api_key"].startswith("htli_"))
        self.assertNotIn(key["api_key"],str(self.a.get("/web/api/integrations/keys").json()))

    def test_scoped_chat_job_idempotency_and_revocation(self):
        a_account=self.link(self.a)
        a_key=self.key(self.a,self.ca)
        b_account=self.link(self.b)
        b_key=self.key(self.b,self.cb)
        headers=self.headers(a_key["api_key"])
        self.assertEqual(self.a.get("/integrations/v1/rooms").status_code,401)
        created=self.a.post("/integrations/v1/rooms",json={"title":"API synthetic chat"},
                            headers=headers)
        self.assertEqual(created.status_code,201,created.text)
        room=created.json()["room_id"]
        self.assertEqual(created.json()["account_id"],a_account)
        self.assertEqual(self.a.get("/integrations/v1/rooms",headers=headers).json()
                         ["rooms"][0]["id"],room)
        content={"room_id":room,"account_id":a_account,"text":"HITEL unit test message only"}
        # Real API refuses to enqueue when Chrome is not connected.
        self.assertEqual(self.a.post("/integrations/v1/chat",json=content,
                        headers=self.headers(a_key["api_key"],
                        "offline-test-no-worker-00001")).status_code,503)
        app.web2api_device=object()  # isolate queue contract from socket transport
        k="client-test-unique-idempotency-00001"
        self.assertEqual(self.a.post("/integrations/v1/chat",json=content,
                         headers=headers).status_code,400)
        first=self.a.post("/integrations/v1/chat",json=content,
                         headers=self.headers(a_key["api_key"],k))
        self.assertEqual(first.status_code,202,first.text)
        self.assertFalse(first.json()["sent_to_chatgpt"])
        jid=first.json()["job_id"]
        with api_v1.connection() as db:
            j=db.execute("SELECT account_id,status FROM jobs WHERE id=?",(jid,)).fetchone()
        self.assertEqual(j["account_id"],a_account)
        self.assertEqual(j["status"],"queued")
        again=self.a.post("/integrations/v1/chat",json=content,
                          headers=self.headers(a_key["api_key"],k))
        self.assertEqual(again.status_code,202)
        self.assertEqual(again.json()["job_id"],jid)
        self.assertTrue(again.json()["replayed"])
        changed=dict(content,text="A different message")
        self.assertEqual(self.a.post("/integrations/v1/chat",json=changed,
                         headers=self.headers(a_key["api_key"],k)).status_code,409)
        self.assertEqual(self.b.get("/integrations/v1/jobs/"+jid,
                         headers=self.headers(b_key["api_key"])).status_code,404)
        self.assertEqual(self.a.post("/integrations/v1/chat",json=dict(content,
                         account_id=b_account),
                         headers=self.headers(a_key["api_key"],"different-key-for-wrong-account")
                         ).status_code,409)
        with api_v1.connection() as db:
            db.execute("UPDATE jobs SET status='completed',stage='verified',result_text=? WHERE id=?",
                       ("HITEL_TEST_REPLY",jid))
        status=self.a.get("/integrations/v1/jobs/"+jid,headers=headers)
        self.assertEqual(status.status_code,200)
        self.assertEqual(status.json()["result_text"],"HITEL_TEST_REPLY")
        self.assertEqual(self.a.post("/integrations/v1/chat",
                         json=dict(content,attachment_ids=["file_synthetic"]),
                         headers=self.headers(a_key["api_key"],"reject-attachment-000002")
                         ).status_code,501)
        revoke=self.a.delete("/web/api/integrations/keys/"+a_key["id"],
                             headers={"X-Web-Csrf":self.ca})
        self.assertEqual(revoke.status_code,200,revoke.text)
        self.assertEqual(self.a.get("/integrations/v1/jobs/"+jid,headers=headers).status_code,403)

    def test_account_switch_revokes_effective_access_without_deleting_key(self):
        first=self.link(self.a)
        key=self.key(self.a,self.ca)
        with api_v1.connection() as db:
            db.execute("UPDATE hitel_verified_chatgpt_accounts SET active=0 WHERE id=?",(first,))
        self.assertEqual(self.a.get("/integrations/v1/rooms",
                         headers=self.headers(key["api_key"])).status_code,409)


if __name__=="__main__":
    unittest.main()
