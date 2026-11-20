"""Isolated synthetic tests of observable status and immutable final-result retrieval."""
import base64
import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

_root=tempfile.TemporaryDirectory(prefix="hitel-long-job-test-")
os.environ["RELAY_DATA_DIR"]=_root.name
os.environ["PUBLIC_SMOKE_ONLY"]="1"
os.environ["WEB_SESSION_SIGNING_KEY"]="synthetic-long-job-test-only"
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
import api_v1
import app
import long_job_events

class LongJobTests(unittest.TestCase):
    def setUp(self):
        self.client=TestClient(app.app,base_url="https://testserver")
        self.client.__enter__()
        app.web2api_device=object()  # Synthetic mock; NO Chrome action is performed.
        app.web2api_last_seen_monotonic=0.0
        app.active_job_id=None
        api_v1.on_new_job=None
        self.request_id="stock-real-client-test-"+api_v1.new_id()
        self.room=self.client.post("/integrations/v1/public/rooms",
                         json={"name":"SYNTHETIC-LONG-"+api_v1.new_id()}).json()["room_id"]

    def tearDown(self):
        self.client.__exit__(None,None,None)
        app.web2api_device=None
        app.active_job_id=None
        api_v1.on_new_job=app.notify_new_job

    def create_job(self):
        response=self.client.post("/integrations/v1/public/chat",json={
            "room_id":self.room,"text":"synthetic JSON test",
            "request_id":self.request_id})
        self.assertEqual(response.status_code,202,response.text)
        job=response.json()["job_id"]
        self.assertFalse(response.json()["sent_to_chatgpt"])
        self.assertEqual(self.client.get("/integrations/v1/public/requests/"+
                         self.request_id).json()["job_id"],job)
        return job

    def test_observed_only_and_immutable_chunks(self):
        job=self.create_job()
        base="/integrations/v1/public/jobs/"+job
        queued=self.client.get(base).json()
        self.assertEqual(queued["status"],"queued")
        self.assertEqual(queued["request_id"],self.request_id)
        self.assertIsNone(queued["chatgpt_send_confirmed"])
        self.assertIsNone(queued["job_last_progress_at"])
        self.assertFalse(queued["result_ready"])
        self.assertEqual(self.client.get(base+"/result").status_code,409)
        claimed=api_v1.claim_next_job(public_trial_only=True,allow_account_bound=True)
        self.assertEqual(claimed["id"],job)
        long_job_events.observe(job,"worker_received")
        before=self.client.get(base).json()["job_last_progress_at"]
        long_job_events.heartbeat(job)
        pulse=self.client.get(base).json()
        self.assertEqual(pulse["job_last_progress_at"],before)
        self.assertIsNotNone(pulse["worker_heartbeat_at"])
        self.assertIsNone(pulse["chatgpt_send_confirmed"])
        raw=json.dumps({"research":"한국어"*40000},ensure_ascii=False)
        self.assertTrue(api_v1.complete_web2api_job(
            job,self.room,raw,
            "https://chatgpt.com/c/aaaa1111-bbbb-2222-cccc-333333333333"))
        long_job_events.observe(job,"assistant_reply_verified",
                               send_confirmed=True,reply_observed=True)
        final=self.client.get(base).json()
        self.assertEqual(final["status"],"completed")
        self.assertTrue(final["result_ready"])
        self.assertTrue(final["result_json_valid"])
        self.assertTrue(final["chatgpt_send_confirmed"])
        self.assertTrue(final["assistant_reply_observed"])
        self.assertIsNone(final["result_text"])  # large reply via immutable chunks
        self.assertEqual(final["result_sha256"],hashlib.sha256(raw.encode()).hexdigest())
        received=bytearray()
        while len(received)<final["result_length_bytes"]:
            p=self.client.get(base+"/result",params={
                "offset":len(received),"limit":65536})
            self.assertEqual(p.status_code,200,p.text[:400])
            obj=p.json()
            self.assertEqual(obj["request_id"],self.request_id)
            self.assertEqual(obj["offset"],len(received))
            received.extend(base64.b64decode(obj["content_base64"],validate=True))
        self.assertEqual(bytes(received),raw.encode("utf-8"))
        self.assertEqual(hashlib.sha256(received).hexdigest(),final["result_sha256"])
        self.assertEqual(json.loads(received)["research"],"한국어"*40000)
        self.assertEqual(self.client.get(base+"/result?offset=99999999").status_code,416)
        self.assertEqual(self.client.get(base).json()["result_sha256"],final["result_sha256"])
        # GET must never create extra queue entries.
        with api_v1.connection() as db:
            count=db.execute("SELECT count(*) FROM hitel_public_link_requests WHERE request_id=?",
                             (self.request_id,)).fetchone()[0]
        self.assertEqual(count,1)

    def test_unknown_and_disconnected_are_not_ai_failures(self):
        job=self.create_job()
        with api_v1.connection() as db:
            db.execute("UPDATE jobs SET status='failed',stage='server_restarted' WHERE id=?",
                       (job,))
        status=self.client.get("/integrations/v1/public/jobs/"+job).json()
        self.assertEqual(status["status"],"unknown")
        self.assertEqual(status["error_code"],"SERVER_RESTARTED_DELIVERY_UNKNOWN")
        with api_v1.connection() as db:
            db.execute("UPDATE jobs SET stage='connection_lost' WHERE id=?",(job,))
        status=self.client.get("/integrations/v1/public/jobs/"+job).json()
        self.assertEqual(status["status"],"stalled")
        self.assertEqual(status["error_code"],"WORKER_CONNECTION_LOST")
        self.assertFalse(status["result_ready"])
        self.assertEqual(status["request_id"],self.request_id)

if __name__=="__main__":
    unittest.main()
