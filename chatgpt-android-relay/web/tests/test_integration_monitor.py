"""Read-only, cross-service HITEL operations dashboard contract.

All jobs are synthetic; no external ChatGPT/GitHub network calls.
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

_data=tempfile.TemporaryDirectory(prefix="hitel-monitor-")
os.environ["RELAY_DATA_DIR"]=_data.name
os.environ["WEB_SESSION_SIGNING_KEY"]="test-only-hitel-monitor-secret"
os.environ["PUBLIC_SMOKE_ONLY"]="1"
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
import api_v1
import app
import integration_monitor
import integration_public

class MonitorTests(unittest.TestCase):
    def setUp(self):
        self.gh=patch.object(integration_monitor,"github_snapshot",
                            return_value={"checked_at":api_v1.clock(),
                                          "runs":[],"error":None,
                                          "refresh_interval_seconds":75})
        self.gh.start()
        self.client=TestClient(app.app,base_url="https://testserver")
        self.client.__enter__()
        app.web2api_device=None
        app.active_job_id=None

    def tearDown(self):
        self.client.__exit__(None,None,None)
        self.gh.stop()

    def test_same_name_scoped_to_multiple_programs_and_legacy_unchanged(self):
        a=self.client.post("/integrations/v1/public/rooms",
                           json={"name":"공통 분석","service_id":"learning-app"})
        b=self.client.post("/integrations/v1/public/rooms",
                           json={"name":"공통 분석","service_id":"recruit-app"})
        self.assertEqual(a.status_code,201,a.text)
        self.assertEqual(b.status_code,201,b.text)
        aid=a.json()["room_id"];bid=b.json()["room_id"]
        self.assertNotEqual(aid,bid)
        repeat=self.client.post("/integrations/v1/public/rooms",
                    json={"name":"공통 분석","service_id":"learning-app"})
        self.assertEqual(repeat.status_code,200)
        self.assertEqual(repeat.json()["room_id"],aid)
        legacy=self.client.post("/integrations/v1/public/rooms",
                           json={"name":"공통 분석"})
        self.assertEqual(legacy.status_code,201,legacy.text)
        self.assertNotIn(legacy.json()["room_id"],(aid,bid))
        invalid=self.client.post("/integrations/v1/public/rooms",
                    json={"name":"Room","service_id":"../unsafe"})
        self.assertEqual(invalid.status_code,422)
        with api_v1.connection() as db:
            user=integration_public.USER_ID
            j=api_v1.store_job(db,user,aid,"chat.send","synthetic secret",[])
            db.execute("""UPDATE jobs SET status='completed',
                           stage='assistant_reply_stable',
                           result_text='private synthetic answer' WHERE id=?""",(j,))
            api_v1.store_job(db,user,bid,"chat.send","another secret",[])
        r=self.client.get("/integrations/v1/public/monitor")
        self.assertEqual(r.status_code,200,r.text)
        d=r.json()
        self.assertEqual(d["monitor_version"],"2.0")
        self.assertEqual(d["jobs"]["public_counts"]["total"],2)
        by_service={i["service_id"]:i for i in d["programs"]}
        self.assertEqual(by_service["learning-app"]["completed"],1)
        self.assertEqual(by_service["recruit-app"]["queued"],1)
        self.assertEqual(by_service["미지정"]["room_count"],1)
        self.assertNotIn("synthetic secret",r.text)
        self.assertNotIn("private synthetic answer",r.text)
        self.assertNotIn("chatgpt_url",r.text)

    def test_private_authenticated_jobs_only_aggregate(self):
        uid="usr_private_monitor_test"
        now=api_v1.clock()
        with api_v1.connection() as db:
            db.execute("""INSERT INTO users(id,name,api_key_hash,created_at)
                          VALUES(?,?,?,?)""",
                       (uid,"PrivateOwner","private-test-synthetic",now))
            rid="room_"+api_v1.new_id()
            db.execute("""INSERT INTO rooms(id,user_id,title,
                         android_state,created_at,updated_at)
                         VALUES(?,?,?,?,?,?)""",
                       (rid,uid,"VERY-PRIVATE-ROOM-NAME","uncreated",now,now))
            job=api_v1.store_job(db,uid,rid,"chat.send",
                                  "secret-text",[],account_id="oai_synthetic")
        d=self.client.get("/integrations/v1/public/monitor")
        self.assertEqual(d.status_code,200,d.text)
        self.assertGreaterEqual(d.json()["jobs"]["total_by_channel"]
                                ["account_bound"]["total"],1)
        self.assertNotIn("VERY-PRIVATE-ROOM-NAME",d.text)
        self.assertNotIn("oai_synthetic",d.text)
        self.assertNotIn("secret-text",d.text)
        self.assertNotIn(job,d.text)

    def test_dashboard_ui_and_cors_origin(self):
        r=self.client.get("/integrations/monitor")
        self.assertEqual(r.status_code,200)
        self.assertIn("통합 모니터링",r.text)
        cors=self.client.get("/integrations/v1/public/monitor",
                             headers={"Origin":"https://lyonbegin.github.io"})
        self.assertEqual(cors.status_code,200)
        self.assertEqual(cors.headers.get("access-control-allow-origin"),
                         "https://lyonbegin.github.io")
        other=self.client.get("/integrations/v1/public/monitor",
                              headers={"Origin":"https://unrelated.example"})
        self.assertNotIn("access-control-allow-origin",other.headers)

if __name__=="__main__":
    unittest.main()
