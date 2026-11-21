"""Task ID isolation, data-plane routing and authenticated worker-scope tests.

All data is synthetic, using temporary SQLite. NO GitHub dispatch and NO AI
question is sent: the WebSocket tests use an explicitly mocked verified OIDC
claim and only an in-process FastAPI TestClient.
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

_root=tempfile.TemporaryDirectory(prefix="hitel-isolated-task-test-")
os.environ["RELAY_DATA_DIR"]=_root.name
os.environ["PUBLIC_SMOKE_ONLY"]="1"
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
import api_v1
import app
import integration_public as public
import task_worker_isolation as isolation


class TaskIsolationTests(unittest.TestCase):
    def setUp(self):
        self.client=TestClient(app.app)
        self.client.__enter__()
        isolation.sessions.clear()
        self.producer_patcher=patch.object(
            isolation,"verify_isolated_task_producer",return_value=True)
        self.mock_producer=self.producer_patcher.start()
        with api_v1.connection() as db:
            db.execute("DELETE FROM hitel_isolated_job_map")
            db.execute("DELETE FROM hitel_public_link_requests")
            db.execute("DELETE FROM hitel_public_named_rooms")
            db.execute("DELETE FROM messages WHERE user_id=?",(public.USER_ID,))
            db.execute("DELETE FROM jobs WHERE user_id=?",(public.USER_ID,))
            db.execute("DELETE FROM rooms WHERE user_id=?",(public.USER_ID,))

    def tearDown(self):
        self.client.__exit__(None,None,None)
        isolation.sessions.clear()
        self.producer_patcher.stop()

    def queue(self,task,req,room):
        return self.client.post(
            "/integrations/v1/public/isolated/tasks/"+task+"/chat",
            json={"request_id":req,"room_name":room,
                  "text":"Synthetic sample; never forwarded to ChatGPT in this test"})

    def test_tasks_are_distinct_even_with_identical_room_names(self):
        a=self.queue("stock-a","test-stock-a-immutable-0001","Research")
        b=self.queue("scribd-18109","test-scribd-immutable-0001","Research")
        self.assertEqual((a.status_code,b.status_code),(202,202))
        self.assertNotEqual(a.json()["job_id"],b.json()["job_id"])
        self.assertNotEqual(a.json()["room_id"],b.json()["room_id"])
        self.assertIn("STOCK-A",isolation.task_room("stock-a","Research"))
        self.assertIn("SCRIBD-18109",isolation.task_room("scribd-18109","Research"))

    def test_old_shared_chrome_cannot_steal_isolated_queue(self):
        self.queue("stock-a","test-stock-a-immutable-0002","Stock")
        job=api_v1.claim_next_job(
            only_user_id=public.USER_ID,allow_account_bound=True,
            web_text_only=True)
        self.assertIsNone(job)
        own=api_v1.claim_next_job(
            only_user_id=public.USER_ID,allow_account_bound=True,
            web_text_only=True,task_id="stock-a")
        self.assertIsNotNone(own)
        self.assertEqual(own["room"]["title"],
                         isolation.task_room("stock-a","Stock"))
        foreign=api_v1.claim_next_job(
            only_user_id=public.USER_ID,allow_account_bound=True,
            web_text_only=True,task_id="scribd-18109")
        self.assertIsNone(foreign)

    def test_idempotent_request_replay_never_creates_second_job(self):
        one=self.queue("stock-a","test-stock-a-immutable-0003","Room")
        two=self.queue("stock-a","test-stock-a-immutable-0003","Room")
        self.assertEqual(one.json()["job_id"],two.json()["job_id"])
        self.assertTrue(two.json()["replayed"])
        with api_v1.connection() as c:
            self.assertEqual(c.execute(
                "SELECT count(*) FROM hitel_isolated_job_map").fetchone()[0],1)

    def test_foreign_task_cannot_reuse_request(self):
        self.queue("stock-a","test-stock-a-immutable-0004","Room")
        foreign=self.queue("scribd-18109","test-stock-a-immutable-0004","Room")
        self.assertEqual(foreign.status_code,409)

    def test_same_request_retargeted_text_is_rejected(self):
        self.queue("stock-a","test-stock-a-immutable-0005","Room")
        r=self.client.post(
            "/integrations/v1/public/isolated/tasks/stock-a/chat",
            json={"request_id":"test-stock-a-immutable-0005",
                  "room_name":"Room","text":"Changed prompt!"})
        self.assertEqual(r.status_code,409)

    def test_second_unresolved_question_same_room_refused(self):
        self.queue("stock-a","test-stock-a-immutable-0006","Room")
        r=self.queue("stock-a","test-stock-a-immutable-0007","Room")
        self.assertEqual(r.status_code,409)

    def test_railway_task_registry_only_reports_counts(self):
        self.queue("stock-a","test-stock-a-immutable-0008","Room")
        r=self.client.get("/integrations/v1/public/isolated/tasks/pending")
        self.assertEqual(r.status_code,200)
        items={x["task_id"]:x for x in r.json()["tasks"]}
        self.assertEqual(items["stock-a"]["queued_jobs_count"],1)
        self.assertEqual(items["scribd-18109"]["queued_jobs_count"],0)
        self.assertNotIn("text",str(r.json()).lower())

    def test_unsigned_project_cannot_enqueue_task(self):
        self.mock_producer.return_value=False
        r=self.queue("stock-a","test-stock-a-immutable-0200","Room")
        self.assertEqual(r.status_code,403)
        with api_v1.connection() as db:
            self.assertEqual(db.execute(
                "SELECT COUNT(*) FROM hitel_isolated_job_map").fetchone()[0],0)

    def test_unknown_task_rejected_before_creating_job(self):
        r=self.queue("unrelated","test-stock-a-immutable-0009","Room")
        self.assertEqual(r.status_code,404)

    def test_wrong_task_oidc_handshake_refused(self):
        with patch.object(isolation,"verify_isolated_worker_identity",
                          return_value=None):
            with self.client.websocket_connect("/ws/task/stock-a") as ws:
                ws.send_json({"role":"web2api","task_id":"stock-a",
                    "hitel_protocol_version":4,"oidc_token":"invalid"})
                from starlette.websockets import WebSocketDisconnect
                with self.assertRaises(WebSocketDisconnect):
                    ws.receive_json()

    def test_right_worker_receives_only_its_task_job(self):
        a=self.queue("stock-a","test-stock-a-immutable-0010","R1")
        b=self.queue("scribd-18109","test-scribd-immutable-0010","R1")
        with patch.object(isolation,"verify_isolated_worker_identity",
                          return_value={"run_id":"1234"}):
            with self.client.websocket_connect("/ws/task/stock-a") as ws:
                ws.send_json({"role":"web2api","task_id":"stock-a",
                    "hitel_protocol_version":4,"oidc_token":"synthetic"})
                hello=ws.receive_json()
                self.assertEqual(hello["task_id"],"stock-a")
                self.assertEqual(ws.receive_json(),
                                 {"type":"room.bootstrap","rooms":[]})
                ws.send_json({"type":"room.bootstrap.done","ready_rooms":[]})
                job=ws.receive_json()
                self.assertEqual(job["type"],"job")
                self.assertEqual(job["job"]["id"],a.json()["job_id"])
                self.assertNotEqual(job["job"]["id"],b.json()["job_id"])
                # Completion is not spoofed by wrong-room identity.
                ws.send_json({"type":"job.result",
                    "job_id":b.json()["job_id"],
                    "room_id":b.json()["room_id"],
                    "verified":True,"stage":"assistant_reply_stable",
                    "result_text":"CROSS-TASK-SPOOF"})
                with api_v1.connection() as db:
                    other=db.execute("SELECT status FROM jobs WHERE id=?",
                        (b.json()["job_id"],)).fetchone()["status"]
                self.assertEqual(other,"queued")


if __name__=="__main__":
    unittest.main()
