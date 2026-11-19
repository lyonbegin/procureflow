"""No-login public text link: isolated queue, real guest worker contract, privacy.

Everything in this suite is synthetic. It never starts GitHub Actions or
sends a ChatGPT message, and no owner credentials are used.
"""
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

_root=tempfile.TemporaryDirectory(prefix="hitel-public-link-")
os.environ["RELAY_DATA_DIR"]=_root.name
os.environ["PUBLIC_SMOKE_ONLY"]="1"
os.environ["WEB_SESSION_SIGNING_KEY"]="synthetic-public-link-test-only"
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
import api_v1
import app
import integration_public
import worker_autostart


class PublicNoLoginContract(unittest.TestCase):
    def setUp(self):
        self.client=TestClient(app.app,base_url="https://testserver")
        self.client.__enter__()
        app.web2api_device=None
        app.active_job_id=None
        api_v1.on_new_job=app.notify_new_job
        with api_v1.connection() as db:
            db.execute("DELETE FROM hitel_public_named_rooms")
            db.execute("DELETE FROM hitel_public_link_requests")
            db.execute("DELETE FROM messages WHERE user_id=?",(integration_public.USER_ID,))
            db.execute("DELETE FROM jobs WHERE user_id=?",(integration_public.USER_ID,))
            db.execute("DELETE FROM rooms WHERE user_id=?",(integration_public.USER_ID,))
            db.execute("""UPDATE hitel_chrome_autostart SET
                 status='idle',dispatch_count=0,failures=0,
                 next_attempt_at=0,lock_until=0,last_failure=NULL WHERE id=1""")

    def tearDown(self):
        self.client.__exit__(None,None,None)
        app.web2api_device=None
        app.active_job_id=None

    def test_link_and_status_are_public(self):
        self.assertEqual(self.client.get("/integrations/public").status_code,200)
        p=self.client.get("/integrations/v1/public/status")
        self.assertEqual(p.status_code,200)
        self.assertFalse(p.json()["login_required"])
        self.assertFalse(p.json()["hitel_api_key_required"])
        self.assertFalse(p.json()["new_conversation_per_question"])
        self.assertTrue(p.json()["same_room_name_reuses_conversation"])

    def test_worker_busy_and_heartbeat_are_distinct_from_connection(self):
        # Simulate state only; no real worker, GitHub Actions or ChatGPT send.
        app.web2api_device=object()
        app.web2api_last_seen_monotonic=time.monotonic()
        app.active_job_id="job_synthetic_do_not_expose"
        state=self.client.get("/integrations/v1/public/status").json()
        self.assertTrue(state["worker_connected"])
        self.assertTrue(state["worker_heartbeat_recent"])
        self.assertTrue(state["worker_busy"])
        self.assertFalse(state["worker_available_for_new_job"])
        self.assertNotIn("job_synthetic_do_not_expose",str(state))
        app.active_job_id=None
        state=self.client.get("/integrations/v1/public/status").json()
        self.assertTrue(state["worker_available_for_new_job"])
        app.web2api_last_seen_monotonic=time.monotonic()-100
        state=self.client.get("/integrations/v1/public/status").json()
        self.assertFalse(state["worker_heartbeat_recent"])
        self.assertFalse(state["worker_available_for_new_job"])
        app.web2api_device=None
        app.web2api_last_seen_monotonic=0

    def test_not_configured_reports_503_instead_of_fake_success(self):
        with patch.dict(os.environ,{"HITEL_GITHUB_ACTIONS_TOKEN":"",
                "HITEL_GITHUB_APP_ID":"",
                "HITEL_GITHUB_APP_INSTALLATION_ID":"",
                "HITEL_GITHUB_APP_PRIVATE_KEY":""}):
            r=self.client.post("/integrations/v1/public/chat",
                json={"text":"public test message"})
        self.assertEqual(r.status_code,503,r.text)
        self.assertEqual(worker_autostart.pending_count(),0)

    def test_no_login_post_auto_launch_idempotent_and_private_isolation(self):
        env={"HITEL_GITHUB_ACTIONS_TOKEN":"synthetic-not-real",
             "HITEL_GITHUB_APP_ID":"",
             "HITEL_GITHUB_APP_INSTALLATION_ID":"",
             "HITEL_GITHUB_APP_PRIVATE_KEY":""}
        with patch.dict(os.environ,env):
            with patch.object(worker_autostart,"_dispatch_with_fallback",
                              return_value="fine_grained_token") as dispatch:
                body={"text":"Synthetic no-login question",
                      "request_id":"public-request-20261119-0001"}
                first=self.client.post("/integrations/v1/public/chat",json=body)
                self.assertEqual(first.status_code,202,first.text)
                d=first.json()
                self.assertTrue(d["accepted"])
                self.assertFalse(d["sent_to_chatgpt"])
                self.assertEqual(dispatch.call_count,1)
                job_id=d["job_id"]
                again=self.client.post("/integrations/v1/public/chat",json=body)
                self.assertEqual(again.status_code,202,again.text)
                self.assertTrue(again.json()["replayed"])
                self.assertEqual(again.json()["job_id"],job_id)
                self.assertEqual(dispatch.call_count,1)
                changed=dict(body,text="Different prompt")
                conflict=self.client.post("/integrations/v1/public/chat",json=changed)
                self.assertEqual(conflict.status_code,409)
                self.assertEqual(worker_autostart.pending_count(),1)

                waiting=self.client.get(d["result_url"])
                self.assertEqual(waiting.status_code,200)
                self.assertEqual(waiting.json()["status"],"queued")
                self.assertIsNone(waiting.json()["result_text"])

                claimed=api_v1.claim_next_job(public_trial_only=True,
                                              allow_account_bound=True)
                self.assertEqual(claimed["id"],job_id)
                self.assertEqual(claimed["user_id"],integration_public.USER_ID)
                self.assertIsNone(claimed["account_id"])
                self.assertFalse(claimed["target_chatgpt_url"])
                self.assertEqual(claimed["attachment_ids"],[])
                self.assertTrue(api_v1.complete_web2api_job(
                    job_id,claimed["room_id"],"Synthetic verified reply",
                    "https://chatgpt.com/c/12345678-abcd-1234"))
                result=self.client.get(d["result_url"])
                self.assertEqual(result.status_code,200)
                self.assertEqual(result.json()["status"],"completed")
                self.assertEqual(result.json()["result_text"],
                                 "Synthetic verified reply")
                self.assertNotIn("chatgpt_url",result.json())
                self.assertEqual(worker_autostart.pending_count(),0)

    def test_same_named_room_preserves_conversation_across_questions(self):
        env={"HITEL_GITHUB_ACTIONS_TOKEN":"synthetic",
             "HITEL_GITHUB_APP_ID":"","HITEL_GITHUB_APP_INSTALLATION_ID":"",
             "HITEL_GITHUB_APP_PRIVATE_KEY":""}
        with patch.dict(os.environ,env):
            with patch.object(worker_autostart,"_dispatch_with_fallback",
                              return_value="fine_grained_token"):
                open1=self.client.post("/integrations/v1/public/rooms",
                    json={"name":"교재 분류"}).json()
                open2=self.client.post("/integrations/v1/public/rooms",
                    json={"name":"  교재   분류 "}).json()
                self.assertEqual(open1["room_id"],open2["room_id"])
                self.assertTrue(open1["created"])
                self.assertFalse(open2["created"])

                first=self.client.post("/integrations/v1/public/chat",
                    json={"room_name":"교재 분류","text":"첫 질문",
                          "request_id":"same-room-req-20261119-0001"})
                self.assertEqual(first.status_code,202,first.text)
                job1=api_v1.claim_next_job(
                    public_trial_only=True,allow_account_bound=True)
                self.assertEqual(job1["room_id"],open1["room_id"])
                self.assertIsNone(job1["target_conversation_id"])
                url="https://chatgpt.com/c/11111111-2222-3333-4444-555555555555"
                self.assertTrue(api_v1.complete_web2api_job(
                    job1["id"],job1["room_id"],"첫 답변",url))
                self.assertEqual(self.client.get(
                    first.json()["result_url"]).json()["status"],"completed")

                second=self.client.post("/integrations/v1/public/chat",
                    json={"room_name":"교재 분류","text":"앞의 답변에 이어서",
                          "request_id":"same-room-req-20261119-0002"})
                self.assertEqual(second.status_code,202,second.text)
                self.assertEqual(second.json()["room_id"],open1["room_id"])
                job2=api_v1.claim_next_job(
                    public_trial_only=True,allow_account_bound=True)
                self.assertEqual(job2["target_conversation_id"],
                    "11111111-2222-3333-4444-555555555555")
                self.assertEqual(job2["target_chatgpt_url"],url)
                self.assertTrue(api_v1.complete_web2api_job(
                    job2["id"],job2["room_id"],"두 번째 답변",url))

                by_id=self.client.post("/integrations/v1/public/chat",
                    json={"room_id":open1["room_id"],"text":"세 번째 질문",
                          "request_id":"same-room-req-20261119-0003"})
                self.assertEqual(by_id.status_code,202,by_id.text)
                job3=api_v1.claim_next_job(
                    public_trial_only=True,allow_account_bound=True)
                self.assertEqual(job3["target_chatgpt_url"],url)
                self.assertTrue(api_v1.complete_web2api_job(
                    job3["id"],job3["room_id"],"세 번째 답변",url))

    def test_switch_name_only_creates_new_room_or_opens_it(self):
        env={"HITEL_GITHUB_ACTIONS_TOKEN":"synthetic",
             "HITEL_GITHUB_APP_ID":"","HITEL_GITHUB_APP_INSTALLATION_ID":"",
             "HITEL_GITHUB_APP_PRIVATE_KEY":""}
        with patch.dict(os.environ,env):
            with patch.object(worker_autostart,"_dispatch_with_fallback",
                              return_value="fine_grained_token"):
                a=self.client.post("/integrations/v1/public/rooms",
                    json={"name":"첫 방"}).json()
                b=self.client.post("/integrations/v1/public/rooms",
                    json={"name":"두 번째 방"}).json()
                self.assertNotEqual(a["room_id"],b["room_id"])
                self.assertEqual(self.client.post("/integrations/v1/public/rooms",
                    json={"name":"첫 방"}).json()["room_id"],a["room_id"])
                self.assertEqual(self.client.post("/integrations/v1/public/rooms",
                    json={"name":"두 번째 방"}).json()["room_id"],b["room_id"])
                rooms=self.client.get("/integrations/v1/public/rooms").json()["rooms"]
                self.assertEqual({r["room_name"] for r in rooms},
                                 {"첫 방","두 번째 방"})
                first=self.client.post("/integrations/v1/public/chat",
                    json={"room_name":"첫 방","text":"첫 방 질문",
                          "request_id":"switch-rooms-req-20261119-0001"})
                self.assertEqual(first.status_code,202)
                self.assertEqual(first.json()["room_id"],a["room_id"])
                job=api_v1.claim_next_job(public_trial_only=True,
                                           allow_account_bound=True)
                self.assertIsNone(job["target_chatgpt_url"])
                url="https://chatgpt.com/c/22222222-2222-3333-4444-555555555555"
                self.assertTrue(api_v1.complete_web2api_job(
                    job["id"],job["room_id"],"답변",url))
                switched=self.client.post("/integrations/v1/public/chat",
                    json={"room_name":"두 번째 방","text":"두 번째 방 질문",
                          "request_id":"switch-rooms-req-20261119-0002"})
                self.assertEqual(switched.status_code,202)
                self.assertEqual(switched.json()["room_id"],b["room_id"])
                target=api_v1.claim_next_job(public_trial_only=True,
                                              allow_account_bound=True)
                self.assertIsNone(target["target_conversation_id"])

    def test_explicit_new_room_replaces_name_only_when_requested(self):
        first=self.client.post("/integrations/v1/public/rooms",
            json={"name":"원래 방"}).json()
        opened=self.client.post("/integrations/v1/public/rooms",
            json={"name":"원래 방"}).json()
        self.assertEqual(first["room_id"],opened["room_id"])
        fresh=self.client.post("/integrations/v1/public/rooms",
            json={"name":"원래 방","create_new":True}).json()
        self.assertTrue(fresh["created"])
        self.assertNotEqual(first["room_id"],fresh["room_id"])
        selected=self.client.post("/integrations/v1/public/rooms",
            json={"name":"원래 방"}).json()
        self.assertEqual(selected["room_id"],fresh["room_id"])
        # The old room ID remains usable if the caller explicitly selects it.
        with patch.dict(os.environ,{"HITEL_GITHUB_ACTIONS_TOKEN":"synthetic"}):
            with patch.object(worker_autostart,"_dispatch_with_fallback",
                              return_value="fine_grained_token"):
                old=self.client.post("/integrations/v1/public/chat",
                    json={"room_id":first["room_id"],"text":"기존 방의 질문",
                          "request_id":"old-room-explicit-20261119-0001"})
        self.assertEqual(old.status_code,202,old.text)
        self.assertEqual(old.json()["room_id"],first["room_id"])

    def test_default_room_compatible_with_original_one_field_chat(self):
        with patch.dict(os.environ,{"HITEL_GITHUB_ACTIONS_TOKEN":"synthetic"}):
            with patch.object(worker_autostart,"_dispatch_with_fallback",
                              return_value="fine_grained_token"):
                r=self.client.post("/integrations/v1/public/chat",
                    json={"text":"old simple client request"})
        self.assertEqual(r.status_code,202,r.text)
        self.assertEqual(r.json()["room_name"],"기본 대화방")
        opened=self.client.post("/integrations/v1/public/rooms",
            json={"name":"기본 대화방"}).json()
        self.assertEqual(opened["room_id"],r.json()["room_id"])

    def test_private_jobs_cannot_be_read_through_public_url(self):
        uid="usr_test_private_not_public"
        with api_v1.connection() as db:
            now=api_v1.clock()
            room="room_"+api_v1.new_id()
            db.execute("""INSERT INTO users(id,name,api_key_hash,created_at)
                VALUES(?,?,?,?)""",(uid,"private","disabled-private",now))
            db.execute("""INSERT INTO rooms(id,user_id,title,
                android_state,created_at,updated_at) VALUES(?,?,?,?,?,?)""",
                (room,uid,"private room","uncreated",now,now))
            jid=api_v1.store_job(db,uid,room,"chat.send","private text",[])
        r=self.client.get("/integrations/v1/public/jobs/"+jid)
        self.assertEqual(r.status_code,404)


if __name__=="__main__":
    unittest.main()
