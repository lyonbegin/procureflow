"""Drive-only attachment regression tests without external Google credentials."""
import hashlib
import os
import sys
import tempfile
from pathlib import Path

test_dir = tempfile.TemporaryDirectory(prefix="relay-drive-tests-")
os.environ["RELAY_DATA_DIR"] = test_dir.name
os.environ["CONSOLE_TOKEN"] = "admin-integration-token"
os.environ["DEVICE_TOKEN"] = "device-integration-token"
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
from app import app
import drive_v1

def main():
    events=[]
    folder_no=[0]
    def stub_google(uid,method,url,*,json_body=None,params=None,content=None,content_type=None):
        events.append({"uid":uid,"method":method,"url":url,
                       "json":json_body,"params":params,"content":content,
                       "content_type":content_type})
        if url==drive_v1.GOOGLE_API and method=="POST":
            folder_no[0]+=1
            assert json_body["mimeType"]=="application/vnd.google-apps.folder"
            return {"id":"gdrive_folder_"+str(folder_no[0])}
        if url==drive_v1.GOOGLE_UPLOAD and method=="POST":
            assert params["uploadType"]=="multipart"
            assert content_type.startswith("multipart/related; boundary=")
            assert b'"parents": ["gdrive_folder_2"]' in content
            assert b"image.png" in content
            assert content.count(b"PNG!")==1
            return {"id":"gdrive_fake_png_id",
                    "webViewLink":"https://drive.google.com/file/d/gdrive_fake_png_id/view"}
        if "/permissions" in url and method=="POST":
            assert json_body=={"type":"anyone","role":"reader"}
            return {"id":"perm_1"}
        raise AssertionError(f"Unexpected Google call: {method} {url}")
    saved_google=drive_v1.google
    saved_ready=drive_v1.ready
    drive_v1.google=stub_google
    drive_v1.ready=lambda: {"client_id":"fake","client_secret":"fake",
                            "encryption_key":"fake","redirect_uri":"https://relay.example.test/oauth"}
    try:
        with TestClient(app) as client:
            admin={"X-Console-Token":"admin-integration-token"}
            a=client.post("/api/v1/users",headers=admin,json={"user_id":"alice","name":"Alice"}).json()
            b=client.post("/api/v1/users",headers=admin,json={"user_id":"bob","name":"Bob"}).json()
            auth_a={"X-API-Key":a["api_key"]}
            auth_b={"X-API-Key":b["api_key"]}
            with drive_v1.api.connection() as c:
                c.execute("INSERT INTO drive_connections(user_id,refresh_token_encrypted,connected_at) VALUES(?,?,?)",
                          ("alice","fake-encrypted-refresh",123))
            room_resp=client.post("/api/v1/rooms",headers=auth_a,json={"title":"My image analysis"})
            assert room_resp.status_code==200,room_resp.text
            room=room_resp.json()
            rid=room["id"]
            assert room["drive_folder_id"]=="gdrive_folder_2",room
            assert folder_no[0]==2,folder_no
            assert client.get("/api/v1/drive/status",headers=auth_b).json()["connected"] is False
            assert client.post("/api/v1/drive/rooms/"+rid+"/folder",headers=auth_b).status_code==404

            p=client.post("/api/v1/drive/files",headers=auth_a,
                          data={"user_id":"alice","room_id":rid,"share_link":"false"},
                          files={"file":("image.png",b"PNG!","image/png")})
            assert p.status_code==200,p.text
            f=p.json()
            assert f["drive_url"]=="https://drive.google.com/file/d/gdrive_fake_png_id/view"
            assert f["drive_file_id"]=="gdrive_fake_png_id"
            assert f["drive_shared"]==0 and f["kind"]=="drive"
            assert f["sha256"]==hashlib.sha256(b"PNG!").hexdigest()
            assert f.get("relative_path") is None
            assert client.post("/api/v1/rooms/"+rid+"/messages",headers=auth_a,
                       json={"text":"Please inspect the picture","attachment_ids":[f["id"]]}).status_code==409

            share=client.post("/api/v1/drive/files/"+f["id"]+"/share",headers=auth_a)
            assert share.status_code==200,share.text
            assert share.json()["drive_shared"]==1
            assert client.post("/api/v1/drive/files/"+f["id"]+"/share",headers=auth_b).status_code==404
            download=client.get("/api/v1/files/"+f["id"]+"/download",headers=auth_a,
                                follow_redirects=False)
            assert download.status_code==302 and download.headers["location"]==f["drive_url"]
            bad=client.post("/api/v1/rooms/"+rid+"/messages",headers=auth_b,
                   json={"text":"steal room","attachment_ids":[f["id"]]})
            assert bad.status_code==404,bad.text

            job=client.post("/api/v1/rooms/"+rid+"/messages",headers=auth_a,
                  json={"text":"What is shown?","attachment_ids":[f["id"]]})
            assert job.status_code==200,job.text
            jid=job.json()["id"]
            with client.websocket_connect("/ws") as device:
                device.send_json({"role":"device","token":"device-integration-token","deviceId":"android-main"})
                assert device.receive_json()["type"]=="auth.ok"
                cmd=device.receive_json()
                assert cmd["type"]=="job"
                payload=cmd["job"]
                assert payload["id"]==jid
                assert payload["action"]=="chat.send"
                assert payload["attachment_ids"]==[]       # NO Android file-picker path
                assert payload["attachment_details"]==[]
                assert "What is shown?" in payload["text"]
                assert "https://drive.google.com/file/d/gdrive_fake_png_id/view" in payload["text"]
                assert payload["drive_links"]==[{
                    "id":f["id"],"name":"image.png","mime":"image/png",
                    "url":"https://drive.google.com/file/d/gdrive_fake_png_id/view"}]
                assert "access" not in str(payload).lower() or "access token" not in str(payload).lower()
                device.send_json({"type":"job.result","job_id":jid,
                    "verified":True,"stage":"assistant_reply_stable",
                    "room_id":rid,"room_state":"active",
                    "result_text":"I cannot access that image from the link"})
                import time
                for _ in range(40):
                    state=client.get("/api/v1/jobs/"+jid,headers=auth_a).json()
                    if state["status"]=="completed":break
                    time.sleep(.025)
                assert state["status"]=="completed",state
            assert any(e["url"]==drive_v1.GOOGLE_UPLOAD for e in events)
            print("PASS: user Drive folders, uploads, private/share switch, link-only Android job, room isolation")
    finally:
        drive_v1.google=saved_google
        drive_v1.ready=saved_ready
        test_dir.cleanup()

if __name__=="__main__":
    main()
