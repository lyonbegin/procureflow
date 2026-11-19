"""HITEL synthetic multi-room concurrency: no real ChatGPT conversation touched."""
import asyncio
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

_root=tempfile.TemporaryDirectory(prefix="hitel-room-dispatch-")
os.environ["RELAY_DATA_DIR"]=_root.name
os.environ["PUBLIC_SMOKE_ONLY"]="1"
os.environ["WEB_SESSION_SIGNING_KEY"]="synthetic-room-dispatch-test-only"
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
import app
import api_v1
import integration_public
import long_job_events

class FakeChromeSocket:
    def __init__(self):
        self.sent=[]
    async def send_json(self,item):
        self.sent.append(item)

class MultiRoomDispatchTests(unittest.TestCase):
    def setUp(self):
        self.client=TestClient(app.app)
        self.client.__enter__()
        self.ws=FakeChromeSocket()
        app.web2api_device=self.ws
        app.web2api_last_seen_monotonic=time.monotonic()
        app.web2api_active_jobs.clear()
        app.active_job_id=None
        app.active_job_transport=None
        app.recovery_checked=True
        api_v1.on_new_job=None
        with api_v1.connection() as db:
            db.execute("DELETE FROM hitel_public_link_requests")
            db.execute("DELETE FROM hitel_public_named_rooms")
            db.execute("DELETE FROM hitel_public_job_observations")
            db.execute("DELETE FROM messages WHERE user_id=?", (integration_public.USER_ID,))
            db.execute("DELETE FROM jobs WHERE user_id=?", (integration_public.USER_ID,))
            db.execute("DELETE FROM rooms WHERE user_id=?", (integration_public.USER_ID,))

    def tearDown(self):
        self.client.__exit__(None,None,None)
        api_v1.on_new_job=app.notify_new_job
        app.web2api_device=None
        app.web2api_active_jobs.clear()
        app.active_job_id=None

    def enqueue(self,name,suffix):
        room=self.client.post("/integrations/v1/public/rooms",
             json={"name":name}).json()["room_id"]
        r=self.client.post("/integrations/v1/public/chat",json={
             "room_id":room,"text":"Synthetic isolation question",
             "request_id":"room-isolation-"+suffix+"-20261120"})
        self.assertEqual(r.status_code,202,r.text)
        return r.json()["job_id"],room

    def test_busy_research_does_not_block_other_room_reply(self):
        a,room_a=self.enqueue("A-group-research","a")
        b,room_b=self.enqueue("Scribd-classification","b")
        asyncio.run(app.dispatch_next())
        self.assertEqual(app.web2api_active_jobs,{a:room_a,b:room_b})
        self.assertEqual([x["job"]["id"] for x in self.ws.sent if x["type"]=="job"],
                         [a,b])
        # Five read-only polls may not submit another question.
        for _ in range(5):
            status=self.client.get("/integrations/v1/public/jobs/"+a).json()
            self.assertEqual(status["status"],"running")
            self.assertIsNone(status["chatgpt_send_confirmed"])
        self.assertEqual(len(self.ws.sent),2)
        # B completes while A remains in-flight. Never mix their rooms.
        with api_v1.connection() as db:
            active_a=db.execute("SELECT status FROM jobs WHERE id=?",(a,)).fetchone()[0]
        self.assertEqual(active_a,"running")
        self.assertTrue(api_v1.complete_web2api_job(
            b,room_b,'{"rows":[{"title":"교재"}]}',
            "https://chatgpt.com/c/aaaa1111-2222-3333-4444-555555555555"))
        app.web2api_active_jobs.pop(b,None)
        result=self.client.get("/integrations/v1/public/jobs/"+b).json()
        self.assertEqual(result["status"],"completed")
        self.assertEqual(result["room_id"],room_b)
        self.assertEqual(self.client.get("/integrations/v1/public/jobs/"+a).json()["status"],
                         "running")
        status=self.client.get("/integrations/v1/public/status").json()
        self.assertFalse(status["worker_busy"])
        self.assertTrue(status["worker_available_for_new_job"])
        self.assertEqual(status["worker_active_jobs_count"],1)

    def test_one_room_serially_queued_and_unknown_blocks_resubmission(self):
        a,room=self.enqueue("A-research-serialized","serialized-a")
        with api_v1.connection() as db:
            second=api_v1.store_job(db,integration_public.USER_ID,room,
                                    "chat.send","Second question",[])
        asyncio.run(app.dispatch_next())
        sent=[x["job"]["id"] for x in self.ws.sent if x["type"]=="job"]
        self.assertEqual(sent,[a])
        with api_v1.connection() as db:
            self.assertEqual(db.execute(
                "SELECT status FROM jobs WHERE id=?",(second,)).fetchone()[0],"queued")
        api_v1.update_job(a,status="unknown",stage="connection_lost",
                          error="Uncertain ChatGPT delivery; no resend")
        app.web2api_active_jobs.pop(a,None)
        asyncio.run(app.dispatch_next())
        self.assertEqual([x["job"]["id"] for x in self.ws.sent if x["type"]=="job"],[a])
        # Unknown blocks the room. It must not be converted to a new send.
        response=self.client.post("/integrations/v1/public/chat",json={
             "room_id":room,"text":"New prompt",
             "request_id":"room-isolation-serialized-b-20261120"})
        self.assertEqual(response.status_code,409)

if __name__=="__main__":
    unittest.main()
