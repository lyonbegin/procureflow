"""Account/room isolation and worker-routing regression tests.

Fixtures only: proves that a web-account prompt cannot go to the native
Android transport, leak into another ChatGPT room, or continue after unlink.
Does not fake a second actual ChatGPT sign-in.
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

_tmp=tempfile.TemporaryDirectory(prefix="hitel-advanced-isolation-")
os.environ["RELAY_DATA_DIR"]=_tmp.name
os.environ["PUBLIC_SMOKE_ONLY"]="1"
os.environ["WEB_SESSION_SIGNING_KEY"]="long-advanced-account-routing-signing-test-secret-20261116"
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
import api_v1
import app
import web_chat
import chatgpt_accounts


class AccountIsolationTests(unittest.TestCase):
    def setUp(self):
        with api_v1.connection() as c:
            c.execute("UPDATE jobs SET status='failed',stage='test_reset' "
                      "WHERE status IN ('queued','running')")
        app.device=None
        app.web2api_device=None
        app.active_job_id=None
        app.active_job_transport=None
        self.client=TestClient(app.app,base_url="https://testserver")
        self.client.__enter__()
        self.csrf=self.client.get("/web/api/bootstrap").json()["csrf"]
        self.owner=web_chat._owner_hash(web_chat._unpack(
            self.client.cookies.get(web_chat.COOKIE)))

    def tearDown(self):
        self.client.__exit__(None,None,None)
        app.device=None
        app.web2api_device=None
        app.active_job_id=None
        app.active_job_transport=None

    def new_room(self):
        r=self.client.post("/web/api/rooms",json={"title":"Account isolation"},
                           headers={"X-Web-Csrf":self.csrf})
        self.assertEqual(r.status_code,200,r.text)
        return r.json()["room"]["id"]

    def add_account(self,name,active):
        aid="oai_"+api_v1.new_id()
        with api_v1.connection() as c:
            if active:
                c.execute("UPDATE hitel_verified_chatgpt_accounts SET active=0 "
                          "WHERE browser_owner=?",(self.owner,))
            c.execute(
                "INSERT INTO hitel_verified_chatgpt_accounts "
                "(id,browser_owner,issuer,client_id,subject,email,display_name,active,verified_at) "
                "VALUES(?,?,?,?,?,?,?,?,?)",
                (aid,self.owner,"https://auth.openai.com","oaiapp_fixture",
                 "subject-"+aid,name+"@example.invalid",name,
                 int(active),api_v1.clock()),
            )
        return aid

    def select(self,aid):
        return self.client.post("/web/api/chatgpt/accounts/"+aid+"/select",
            headers={"X-Web-Csrf":self.csrf})

    def unlink(self,aid):
        return self.client.delete("/web/api/chatgpt/accounts/"+aid,
            headers={"X-Web-Csrf":self.csrf})

    def send(self,room,account):
        return self.client.post("/web/api/rooms/"+room+"/message",
            headers={"X-Web-Csrf":self.csrf},
            json={"text":"Only send via expected ChatGPT account","account_id":account})

    def state(self,jid):
        with api_v1.connection() as c:
            return dict(c.execute("SELECT status,stage,account_id FROM jobs WHERE id=?",
                                  (jid,)).fetchone())

    def test_01_room_guest_cannot_become_account_a(self):
        room=self.new_room()
        queued=self.send(room,None)
        self.assertEqual(queued.status_code,200,queued.text)
        aid=self.add_account("A",True)
        self.assertEqual(self.send(room,aid).status_code,409)
        with api_v1.connection() as c:
            row=c.execute("SELECT chatgpt_account_id FROM rooms WHERE id=?",(room,)).fetchone()
            self.assertEqual(row["chatgpt_account_id"],"__guest__")

    def test_02_account_a_room_cannot_send_as_b(self):
        room=self.new_room()
        a=self.add_account("A",True)
        b=self.add_account("B",False)
        r=self.send(room,a)
        self.assertEqual(r.status_code,200,r.text)
        with api_v1.connection() as c:
            c.execute("UPDATE jobs SET status='failed' WHERE id=?",(r.json()["jobId"],))
        self.assertEqual(self.select(b).status_code,200)
        self.assertEqual(self.send(room,b).status_code,409)
        with api_v1.connection() as c:
            self.assertEqual(c.execute("SELECT chatgpt_account_id FROM rooms WHERE id=?",
                                       (room,)).fetchone()[0],a)

    def test_03_account_b_uses_separate_room_a_can_resume_original(self):
        a=self.add_account("A",True)
        b=self.add_account("B",False)
        ar=self.new_room()
        br=self.new_room()
        for aid,room in ((a,ar),(b,br),(a,ar)):
            self.assertEqual(self.select(aid).status_code,200)
            r=self.send(room,aid)
            self.assertEqual(r.status_code,200,r.text)
            self.assertIs(r.json()["sentToChatGPT"],False)
            with api_v1.connection() as c:
                self.assertEqual(c.execute("SELECT chatgpt_account_id FROM rooms "
                                  "WHERE id=?",(room,)).fetchone()[0],aid)
                c.execute("UPDATE jobs SET status='failed' WHERE id=?",(r.json()["jobId"],))

    def test_04_android_only_can_claim_guest_not_targeted_account(self):
        guest_room=self.new_room()
        guest=self.send(guest_room,None)
        self.assertEqual(guest.status_code,200)
        a=self.add_account("A",True)
        ar=self.new_room()
        targeted=self.send(ar,a)
        self.assertEqual(targeted.status_code,200)
        claimed=api_v1.claim_next_job(public_trial_only=True,allow_account_bound=False)
        self.assertEqual(claimed["id"],guest.json()["jobId"])
        self.assertIsNone(claimed["account_id"])
        self.assertEqual(self.state(targeted.json()["jobId"])["status"],"queued")

    def test_05_targeted_prompt_stays_queued_without_web_worker(self):
        a=self.add_account("A",True)
        room=self.new_room()
        jid=self.send(room,a).json()["jobId"]
        claimed=api_v1.claim_next_job(public_trial_only=True,allow_account_bound=False)
        self.assertIsNone(claimed)
        self.assertEqual(self.state(jid)["status"],"queued")

    def test_06_remove_account_cancels_unsent_job_atomically(self):
        a=self.add_account("A",True)
        room=self.new_room()
        jid=self.send(room,a).json()["jobId"]
        result=self.unlink(a)
        self.assertEqual(result.status_code,200,result.text)
        self.assertEqual(result.json()["cancelledQueuedJobs"],1)
        self.assertFalse(result.json()["chatgptAccountDeleted"])
        self.assertEqual(self.state(jid)["status"],"failed")
        self.assertEqual(self.state(jid)["stage"],"ACCOUNT_UNLINKED")
        self.assertEqual(self.send(room,None).status_code,409)

    def test_07_unlink_running_account_returns_conflict(self):
        a=self.add_account("A",True)
        jid=self.send(self.new_room(),a).json()["jobId"]
        with api_v1.connection() as c:
            c.execute("UPDATE jobs SET status='running' WHERE id=?",(jid,))
        response=self.unlink(a)
        self.assertEqual(response.status_code,409,response.text)
        self.assertEqual(len(self.client.get("/web/api/chatgpt/accounts").json()["accounts"]),1)
        with api_v1.connection() as c:
            c.execute("UPDATE jobs SET status='failed' WHERE id=?",(jid,))
        self.assertEqual(self.unlink(a).status_code,200)

    def test_08_unlink_a_does_not_cancel_b_queue(self):
        a=self.add_account("A",True)
        ra=self.new_room()
        ja=self.send(ra,a).json()["jobId"]
        b=self.add_account("B",False)
        self.assertEqual(self.select(b).status_code,200)
        rb=self.new_room()
        jb=self.send(rb,b).json()["jobId"]
        self.assertEqual(self.unlink(a).status_code,200)
        self.assertEqual(self.state(ja)["stage"],"ACCOUNT_UNLINKED")
        self.assertEqual(self.state(jb)["status"],"queued")

    def test_09_old_guest_conversation_migrates_to_guest_binding(self):
        room=self.new_room()
        with api_v1.connection() as c:
            c.execute("UPDATE rooms SET chatgpt_url=?,chatgpt_account_id=NULL WHERE id=?",
                    ("https://chatgpt.com/c/a1234567-1234-4123-8123-123456789012",room))
        api_v1.init_db()
        with api_v1.connection() as c:
            self.assertEqual(c.execute("SELECT chatgpt_account_id FROM rooms WHERE id=?",
                             (room,)).fetchone()[0],"__guest__")
        a=self.add_account("A",True)
        self.assertEqual(self.send(room,a).status_code,409)

    def test_10_queued_account_remains_pinned_after_selection(self):
        a=self.add_account("A",True)
        b=self.add_account("B",False)
        ja=self.send(self.new_room(),a).json()["jobId"]
        self.assertEqual(self.select(b).status_code,200)
        self.assertEqual(self.state(ja)["account_id"],a)


if __name__=="__main__":
    unittest.main()
