"""HITEL on-demand worker launch: no artificial user chat cap, no duplicate runner.

All tests are local synthetic server calls. They never use real GitHub tokens,
never send a ChatGPT message, and do not start a real GitHub Action.
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

_root=tempfile.TemporaryDirectory(prefix="hitel-worker-autostart-")
os.environ["RELAY_DATA_DIR"]=_root.name
os.environ["PUBLIC_SMOKE_ONLY"]="1"
os.environ["WEB_SESSION_SIGNING_KEY"]="synthetic-autostart-test-signing-key"
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
import api_v1
import app
import web_chat
import worker_autostart


class WorkerStartContract(unittest.TestCase):
    def setUp(self):
        self.client=TestClient(app.app,base_url="https://testserver")
        self.client.__enter__()
        self.csrf=self.client.get("/web/api/bootstrap").json()["csrf"]
        self.original_cb=api_v1.on_new_job
        api_v1.on_new_job=app.notify_new_job
        app.web2api_device=None
        with api_v1.connection() as db:
            db.execute("""UPDATE hitel_chrome_autostart SET
                         status='idle',failures=0,dispatch_count=0,
                         next_attempt_at=0,lock_until=0,last_failure=NULL WHERE id=1""")
            db.execute("UPDATE jobs SET status='completed' WHERE status='queued' AND account_id IS NOT NULL")
        owner=web_chat._owner_hash(web_chat._unpack(self.client.cookies.get(web_chat.COOKIE)))
        aid="oai_"+api_v1.new_id()
        with api_v1.connection() as db:
            db.execute("""INSERT INTO hitel_verified_chatgpt_accounts
              (id,browser_owner,issuer,client_id,subject,email,display_name,active,verified_at)
              VALUES(?,?,?,?,?,?,?,?,?)""",
              (aid,owner,"https://auth.openai.com","synthetic_test",
               api_v1.new_id(),"test@example.invalid","Test",1,api_v1.clock()))
        key=self.client.post("/web/api/integrations/keys",headers={
            "X-Web-Csrf":self.csrf},json={"name":"Autostart unit test"}).json()
        self.account=aid
        self.token=key["api_key"]
        room=self.client.post("/integrations/v1/rooms",json={"title":"Start me"},
                              headers=self.headers()).json()
        self.room=room["room_id"]

    def tearDown(self):
        api_v1.on_new_job=self.original_cb
        app.web2api_device=None
        self.client.__exit__(None,None,None)

    def headers(self,idempotency=None):
        h={"Authorization":"Bearer "+self.token}
        if idempotency:h["Idempotency-Key"]=idempotency
        return h

    def chat(self,idem):
        return self.client.post("/integrations/v1/chat",headers=self.headers(idem),
                    json={"room_id":self.room,"account_id":self.account,
                          "text":"One synthetic request, never sent to ChatGPT",
                          "attachment_ids":[]})

    def test_no_runtime_credential_fails_without_enqueuing(self):
        with patch.dict(os.environ,{"HITEL_GITHUB_ACTIONS_TOKEN":"",
                "HITEL_GITHUB_APP_ID":"",
                "HITEL_GITHUB_APP_INSTALLATION_ID":"",
                "HITEL_GITHUB_APP_PRIVATE_KEY":""}):
            r=self.chat("missing-gh-app-config-0001")
        self.assertEqual(r.status_code,503,r.text)
        self.assertEqual(worker_autostart.pending_count(),0)

    def test_authenticated_job_launch_and_durable_lease_deduplicates(self):
        with patch.dict(os.environ,{"HITEL_GITHUB_ACTIONS_TOKEN":"synthetic-not-live"}):
            with patch.object(worker_autostart,"_dispatch_with_fallback",
                              return_value="fine_grained_token") as dispatch:
                first=self.chat("auto-start-idempotent-00001")
                self.assertEqual(first.status_code,202,first.text)
                self.assertFalse(first.json()["sent_to_chatgpt"])
                self.assertEqual(first.json()["worker_autostart"]["launch_status"],
                                 "requested")
                second=self.chat("auto-start-idempotent-00001")
                self.assertEqual(second.status_code,202,second.text)
                self.assertEqual(second.json()["job_id"],first.json()["job_id"])
                self.assertTrue(second.json()["replayed"])
                self.assertEqual(dispatch.call_count,1)
                self.assertEqual(worker_autostart.read_status(
                    connected=False)["launch_attempts"],1)
                self.assertEqual(worker_autostart.pending_count(),1)

    def test_dispatch_error_is_visible_and_retry_is_throttled(self):
        with patch.dict(os.environ,{"HITEL_GITHUB_ACTIONS_TOKEN":"synthetic-not-live"}):
            with patch.object(worker_autostart,"_dispatch_with_fallback",
                     side_effect=RuntimeError("GITHUB_HTTP_403")) as dispatch:
                r=self.chat("github-dispatch-error-00001")
                self.assertEqual(r.status_code,202,r.text)
                state=r.json()["worker_autostart"]
                self.assertEqual(state["launch_status"],"dispatch_failed")
                self.assertEqual(state["last_failure_class"],"GITHUB_HTTP_403")
                self.assertGreater(state["next_attempt_delay_seconds"],0)
                self.assertEqual(dispatch.call_count,1)
                self.assertEqual(worker_autostart.pending_count(),1)

    def test_github_app_then_fine_grained_token_fallback(self):
        env={"HITEL_GITHUB_APP_ID":"1234",
             "HITEL_GITHUB_APP_INSTALLATION_ID":"5678",
             "HITEL_GITHUB_APP_PRIVATE_KEY":"fake-pem-not-real",
             "HITEL_GITHUB_ACTIONS_TOKEN":"second-synthetic-option"}
        with patch.dict(os.environ,env):
            with patch.object(worker_autostart,"_installation_token",
                       side_effect=RuntimeError("GITHUB_APP_TOKEN_NOT_ISSUED")):
                with patch.object(worker_autostart,"_dispatch_once") as dispatch:
                    self.assertEqual(worker_autostart._dispatch_with_fallback(),
                                     "fine_grained_token")
                    dispatch.assert_called_once_with("second-synthetic-option")

    def test_signed_worker_self_restart_reserves_one_successor(self):
        import bridge_qa_api
        with patch.dict(os.environ,{"HITEL_GITHUB_ACTIONS_TOKEN":"synthetic-not-live"}):
            with patch.object(worker_autostart,"_dispatch_with_fallback",
                              return_value="fine_grained_token"):
                result=self.chat("signed-fallback-pending-000001")
                self.assertEqual(result.status_code,202,result.text)
        # Simulate the end of an already-running 4h Chrome worker.
        with api_v1.connection() as db:
            db.execute("""UPDATE hitel_chrome_autostart
                         SET next_attempt_at=0,lock_until=0 WHERE id=1""")
        endpoint="/integrations/v1/qa/bridge/worker-fallback"
        self.assertEqual(self.client.post(endpoint).status_code,401)
        with patch.object(bridge_qa_api,"verify_bridge_qa_identity",
                          lambda t:t=="test-only-valid-oidc"):
            denied=self.client.post(endpoint,headers={
                "Authorization":"Bearer unsigned-token"})
            self.assertEqual(denied.status_code,403)
            accepted=self.client.post(endpoint,headers={
                "Authorization":"Bearer test-only-valid-oidc"})
            self.assertEqual(accepted.status_code,200,accepted.text)
            self.assertTrue(accepted.json()["relaunch_authorized"])
            replay=self.client.post(endpoint,headers={
                "Authorization":"Bearer test-only-valid-oidc"})
            self.assertEqual(replay.status_code,200,replay.text)
            self.assertFalse(replay.json()["relaunch_authorized"])

    def test_worker_connected_clears_errors_without_resubmitting(self):
        worker_autostart.worker_connected()
        state=worker_autostart.read_status(connected=True)
        self.assertEqual(state["launch_status"],"connected")
        self.assertEqual(worker_autostart.pending_count(),0)


if __name__=="__main__":
    unittest.main()
