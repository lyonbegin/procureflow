"""Actual account-connection contract tests, without credentials or real login.

A verified OIDC identity is NOT a ChatGPT web-browser session. These tests
enforce that a selected verified identity cannot send a prompt using an
unrelated GitHub Actions Chrome login, and that other browser visitors cannot
read or select each other's accounts.
"""
import os
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

_temp=tempfile.TemporaryDirectory(prefix="hitel-chatgpt-identity-test-")
os.environ["RELAY_DATA_DIR"]=_temp.name
os.environ["PUBLIC_SMOKE_ONLY"]="1"
os.environ["WEB_SESSION_SIGNING_KEY"]="test-signing-secret-for-account-isolation-20261116"
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
import api_v1
import app
import chatgpt_accounts
import web_chat


class ChatGPTAccountSafetyTests(unittest.TestCase):
    def setUp(self):
        self.a=TestClient(app.app,base_url="https://testserver")
        self.b=TestClient(app.app,base_url="https://testserver")
        self.a.__enter__(); self.b.__enter__()
        self.ca=self.a.get("/web/api/bootstrap").json()["csrf"]
        self.cb=self.b.get("/web/api/bootstrap").json()["csrf"]
        app.web2api_device=None
        app.active_job_id=None

    def tearDown(self):
        self.a.__exit__(None,None,None)
        self.b.__exit__(None,None,None)

    def owner(self,client):
        value=client.cookies.get(web_chat.COOKIE)
        assert value, "NO_SIGNED_TEST_COOKIE"
        raw=web_chat._unpack(value)
        assert raw, "BAD_SIGNED_TEST_COOKIE"
        return web_chat._owner_hash(raw)

    def insert_verified_fixture(self, client, subject, name):
        owner=self.owner(client)
        account_id="oai_"+api_v1.new_id()
        with api_v1.connection() as db:
            db.execute(
                "INSERT INTO hitel_verified_chatgpt_accounts "
                "(id,browser_owner,issuer,client_id,subject,email,display_name,active,verified_at)"
                " VALUES(?,?,?,?,?,?,?,?,?)",
                (account_id,owner,"https://auth.openai.com","oaiapp_fake_test_client",
                 subject,name+"@example.invalid",name,1,api_v1.clock())
            )
        return account_id

    def create_room(self,client,csrf):
        r=client.post("/web/api/rooms",json={"title":"계정 검증 격리 시험"},
            headers={"X-Web-Csrf":csrf})
        self.assertEqual(r.status_code,200,r.text)
        return r.json()["room"]["id"]

    def test_unconfigured_official_login_never_forges_account(self):
        with patch.object(chatgpt_accounts,"CLIENT_ID",""),\
             patch.object(chatgpt_accounts,"REDIRECT_URI",""):
            a=self.a.get("/web/api/chatgpt/accounts").json()
            self.assertEqual(a["accounts"],[])
            self.assertFalse(a["oauthAvailable"])
            self.assertFalse(a["executionAccountBound"])
            r=self.a.get("/web/api/chatgpt/login",follow_redirects=False)
            self.assertEqual(r.status_code,503)
            self.assertNotIn("set-cookie",r.headers)
            self.assertEqual(self.a.get("/web/api/chatgpt/accounts").json()["accounts"],[])

    def test_actual_identity_does_not_enable_shared_worker(self):
        room=self.create_room(self.a,self.ca)
        account=self.insert_verified_fixture(self.a,"subject-account-A","Account A")
        public=self.a.get("/web/api/chatgpt/accounts").json()
        self.assertTrue(public["connected"])
        self.assertFalse(public["executionAccountBound"])
        self.assertEqual(public["accounts"][0]["id"],account)
        self.assertFalse(public["accounts"][0]["canRunWeb2APIAsThisAccount"])
        attempted=self.a.post("/web/api/rooms/"+room+"/message",
            json={"text":"Do not send this under the default Chrome account",
                  "account_id":account},
            headers={"X-Web-Csrf":self.ca})
        self.assertEqual(attempted.status_code,200,attempted.text)
        self.assertFalse(attempted.json()["sentToChatGPT"])
        with api_v1.connection() as db:
            row=db.execute("SELECT account_id,status FROM jobs WHERE room_id=?",
                           (room,)).fetchone()
        self.assertEqual(row["account_id"],account)
        self.assertEqual(row["status"],"queued")

    def test_cross_browser_selection_and_unlink_are_blocked(self):
        account=self.insert_verified_fixture(self.a,"account-only-owner-A","Owner A")
        self.assertEqual(self.b.get("/web/api/chatgpt/accounts").json()["accounts"],[])
        self.assertEqual(self.b.post("/web/api/chatgpt/accounts/"+account+"/select",
            headers={"X-Web-Csrf":self.cb}).status_code,404)
        self.assertEqual(self.b.delete("/web/api/chatgpt/accounts/"+account,
            headers={"X-Web-Csrf":self.cb}).status_code,404)
        self.assertEqual(self.a.post("/web/api/chatgpt/accounts/"+account+"/select").status_code,403)
        self.assertEqual(self.a.delete("/web/api/chatgpt/accounts/"+account).status_code,403)
        self.assertEqual(self.a.post("/web/api/chatgpt/accounts/"+account+"/select",
            headers={"X-Web-Csrf":self.ca,"Origin":"https://attacker.invalid"}).status_code,403)
        self.assertEqual(len(self.a.get("/web/api/chatgpt/accounts").json()["accounts"]),1)

    def test_unlink_does_not_delete_real_account_and_reverts_to_trial(self):
        account=self.insert_verified_fixture(self.a,"account-only-owner-B","Owner B")
        res=self.a.delete("/web/api/chatgpt/accounts/"+account,
            headers={"X-Web-Csrf":self.ca})
        self.assertEqual(res.status_code,200,res.text)
        self.assertFalse(res.json()["chatgptAccountDeleted"])
        self.assertEqual(self.a.get("/web/api/chatgpt/accounts").json()["accounts"],[])
        room=self.create_room(self.a,self.ca)
        # Previous isolated trial remains available after merely removing
        # the verified identity association.
        reply=self.a.post("/web/api/rooms/"+room+"/message",
            json={"text":"Harmless fixed test after unlink"},
            headers={"X-Web-Csrf":self.ca})
        self.assertEqual(reply.status_code,200,reply.text)
        self.assertFalse(reply.json()["sentToChatGPT"])

    def test_switching_verified_identity_still_cannot_use_default_worker(self):
        first=self.insert_verified_fixture(self.a,"subject-A-switch","Switch A")
        with api_v1.connection() as db:
            db.execute("UPDATE hitel_verified_chatgpt_accounts SET active=0 WHERE id=?",(first,))
        second=self.insert_verified_fixture(self.a,"subject-B-switch","Switch B")
        for active in [first,second]:
            # A private ChatGPT conversation must never be shared across
            # execution accounts: each selected account uses its own room.
            room=self.create_room(self.a,self.ca)
            choice=self.a.post("/web/api/chatgpt/accounts/"+active+"/select",
                headers={"X-Web-Csrf":self.ca})
            self.assertEqual(choice.status_code,200,choice.text)
            self.assertFalse(choice.json()["canRunWeb2APIAsThisAccount"])
            r=self.a.post("/web/api/rooms/"+room+"/message",
                json={"text":"No wrong-account ChatGPT browser submission",
                      "account_id":active},
                headers={"X-Web-Csrf":self.ca})
            self.assertEqual(r.status_code,200,r.text)
            self.assertFalse(r.json()["sentToChatGPT"])
            with api_v1.connection() as db:
                item=db.execute("SELECT account_id FROM jobs WHERE id=?",
                                (r.json()["jobId"],)).fetchone()
                self.assertEqual(item["account_id"],active)
                db.execute("UPDATE jobs SET status='failed' WHERE id=?",
                           (r.json()["jobId"],))


if __name__=="__main__":
    unittest.main()
