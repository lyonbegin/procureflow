"""Real FastAPI WebSocket coexistence test: browser and Android never preempt one another.

No Google account, no Railway, no passwords. The original API routes are used.
"""
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
_tmp=tempfile.TemporaryDirectory(prefix="relay-coexist-")
os.environ["RELAY_DATA_DIR"]=_tmp.name
os.environ["CONSOLE_TOKEN"]="admin-integration-test"
os.environ["DEVICE_TOKEN"]="android-integration-test"
os.environ["WEB_SESSION_SIGNING_KEY"]="nonproduction-test-session-key-is-long-enough"
from fastapi.testclient import TestClient
from app import app


class WorkerCoexistence(unittest.TestCase):
    @patch("app.verify_worker_identity",return_value=True)
    def test_text_to_browser_files_to_android_both_stay_online(self,_verify):
        with TestClient(app) as client:
            a=client.post("/api/v1/users",
                headers={"X-Console-Token":"admin-integration-test"},
                json={"name":"Coexist user","user_id":"coexist_"+str(int(time.time()*1000))})
            self.assertEqual(a.status_code,200,a.text)
            headers={"X-API-Key":a.json()["api_key"]}
            r=client.post("/api/v1/rooms",headers=headers,json={"title":"Preserved original room"})
            self.assertEqual(r.status_code,200,r.text)
            rid=r.json()["id"]
            with client.websocket_connect("/ws") as android:
                android.send_json({"role":"device","deviceId":"android-main",
                                   "token":"android-integration-test"})
                self.assertEqual(android.receive_json()["type"],"auth.ok")
                with client.websocket_connect("/ws") as browser:
                    browser.send_json({"role":"web2api","deviceId":"web2api-main",
                                       "oidc_token":"signed-simulation"})
                    self.assertEqual(browser.receive_json()["type"],"auth.ok")
                    health=client.get("/health").json()
                    self.assertTrue(health["deviceOnline"])
                    self.assertTrue(health["web2apiOnline"])

                    sent=client.post("/api/v1/rooms/"+rid+"/messages",
                        headers=headers,json={"text":"Browser first turn"})
                    self.assertEqual(sent.status_code,200,sent.text)
                    job=browser.receive_json()
                    self.assertEqual(job["type"],"job")
                    self.assertEqual(job["job"]["id"],sent.json()["id"])
                    self.assertEqual(job["job"]["attachment_ids"],[])
                    self.assertEqual(job["job"]["room_id"],rid)
                    browser.send_json({"type":"job.result","job_id":sent.json()["id"],
                        "room_id":rid,"verified":True,"stage":"assistant_reply_stable",
                        "result_text":"Browser answer verified",
                        "chatgpt_url":"https://chatgpt.com/c/b12a45cd-1234-5678-9012-abcd12345678"})
                    for _ in range(50):
                        resp=client.get("/api/v1/jobs/"+sent.json()["id"],headers=headers).json()
                        if resp["status"]=="completed":break
                        time.sleep(.02)
                    self.assertEqual(resp["status"],"completed",resp)

                    # OIDC browser connection did not evict Android.
                    android.send_json({"type":"ping"})
                    self.assertEqual(android.receive_json()["type"],"pong")

                    uploaded=client.post("/api/v1/files",
                        headers=headers,data={"user_id":a.json()["user_id"],"room_id":rid},
                        files={"file":("source.txt",b"original bytes","text/plain")})
                    self.assertEqual(uploaded.status_code,200,uploaded.text)
                    attachment=uploaded.json()["id"]
                    sent_file=client.post("/api/v1/rooms/"+rid+"/messages",
                        headers=headers,json={"text":"Read this file",
                            "attachment_ids":[attachment]})
                    self.assertEqual(sent_file.status_code,200,sent_file.text)
                    android_job=android.receive_json()
                    self.assertEqual(android_job["type"],"job")
                    self.assertEqual(android_job["job"]["id"],sent_file.json()["id"])
                    self.assertEqual(android_job["job"]["attachment_ids"],[attachment])
                    self.assertEqual(android_job["job"]["room_id"],rid)
                    android.send_json({"type":"job.error","job_id":sent_file.json()["id"],
                                       "room_id":rid,"stage":"test_only",
                                       "reason":"No actual Android send performed"})
                    for _ in range(50):
                        failed=client.get("/api/v1/jobs/"+sent_file.json()["id"],
                            headers=headers).json()
                        if failed["status"]=="failed":break
                        time.sleep(.02)
                    self.assertEqual(failed["status"],"failed",failed)
                    browser.send_json({"type":"ping"})
                    self.assertEqual(browser.receive_json()["type"],"pong")

                # Closing browser worker leaves Android connection intact.
                for _ in range(50):
                    h=client.get("/health").json()
                    if not h["web2apiOnline"]:break
                    time.sleep(.02)
                self.assertTrue(h["deviceOnline"])
                self.assertFalse(h["web2apiOnline"])
                android.send_json({"type":"ping"})
                self.assertEqual(android.receive_json()["type"],"pong")


if __name__=="__main__":
    unittest.main()
