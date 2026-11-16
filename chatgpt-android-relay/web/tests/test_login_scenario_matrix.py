"""HITEL account lifecycle case-by-case integration matrix.

All identities and worker results are fixtures. No ChatGPT/Google credentials
or real browser session are used. Passing DOES NOT prove live sign-in/sign-out.
"""
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

_tmp = tempfile.TemporaryDirectory(prefix="hitel-login-matrix-")
os.environ["RELAY_DATA_DIR"] = _tmp.name
os.environ["PUBLIC_SMOKE_ONLY"] = "1"
os.environ["WEB_SESSION_SIGNING_KEY"] = "hitel-login-scenario-matrix-secure-test-signing-key"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
import app
import api_v1
import chatgpt_accounts
import web_chat

class LoginScenarioMatrix(unittest.TestCase):
    def setUp(self):
        app.web2api_device = None
        app.active_job_id = None
        app.active_job_transport = None
        with api_v1.connection() as db:
            db.execute("UPDATE jobs SET status='failed',stage='scenario_reset' "
                       "WHERE status IN ('queued','running')")
        self.a = TestClient(app.app, base_url="https://testserver")
        self.b = TestClient(app.app, base_url="https://testserver")
        self.a.__enter__()
        self.b.__enter__()
        self.csrf_a = self.a.get("/web/api/bootstrap").json()["csrf"]
        self.csrf_b = self.b.get("/web/api/bootstrap").json()["csrf"]
        created = self.a.post("/web/api/rooms",
            headers={"X-Web-Csrf":self.csrf_a},
            json={"title":"Scenario room"})
        self.assertEqual(created.status_code, 200, created.text)
        self.rid = created.json()["room"]["id"]

    def tearDown(self):
        self.a.__exit__(None,None,None)
        self.b.__exit__(None,None,None)

    def fixture_account(self, client, email_suffix, active=False):
        raw = web_chat._unpack(client.cookies.get(web_chat.COOKIE))
        owner = web_chat._owner_hash(raw)
        aid = "oai_fixture_" + api_v1.new_id()
        with api_v1.connection() as db:
            if active:
                db.execute("UPDATE hitel_verified_chatgpt_accounts "
                           "SET active=0 WHERE browser_owner=?", (owner,))
            db.execute(
                "INSERT INTO hitel_verified_chatgpt_accounts "
                "(id,browser_owner,issuer,client_id,subject,email,display_name,active,verified_at)"
                " VALUES(?,?,?,?,?,?,?,?,?)",
                (aid,owner,"https://auth.openai.com","oaiapp_test_fixture",
                 "sub:"+aid,email_suffix+"@example.invalid",email_suffix,
                 1 if active else 0,api_v1.clock())
            )
        return aid

    def select(self, aid, client=None, csrf=None, **extra):
        client = client or self.a
        csrf = csrf or self.csrf_a
        headers={"X-Web-Csrf":csrf,**extra}
        return client.post("/web/api/chatgpt/accounts/"+aid+"/select",headers=headers)

    def send(self, account_id, client=None, csrf=None):
        client=client or self.a
        csrf=csrf or self.csrf_a
        return client.post("/web/api/rooms/"+self.rid+"/message",
                           json={"text":"safe scenario message","account_id":account_id},
                           headers={"X-Web-Csrf":csrf})

    def accounts(self, client=None):
        return (client or self.a).get("/web/api/chatgpt/accounts").json()["accounts"]

    def queued(self):
        with api_v1.connection() as db:
            return db.execute("SELECT count(*) FROM jobs WHERE room_id=?",
                              (self.rid,)).fetchone()[0]

    def test_01_guest_first_visit_no_login(self):
        self.assertEqual(self.accounts(),[])
        r=self.send(None)
        self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(self.queued(),1)

    def test_02_unknown_requested_account_blocked(self):
        self.assertEqual(self.send("oai_unknown").status_code,409)
        self.assertEqual(self.queued(),0)

    def test_03_selected_account_missing_parameter_blocked(self):
        self.fixture_account(self.a,"A",active=True)
        self.assertEqual(self.send(None).status_code,409)
        self.assertEqual(self.queued(),0)

    def test_04_selected_account_wrong_parameter_blocked(self):
        self.fixture_account(self.a,"A",active=True)
        self.assertEqual(self.send("oai_some_other").status_code,409)
        self.assertEqual(self.queued(),0)

    def test_05_selected_account_same_parameter_queues_not_delivered(self):
        a=self.fixture_account(self.a,"A",active=True)
        response=self.send(a)
        self.assertEqual(response.status_code,200,response.text)
        self.assertIs(response.json()["sentToChatGPT"],False)
        self.assertEqual(self.queued(),1)
        self.assertEqual(self.send(a).status_code,409)

    def test_06_switch_a_b_a_and_pin_each_job_at_queue_time(self):
        a=self.fixture_account(self.a,"A",active=True)
        b=self.fixture_account(self.a,"B",active=False)
        actual=[]
        new_room=self.a.post("/web/api/rooms",
            headers={"X-Web-Csrf":self.csrf_a},json={"title":"Account B room"})
        self.assertEqual(new_room.status_code,200)
        per_account={a:self.rid,b:new_room.json()["room"]["id"]}
        for aid in (a,b,a):
            self.rid=per_account[aid]
            self.assertEqual(self.select(aid).status_code,200)
            selected=[p["id"] for p in self.accounts() if p["active"]]
            self.assertEqual(selected,[aid])
            r=self.send(aid)
            self.assertEqual(r.status_code,200,r.text)
            self.assertIs(r.json()["sentToChatGPT"],False)
            with api_v1.connection() as db:
                item=db.execute("SELECT account_id FROM jobs WHERE id=?",
                                (r.json()["jobId"],)).fetchone()
                actual.append(item["account_id"])
                db.execute("UPDATE jobs SET status='failed' WHERE id=?",
                           (r.json()["jobId"],))
        self.assertEqual(actual,[a,b,a])

    def test_07_unlink_selected_falls_back_only_to_remaining_account(self):
        a=self.fixture_account(self.a,"A",active=True)
        b=self.fixture_account(self.a,"B",active=False)
        self.assertEqual(self.select(b).status_code,200)
        deleted=self.a.delete("/web/api/chatgpt/accounts/"+b,
                             headers={"X-Web-Csrf":self.csrf_a})
        self.assertEqual(deleted.status_code,200,deleted.text)
        self.assertFalse(deleted.json()["chatgptAccountDeleted"])
        self.assertEqual([p["id"] for p in self.accounts() if p["active"]],[a])
        self.assertEqual(self.send(b).status_code,409)

    def test_08_unlink_last_identity_reverts_to_anonymous_trial(self):
        a=self.fixture_account(self.a,"A",active=True)
        result=self.a.delete("/web/api/chatgpt/accounts/"+a,
                             headers={"X-Web-Csrf":self.csrf_a})
        self.assertEqual(result.status_code,200)
        self.assertEqual(self.accounts(),[])
        self.assertEqual(self.send(a).status_code,409)
        self.assertEqual(self.send(None).status_code,200)

    def test_09_cross_browser_account_isolation(self):
        a=self.fixture_account(self.a,"A",active=True)
        self.assertEqual(self.accounts(self.b),[])
        self.assertEqual(self.select(a,client=self.b,csrf=self.csrf_b).status_code,404)
        self.assertEqual(self.b.delete("/web/api/chatgpt/accounts/"+a,
                                     headers={"X-Web-Csrf":self.csrf_b}).status_code,404)
        self.assertEqual(self.send(a).status_code,200)
        self.assertEqual(len(self.accounts()),1)

    def test_10_csrf_and_cross_origin_mutations_refused(self):
        a=self.fixture_account(self.a,"A",active=True)
        r1=self.a.post("/web/api/chatgpt/accounts/"+a+"/select")
        r2=self.select(a,Origin="https://other.example")
        r3=self.a.delete("/web/api/chatgpt/accounts/"+a)
        self.assertEqual([r1.status_code,r2.status_code,r3.status_code],[403,403,403])
        self.assertEqual(len(self.accounts()),1)

    def test_11_tampered_browser_cookie_cannot_manage_account(self):
        a=self.fixture_account(self.a,"A",active=True)
        fake=TestClient(app.app,base_url="https://testserver")
        with fake:
            fake.cookies.set(web_chat.COOKIE,"bad.signed.cookie")
            self.assertEqual(fake.get("/web/api/chatgpt/accounts").status_code,401)
            self.assertEqual(fake.post("/web/api/chatgpt/accounts/"+a+"/select",
                headers={"X-Web-Csrf":self.csrf_a}).status_code,401)

    def test_12_inflight_duplicate_send_rejected(self):
        first=self.send(None)
        self.assertEqual(first.status_code,200,first.text)
        second=self.send(None)
        self.assertEqual(second.status_code,409)
        self.assertEqual(self.queued(),1)

    def test_13_job_account_pinned_through_later_selection_change(self):
        a=self.fixture_account(self.a,"A",active=True)
        b=self.fixture_account(self.a,"B",active=False)
        with api_v1.connection() as db:
            uid=db.execute("SELECT user_id FROM rooms WHERE id=?", (self.rid,)).fetchone()[0]
            jid=api_v1.store_job(db,uid,self.rid,"chat.send","pin account A",[],account_id=a)
        self.assertEqual(self.select(b).status_code,200)
        with api_v1.connection() as db:
            row=db.execute("SELECT account_id,status FROM jobs WHERE id=?",(jid,)).fetchone()
        self.assertEqual(row["account_id"],a)
        self.assertEqual(row["status"],"queued")

    def test_14_oauth_unconfigured_fails_without_forging_login(self):
        with patch.object(chatgpt_accounts,"CLIENT_ID",""),\
             patch.object(chatgpt_accounts,"REDIRECT_URI",""):
            response=self.a.get("/web/api/chatgpt/login",follow_redirects=False)
            self.assertEqual(response.status_code,503)
            self.assertEqual(self.accounts(),[])

    @patch("app.verify_worker_identity",return_value=True)
    def test_15_worker_claims_matching_account_but_no_independent_proof(self,_):
        a=self.fixture_account(self.a,"A",active=True)
        with api_v1.connection() as db:
            uid=db.execute("SELECT user_id FROM rooms WHERE id=?", (self.rid,)).fetchone()[0]
            jid=api_v1.store_job(db,uid,self.rid,"chat.send","fixture only",[],account_id=a)
        with self.a.websocket_connect("/ws") as ws:
            ws.send_json({"role":"web2api","deviceId":"web2api-main",
                          "oidc_token":"synthetic-token"})
            self.assertEqual(ws.receive_json()["type"],"auth.ok")
            packet=ws.receive_json()
            self.assertEqual(packet["type"],"job")
            self.assertEqual(packet["job"]["account_id"],a)
            ws.send_json({"type":"job.result","job_id":jid,"room_id":self.rid,
                          "verified":True,"stage":"assistant_reply_stable",
                          "result_text":"forged successful result",
                          "execution_account_id":a,
                          "chatgpt_url":"https://chatgpt.com/c/a1234567-1234-4123-8123-123456789012"})
            for _ in range(80):
                with api_v1.connection() as db:
                    status=db.execute("SELECT status,stage FROM jobs WHERE id=?",
                                      (jid,)).fetchone()
                if status["status"]=="failed":
                    break
                time.sleep(.02)
            self.assertEqual(status["status"],"failed")
            self.assertEqual(status["stage"],"ACCOUNT_EXECUTION_NOT_VERIFIED")
            with api_v1.connection() as db:
                assistant=db.execute("SELECT count(*) FROM messages "
                    "WHERE room_id=? AND role='assistant'",(self.rid,)).fetchone()[0]
            self.assertEqual(assistant,0)


    @patch("app.verify_worker_identity",return_value=True)
    def test_16_signed_worker_proves_matching_email_and_room(self,_):
        selected=self.fixture_account(self.a,"AccountA",active=True)
        posted=self.send(selected)
        self.assertEqual(posted.status_code,200,posted.text)
        jid=posted.json()["jobId"]
        with self.a.websocket_connect("/ws") as ws:
            ws.send_json({"role":"web2api","deviceId":"web2api-main",
                          "oidc_token":"mock-signed-github-runner"})
            self.assertEqual(ws.receive_json()["type"],"auth.ok")
            packet=ws.receive_json()
            self.assertEqual(packet["job"]["id"],jid)
            self.assertEqual(packet["job"]["account_id"],selected)
            self.assertEqual(packet["job"]["account_email"],"AccountA@example.invalid")
            ws.send_json({
                "type":"job.result","job_id":jid,"room_id":self.rid,
                "verified":True,"stage":"assistant_reply_stable",
                "result_text":"Fixture matched account result",
                "execution_account_id":selected,
                "execution_account_email":"accounta@example.invalid",
                "session_verified":True,
                "chatgpt_url":"https://chatgpt.com/c/a1234567-1234-4123-8123-123456789012",
            })
            for _ in range(80):
                with api_v1.connection() as db:
                    status=db.execute("SELECT status FROM jobs WHERE id=?",(jid,)).fetchone()
                if status["status"]!="running":
                    break
                time.sleep(.02)
            self.assertEqual(status["status"],"completed")

    @patch("app.verify_worker_identity",return_value=True)
    def test_17_matching_id_wrong_session_email_refused(self,_):
        selected=self.fixture_account(self.a,"AccountA",active=True)
        posted=self.send(selected)
        self.assertEqual(posted.status_code,200)
        jid=posted.json()["jobId"]
        with self.a.websocket_connect("/ws") as ws:
            ws.send_json({"role":"web2api","deviceId":"web2api-main",
                          "oidc_token":"mock-signed-github-runner"})
            self.assertEqual(ws.receive_json()["type"],"auth.ok")
            self.assertEqual(ws.receive_json()["job"]["id"],jid)
            ws.send_json({
                "type":"job.result","job_id":jid,"room_id":self.rid,
                "verified":True,"stage":"assistant_reply_stable",
                "result_text":"Must not be stored",
                "execution_account_id":selected,
                "execution_account_email":"other@example.invalid",
                "session_verified":True,
                "chatgpt_url":"https://chatgpt.com/c/a1234567-1234-4123-8123-123456789012",
            })
            for _ in range(80):
                with api_v1.connection() as db:
                    status=db.execute("SELECT status,stage FROM jobs WHERE id=?",
                                      (jid,)).fetchone()
                if status["status"]=="failed":
                    break
                time.sleep(.02)
            self.assertEqual(status["status"],"failed")
            self.assertEqual(status["stage"],"ACCOUNT_EXECUTION_NOT_VERIFIED")

    @patch("app.verify_worker_identity",return_value=True)
    def test_18_unlinked_account_cannot_complete_old_worker_job(self,_):
        selected=self.fixture_account(self.a,"AccountA",active=True)
        posted=self.send(selected)
        self.assertEqual(posted.status_code,200)
        jid=posted.json()["jobId"]
        with self.a.websocket_connect("/ws") as ws:
            ws.send_json({"role":"web2api","deviceId":"web2api-main",
                          "oidc_token":"mock-signed-github-runner"})
            self.assertEqual(ws.receive_json()["type"],"auth.ok")
            self.assertEqual(ws.receive_json()["job"]["id"],jid)
            dropped=self.a.delete("/web/api/chatgpt/accounts/"+selected,
                                  headers={"X-Web-Csrf":self.csrf_a})
            self.assertEqual(dropped.status_code,409)
            ws.send_json({
                "type":"job.result","job_id":jid,"room_id":self.rid,
                "verified":True,"stage":"assistant_reply_stable",
                "result_text":"Must not be stored",
                "execution_account_id":selected,
                "execution_account_email":"accounta@example.invalid",
                "session_verified":True,
                "chatgpt_url":"https://chatgpt.com/c/a1234567-1234-4123-8123-123456789012",
            })
            for _ in range(80):
                with api_v1.connection() as db:
                    status=db.execute("SELECT status,stage FROM jobs WHERE id=?",
                                      (jid,)).fetchone()
                if status["status"]=="failed":
                    break
                time.sleep(.02)
            self.assertEqual(status["status"],"failed")
            self.assertEqual(status["stage"],"ACCOUNT_EXECUTION_NOT_VERIFIED")
            dropped_again=self.a.delete("/web/api/chatgpt/accounts/"+selected,
                headers={"X-Web-Csrf":self.csrf_a})
            self.assertEqual(dropped_again.status_code,200)

    def test_19_legacy_preset_cannot_skip_account_metadata(self):
        self.fixture_account(self.a,"A",active=True)
        r=self.a.post("/web/api/rooms/"+self.rid+"/test",
            headers={"X-Web-Csrf":self.csrf_a},json={"preset":"hello"})
        self.assertEqual(r.status_code,409,r.text)
        self.assertEqual(self.queued(),0)

if __name__=="__main__":
    unittest.main()
