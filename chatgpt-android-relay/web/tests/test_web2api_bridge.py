"""Live FastAPI/WebSocket room-isolation tests for signed Web2API worker.

No Railway writes, no GitHub credentials, no ChatGPT requests.
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
_temp=tempfile.TemporaryDirectory(prefix="web2api-bridge-")
os.environ["RELAY_DATA_DIR"]=_temp.name
os.environ["CONSOLE_TOKEN"]="test-console"
os.environ["DEVICE_TOKEN"]="test-android"
os.environ["WEB_SESSION_SIGNING_KEY"]="test-web-signing-key-longer-than-32-chars"
from fastapi.testclient import TestClient
from app import app
import api_v1

CID="c15d4040-1234-4abc-8912-123456789abc"
OTHER="aa991122-1234-4abc-8912-123456789abc"
TARGET="https://chatgpt.com/c/"+CID


class RelayBridgeTests(unittest.TestCase):
    def setUp(self):
        self.client=TestClient(app)
        self.client.__enter__()
        user=self.client.post("/api/v1/users",headers={"X-Console-Token":"test-console"},
            json={"name":"User-"+api_v1.new_id()[:10]})
        self.assertEqual(user.status_code,200,user.text)
        self.key={"X-API-Key":user.json()["api_key"]}
        self.uid=user.json()["user_id"]
        room=self.client.post("/api/v1/rooms",headers=self.key,json={"title":"Web2API test room"})
        self.assertEqual(room.status_code,200,room.text)
        self.rid=room.json()["id"]

    def tearDown(self):
        self.client.__exit__(None,None,None)

    def enqueue(self,text="Test message"):
        response=self.client.post("/api/v1/rooms/"+self.rid+"/messages",
                                  headers=self.key,json={"text":text})
        self.assertEqual(response.status_code,200,response.text)
        return response.json()["id"]

    @patch("app.verify_worker_identity",return_value=True)
    def test_worker_binds_first_reply_then_rejects_wrong_chat(self,_):
        first=self.enqueue("First verified turn")
        with self.client.websocket_connect("/ws") as ws:
            ws.send_json({"role":"device","deviceId":"android-main",
                          "oidc_token":"signed-test-token-not-real"})
            self.assertEqual(ws.receive_json()["type"],"auth.ok")
            packet=ws.receive_json()
            self.assertEqual(packet["type"],"job")
            self.assertEqual(packet["job"]["id"],first)
            self.assertIsNone(packet["job"]["target_conversation_id"])
            ws.send_json({"type":"job.result","job_id":first,
                          "room_id":self.rid,"verified":True,
                          "stage":"assistant_reply_stable",
                          "result_text":"Reply verified",
                          "chatgpt_url":TARGET,"room_state":"active"})
            result=self.client.get("/api/v1/jobs/"+first,headers=self.key).json()
            for _ in range(30):
                if result["status"]=="completed":break
                import time;time.sleep(.02)
                result=self.client.get("/api/v1/jobs/"+first,headers=self.key).json()
            self.assertEqual(result["status"],"completed",result)
            room=self.client.get("/api/v1/rooms/"+self.rid,headers=self.key).json()
            self.assertEqual(room["chatgpt_url"],TARGET)
            texts=self.client.get("/api/v1/rooms/"+self.rid+"/messages",headers=self.key).json()["messages"]
            self.assertEqual([x["role"] for x in texts],["user","assistant"])
            self.assertEqual(texts[1]["text"],"Reply verified")

            second=self.enqueue("Second, same room")
            packet=ws.receive_json()
            self.assertEqual(packet["type"],"job")
            self.assertEqual(packet["job"]["id"],second)
            self.assertEqual(packet["job"]["target_conversation_id"],CID)
            ws.send_json({"type":"job.result","job_id":second,
                          "room_id":self.rid,"verified":True,
                          "stage":"assistant_reply_stable","result_text":"Wrong room",
                          "chatgpt_url":"https://chatgpt.com/c/"+OTHER})
            failed=self.client.get("/api/v1/jobs/"+second,headers=self.key).json()
            for _ in range(30):
                if failed["status"]=="failed":break
                import time;time.sleep(.02)
                failed=self.client.get("/api/v1/jobs/"+second,headers=self.key).json()
            self.assertEqual(failed["status"],"failed",failed)
            self.assertEqual(failed["stage"],"ROOM_CONVERSATION_ID_MISMATCH")
            texts=self.client.get("/api/v1/rooms/"+self.rid+"/messages",headers=self.key).json()["messages"]
            self.assertEqual(len([x for x in texts if x["role"]=="assistant"]),1)
            self.assertEqual(self.client.get("/api/v1/rooms/"+self.rid,
                headers=self.key).json()["chatgpt_url"],TARGET)

    def test_invalid_url_and_cross_room_rejected(self):
        job=self.enqueue()
        with api_v1.connection() as db:
            db.execute("UPDATE jobs SET status='running' WHERE id=?",(job,))
        self.assertFalse(api_v1.bind_verified_browser_conversation(job,self.rid,
            "https://not-chatgpt.com/c/"+CID))
        self.assertFalse(api_v1.bind_verified_browser_conversation(job,"room_wrong",TARGET))
        self.assertFalse(api_v1.bind_verified_browser_conversation(job,self.rid,
            "https://chatgpt.com/share/"+CID))
        self.assertTrue(api_v1.bind_verified_browser_conversation(job,self.rid,TARGET))
        self.assertFalse(api_v1.bind_verified_browser_conversation(job,self.rid,
            "https://chatgpt.com/c/"+OTHER))

    @patch("app.verify_worker_identity",return_value=False)
    def test_unsigned_worker_denied(self,_):
        with self.client.websocket_connect("/ws") as ws:
            ws.send_json({"role":"device","deviceId":"android-main",
                          "oidc_token":"unsigned"})
            self.assertEqual(ws.receive_json()["type"],"auth.error")


if __name__ == "__main__":
    unittest.main()
