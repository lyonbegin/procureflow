import hashlib
import os
import tempfile
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

data_dir = tempfile.TemporaryDirectory(prefix="relay-v1-tests-")
os.environ["RELAY_DATA_DIR"] = data_dir.name
os.environ["CONSOLE_TOKEN"] = "admin-testing-secret"
os.environ["DEVICE_TOKEN"] = "android-testing-secret"

from fastapi.testclient import TestClient
from app import app

def main():
    with TestClient(app) as client:
        admin={"X-Console-Token":"admin-testing-secret"}
        user_a=client.post("/api/v1/users",headers=admin,json={"user_id":"alice","name":"Alice"})
        assert user_a.status_code==200,user_a.text
        key_a=user_a.json()["api_key"]
        assert len(key_a)>35
        auth_a={"X-API-Key":key_a}
        user_b=client.post("/api/v1/users",headers=admin,json={"user_id":"bob","name":"Bob"})
        assert user_b.status_code==200,user_b.text
        auth_b={"X-API-Key":user_b.json()["api_key"]}
        assert client.get("/api/v1/users",headers=auth_a).status_code==403

        room=client.post("/api/v1/rooms",headers=auth_a,json={"title":"Alice private proposal"})
        assert room.status_code==200,room.text
        rid=room.json()["id"]
        assert client.get("/api/v1/rooms",headers=auth_b).json()["rooms"]==[]
        assert client.get("/api/v1/rooms/"+rid,headers=auth_b).status_code==404
        assert client.patch("/api/v1/rooms/"+rid,headers=auth_b,json={"title":"Hack"}).status_code==404

        uploaded=client.post("/api/v1/files",headers=auth_a,data={"user_id":"alice","room_id":rid},
                             files={"file":("details.txt",b"procurement-details-original","text/plain")})
        assert uploaded.status_code==200,uploaded.text
        file_obj=uploaded.json()
        fid=file_obj["id"]
        assert file_obj["sha256"]==hashlib.sha256(b"procurement-details-original").hexdigest()
        assert client.get("/api/v1/files/"+fid+"/download",headers=auth_b).status_code==404
        content=client.get("/api/v1/files/"+fid+"/download",headers=auth_a)
        assert content.status_code==200 and content.content==b"procurement-details-original"
        assert client.post("/api/v1/files",headers=auth_a,data={"user_id":"alice","room_id":rid},
                           files={"file":("unallowed.exe",b"abc")}).status_code==415
        import base64
        tiny_png=base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/ScL/nwAAAABJRU5ErkJggg==")
        image=client.post("/api/v1/files",headers=auth_a,
                          data={"user_id":"alice","room_id":rid},
                          files={"file":("picture.png",tiny_png,"image/png")})
        assert image.status_code==200,image.text
        image_id=image.json()["id"]
        assert image.json()["mime"]=="image/png"
        assert client.get("/api/v1/files/"+image_id+"/download",headers=auth_a).content==tiny_png


        req=client.post("/api/v1/rooms/"+rid+"/messages",headers=auth_a,
                        json={"text":"Please analyze attached document","attachment_ids":[fid]})
        assert req.status_code==200,req.text
        job=req.json()
        jid=job["id"]
        assert job["status"]=="queued"
        assert job["room_id"]==rid
        assert job["attachment_ids"]==[fid]
        assert client.get("/api/v1/jobs/"+jid,headers=auth_b).status_code==404

        with client.websocket_connect("/ws") as device:
            device.send_json({"role":"device","token":"android-testing-secret","deviceId":"android-main"})
            assert device.receive_json()["type"]=="auth.ok"
            dispatched=device.receive_json()
            assert dispatched["type"]=="job",dispatched
            assert dispatched["job"]["id"]==jid
            assert dispatched["job"]["room"]["id"]==rid
            assert dispatched["job"]["attachment_ids"]==[fid]
            meta=dispatched["job"]["attachment_details"]
            assert len(meta)==1 and meta[0]["id"]==fid
            assert meta[0]["name"]=="details.txt" and meta[0]["mime"]=="text/plain"
            assert meta[0]["size"]==len(b"procurement-details-original")
            assert meta[0]["sha256"]==hashlib.sha256(b"procurement-details-original").hexdigest()
            assert client.get("/api/v1/jobs/"+jid,headers=auth_a).json()["status"]=="running"

            fetched=client.get("/api/v1/device/jobs/"+jid+"/files/"+fid,
                               headers={"Authorization":"Bearer android-testing-secret"})
            assert fetched.status_code==200 and fetched.content==b"procurement-details-original"
            assert client.get("/api/v1/device/jobs/"+jid+"/files/"+fid,
                              headers={"Authorization":"Bearer invalid"}).status_code==403

            output=client.post("/api/v1/device/jobs/"+jid+"/outputs",
                               headers={"Authorization":"Bearer android-testing-secret"},
                               files={"file":("answer.md",b"# Android output","text/markdown")})
            assert output.status_code==200,output.text
            output_file=output.json()["id"]

            device.send_json({"type":"job.progress","job_id":jid,"stage":"Testing input file"})
            assert client.get("/api/v1/jobs/"+jid,headers=auth_a).json()["stage"] in ("Testing input file","dispatched")
            device.send_json({"type":"job.result","job_id":jid,"verified":True,
                              "result_text":"Document processed and verified",
                              "room_id":rid,"room_state":"active","stage":"assistant_reply_stable"})
            import time
            for _ in range(40):
                j=client.get("/api/v1/jobs/"+jid,headers=auth_a).json()
                if j["status"]=="completed":break
                time.sleep(.025)
            assert j["status"]=="completed",j
            assert client.get("/api/v1/files/"+output_file+"/download",headers=auth_a).content==b"# Android output"

            msgs=client.get("/api/v1/rooms/"+rid+"/messages",headers=auth_a).json()["messages"]
            assert [m["role"] for m in msgs]==["user","assistant"],msgs
            assert msgs[-1]["text"]=="Document processed and verified"
            assert client.get("/api/v1/rooms/"+rid,headers=auth_a).json()["android_state"]=="active"

            # A controller reinstalled after the first job must be able to
            # identify the correct room from the server's completed history.
            follow=client.post("/api/v1/rooms/"+rid+"/messages",headers=auth_a,
                               json={"text":"Follow-up after Android app restart"})
            assert follow.status_code==200,follow.text
            follow_jid=follow.json()["id"]
            follow_packet=device.receive_json()
            assert follow_packet["type"]=="job" and follow_packet["job"]["id"]==follow_jid
            anchors=follow_packet["job"].get("room_anchors", [])
            assert any(a["role"]=="assistant" and
                       a["text"]=="Document processed and verified"
                       for a in anchors),anchors
            assert all(a["from_job_id"]!=follow_jid for a in anchors)
            device.send_json({"type":"job.error","job_id":follow_jid,"verified":False,
                              "reason":"Test of non-destructive failed follow-up",
                              "stage":"test_failed"})
            for _ in range(40):
                state=client.get("/api/v1/jobs/"+follow_jid,headers=auth_a).json()
                if state["status"]=="failed":break
                time.sleep(.025)
            assert state["status"]=="failed",state
            assert client.get("/api/v1/rooms/"+rid,headers=auth_a).json()["android_state"]=="active"

            dele=client.delete("/api/v1/rooms/"+rid,headers=auth_a)
            assert dele.status_code==200 and dele.json()["status"]=="delete_pending"
            delete_job=device.receive_json()
            assert delete_job["type"]=="job" and delete_job["job"]["action"]=="room.delete"
            device.send_json({"type":"job.error","job_id":delete_job["job"]["id"],"verified":False,
                              "reason":"Room identity not verifiable","stage":"delete_not_verified"})
            for _ in range(40):
                dr=client.get("/api/v1/rooms/"+rid,headers=auth_a).json()
                if dr["status"]=="delete_failed":break
                time.sleep(.025)
            assert dr["status"]=="delete_failed",dr
            assert client.get("/api/v1/rooms/"+rid+"/messages",headers=auth_a).status_code==200

    print("PASS: API users/authorization/rooms/messages/jobs/input-output files/Android websocket",flush=True)

if __name__=="__main__":
    main()
