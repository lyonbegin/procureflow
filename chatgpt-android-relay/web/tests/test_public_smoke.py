"""Token-free public smoke console tests. No Railway or ChatGPT traffic."""
import os,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch,AsyncMock

tmp=tempfile.TemporaryDirectory(prefix="web2api-public-smoke-")
os.environ["RELAY_DATA_DIR"]=tmp.name
os.environ["PUBLIC_SMOKE_ONLY"]="1"
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
import app,api_v1

class PublicNoLoginSmoke(unittest.TestCase):
    def setUp(self):
        self.client=TestClient(app.app)
        self.client.__enter__()
        app.web2api_device=None
        app.active_job_id=None
        with api_v1.connection() as db:
            db.execute("DELETE FROM jobs WHERE user_id=?",(app.DEMO_UID,))
            db.execute("DELETE FROM messages WHERE user_id=?",(app.DEMO_UID,))
            db.execute("DELETE FROM rooms WHERE user_id=?",(app.DEMO_UID,))
            db.execute("DELETE FROM users WHERE id=?",(app.DEMO_UID,))

    def tearDown(self):
        app.web2api_device=None
        self.client.__exit__(None,None,None)

    def test_old_console_absent_and_uncached(self):
        r=self.client.get("/")
        self.assertEqual(r.status_code,200)
        self.assertIn("Web2API 연결 시험",r.text)
        self.assertNotIn('id="admin-token"',r.text)
        self.assertNotIn('id="user-api-key"',r.text)
        self.assertNotIn('type="password"',r.text)
        self.assertNotIn("관리 콘솔 토큰",r.text)
        self.assertNotIn("Android · API Test Console",r.text)
        self.assertIn("no-store",r.headers.get("cache-control",""))

    def test_legacy_private_api_and_docs_blocked(self):
        for path in ("/api/v1/rooms","/api/v1/users","/api/v1/jobs","/docs","/openapi.json"):
            self.assertEqual(self.client.get(path).status_code,404,path)

    def test_safe_status_does_not_expose_private_records(self):
        h=self.client.get("/health")
        self.assertEqual(h.status_code,200)
        r=self.client.get("/demo/status")
        self.assertEqual(r.status_code,200)
        self.assertEqual(r.json()["testState"],"not_started")
        self.assertFalse(r.json()["workerConnected"])
        self.assertNotIn("conversation",str(r.json()).lower())
        self.assertNotIn("result_text",str(r.json()).lower())

    def test_offline_worker_accepts_exactly_one_queued_test_without_private_access(self):
        r=self.client.post("/demo/start")
        self.assertEqual(r.status_code,200,r.text)
        self.assertTrue(r.json()["started"])
        self.assertFalse(r.json()["workerConnected"])
        with api_v1.connection() as db:
            jobs=db.execute(
                "SELECT * FROM jobs WHERE user_id=?", (app.DEMO_UID,)
            ).fetchall()
        self.assertEqual(len(jobs),1)
        self.assertEqual(jobs[0]["status"],"queued")
        self.assertEqual(jobs[0]["text"],app.DEMO_QUESTION)
        self.assertEqual(jobs[0]["room_id"],app.DEMO_ROOM)
        status=self.client.get("/demo/status").json()
        self.assertEqual(status["testState"],"queued")
        self.assertFalse(status["workerConnected"])
        self.assertEqual(self.client.post("/demo/start").status_code,429)

    def test_fixed_prompt_and_rate_limit(self):
        app.web2api_device=object()
        with patch.object(app,"dispatch_next",new_callable=AsyncMock) as fn:
            r=self.client.post("/demo/start")
            self.assertEqual(r.status_code,200,r.text)
            fn.assert_awaited_once()
        with api_v1.connection() as db:
            jobs=db.execute(
                "SELECT * FROM jobs WHERE user_id=?",(app.DEMO_UID,)
            ).fetchall()
        self.assertEqual(len(jobs),1)
        self.assertEqual(jobs[0]["text"],app.DEMO_QUESTION)
        self.assertEqual(jobs[0]["room_id"],app.DEMO_ROOM)
        self.assertEqual(self.client.post("/demo/start").status_code,429)

    def test_cross_site_request_rejected(self):
        app.web2api_device=object()
        r=self.client.post("/demo/start",headers={"Origin":"https://thirdparty.example"})
        self.assertEqual(r.status_code,403)

if __name__=="__main__":unittest.main()
