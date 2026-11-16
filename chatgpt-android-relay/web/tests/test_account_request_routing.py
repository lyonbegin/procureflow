"""Regression tests for account-id on each HITEL chat request.

All browser, worker and account identities below are fixtures. No real
ChatGPT authentication occurs, and passing these tests does not prove login.
"""
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

_tmp = tempfile.TemporaryDirectory(prefix="hitel-account-routing-")
os.environ["RELAY_DATA_DIR"] = _tmp.name
os.environ["PUBLIC_SMOKE_ONLY"] = "1"
os.environ["WEB_SESSION_SIGNING_KEY"] = "account-routing-test-signing-key-over-32-bytes"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
import api_v1
import web_chat
import app

class AccountRoutingTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app.app, base_url="https://testserver")
        self.client.__enter__()
        self.csrf = self.client.get("/web/api/bootstrap").json()["csrf"]
        response = self.client.post(
            "/web/api/rooms",
            json={"title":"Account routing regression"},
            headers={"X-Web-Csrf":self.csrf},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.room = response.json()["room"]["id"]
        # Previous test cases may leave an anonymous queued fixture;
        # keep the shared in-process worker from claiming the wrong test job.
        with api_v1.connection() as db:
            db.execute("UPDATE jobs SET status='failed', stage='test_reset' "
                       "WHERE status IN ('queued','running')")
        app.web2api_device = None
        app.active_job_id = None
        app.active_job_transport = None

    def tearDown(self):
        self.client.__exit__(None, None, None)

    def send(self, account_id):
        return self.client.post(
            "/web/api/rooms/" + self.room + "/message",
            headers={"X-Web-Csrf":self.csrf},
            json={"text":"Account-specific question", "account_id":account_id},
        )

    def add_account(self):
        raw = web_chat._unpack(self.client.cookies.get(web_chat.COOKIE))
        owner = web_chat._owner_hash(raw)
        aid = "oai_fixture_" + api_v1.new_id()[:16]
        with api_v1.connection() as db:
            db.execute(
                "INSERT INTO hitel_verified_chatgpt_accounts "
                "(id,browser_owner,issuer,client_id,subject,email,display_name,active,verified_at) "
                "VALUES(?,?,?,?,?,?,?,?,?)",
                (aid,owner,"https://auth.openai.com","oaiapp_fixture",
                 "subject-fixture-"+aid,"a@example.invalid","A",1,api_v1.clock()),
            )
        return aid

    def count_jobs(self):
        with api_v1.connection() as db:
            return db.execute("SELECT count(*) FROM jobs WHERE room_id=?", (self.room,)).fetchone()[0]

    def test_anonymous_trial_sends_explicit_null_account(self):
        response = self.send(None)
        self.assertEqual(response.status_code, 200, response.text)
        with api_v1.connection() as db:
            row = db.execute("SELECT account_id FROM jobs WHERE room_id=?", (self.room,)).fetchone()
        self.assertIsNotNone(row)
        self.assertIsNone(row["account_id"])

    def test_unselected_external_account_cannot_be_injected(self):
        response = self.send("oai_attacker")
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(self.count_jobs(), 0)

    def test_selected_account_must_match_request_and_remains_fail_closed(self):
        active = self.add_account()
        mismatch = self.send("oai_other_account")
        self.assertEqual(mismatch.status_code, 409, mismatch.text)
        matching = self.send(active)
        self.assertEqual(matching.status_code, 200, matching.text)
        self.assertFalse(matching.json()["sentToChatGPT"])
        self.assertEqual(self.count_jobs(), 1)
        with api_v1.connection() as db:
            row=db.execute("SELECT account_id FROM jobs WHERE room_id=?",
                           (self.room,)).fetchone()
        self.assertEqual(row["account_id"],active)

    @patch("app.verify_worker_identity", return_value=True)
    def test_worker_ack_wrong_account_is_rejected(self, _verify):
        # Direct fixture queue insertion: real account-bound user sends
        # are intentionally blocked until Chrome login verification exists.
        with api_v1.connection() as db:
            uid = db.execute("SELECT user_id FROM rooms WHERE id=?", (self.room,)).fetchone()[0]
            job_id = api_v1.store_job(
                db, uid, self.room, "chat.send", "Fixture question", [],
                account_id="oai_fixture_account_A",
            )
        with self.client.websocket_connect("/ws") as ws:
            ws.send_json({"role":"web2api","deviceId":"web2api-main",
                          "oidc_token":"fake-signed-runner-test"})
            self.assertEqual(ws.receive_json()["type"], "auth.ok")
            dispatched = ws.receive_json()
            self.assertEqual(dispatched["type"], "job")
            self.assertEqual(dispatched["job"]["account_id"], "oai_fixture_account_A")
            ws.send_json({
                "type":"job.result","job_id":job_id,"room_id":self.room,
                "verified":True,"stage":"assistant_reply_stable",
                "result_text":"Must not be saved",
                "chatgpt_url":"https://chatgpt.com/c/c15d4040-1234-4abc-8912-123456789abc",
                "execution_account_id":"oai_fixture_account_B",
            })
            for _ in range(80):
                with api_v1.connection() as db:
                    status = db.execute(
                        "SELECT status,stage FROM jobs WHERE id=?", (job_id,)
                    ).fetchone()
                if status["status"] == "failed":
                    break
                time.sleep(.02)
            self.assertEqual(status["status"], "failed")
            self.assertEqual(status["stage"], "ACCOUNT_ID_MISMATCH")
            with api_v1.connection() as db:
                recorded = db.execute(
                    "SELECT count(*) FROM messages WHERE room_id=? AND role='assistant'",
                    (self.room,),
                ).fetchone()[0]
            self.assertEqual(recorded, 0)

if __name__ == "__main__":
    unittest.main()
