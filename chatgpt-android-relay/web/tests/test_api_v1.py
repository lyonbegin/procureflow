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
os.environ["WEB_SESSION_SIGNING_KEY"] = "testing-session-key-longer-than-32-chars-123"

from fastapi.testclient import TestClient
from app import app
import api_v1

def main():
    with TestClient(app) as client:
        # Legacy console send/new commands omit verified API room identity.
        # They MUST be blocked, even if an authenticated device is connected.
        with client.websocket_connect("/ws") as console:
            console.send_json({"role":"console","token":"admin-testing-secret"})
            assert console.receive_json()["type"]=="auth.ok"
            for action in ("chat.send","chat.new"):
                console.send_json({
                    "type":"command", "id":"legacy-"+action,
                    "action":action,"payload":{"text":"Never send to current room"}})
                denied=console.receive_json()
                assert denied["type"]=="command.error",denied
                assert "ROOM_SCOPED_API_REQUIRED" in denied["reason"],denied

        admin={"X-Console-Token":"admin-testing-secret"}
        user_a=client.post("/api/v1/users",headers=admin,json={"user_id":"alice","name":"Alice"})
        assert user_a.status_code==200,user_a.text
        key_a=user_a.json()["api_key"]
        assert len(key_a)>35
        auth_a={"X-API-Key":key_a}
        # Browser remembers a verified login via HttpOnly secure cookie.
        # A new user doesn't receive a public embedded admin credential.
        with TestClient(app,base_url="https://testserver") as browser:
            assert browser.get("/api/v1/rooms?user_id=alice").status_code==401
            login=browser.post("/api/v1/auth/session",headers=admin)
            assert login.status_code==200,login.text
            assert login.json()["authenticated"] is True
            cookie=login.headers.get("set-cookie","")
            assert "httponly" in cookie.lower()
            assert "secure" in cookie.lower()
            assert "samesite=strict" in cookie.lower()
            assert "relay_web_session" in cookie
            assert "admin-testing-secret" not in cookie
            assert browser.get("/api/v1/auth/check").json()["role"]=="admin"
            assert browser.get("/api/v1/rooms?user_id=alice").status_code==200
            assert browser.post("/api/v1/auth/logout").status_code==200
            assert browser.get("/api/v1/rooms?user_id=alice").status_code==401
            user_login=browser.post("/api/v1/auth/session",headers=auth_a)
            assert user_login.status_code==200,user_login.text
            assert browser.get("/api/v1/rooms?user_id=alice").status_code==200
            assert browser.get("/api/v1/rooms?user_id=bob").status_code==403
            assert browser.get("/api/v1/users").status_code==403
        # Cross-browser requests without cookie still require a key.

        assert client.get("/api/v1/auth/check").status_code==401
        assert client.get("/api/v1/auth/check",headers=admin).json()=={
            "authenticated":True,"role":"admin","user_id":None}
        assert client.get("/api/v1/auth/check",headers=auth_a).json()=={
            "authenticated":True,"role":"user","user_id":"alice"}
        assert client.get("/api/v1/auth/check",headers={"X-API-Key":"invalid"}).status_code==403
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


        # Previously uploaded Railway files MUST be attachable without Drive.
        req=client.post("/api/v1/rooms/"+rid+"/messages",headers=auth_a,
                        json={"text":"Please analyze attached document","attachment_ids":[fid]})
        assert req.status_code==200,req.text
        job=req.json()
        jid=job["id"]
        assert job["status"]=="queued"
        assert job["room_id"]==rid
        assert job["attachment_ids"]==[fid]
        assert client.get("/api/v1/jobs/"+jid,headers=auth_b).status_code==404

        # Simulate one previous server-process job left 'running' in
        # persistent storage when a new process first sees Android connect.
        with api_v1.connection() as db:
            orphan_id=api_v1.store_job(
                db,"alice",rid,"chat.send","Old unconfirmed message")
            db.execute("UPDATE jobs SET status='running' WHERE id=?",(orphan_id,))
        assert client.get("/api/v1/jobs/"+orphan_id,
                          headers=auth_a).json()["status"]=="running"

        with client.websocket_connect("/ws") as device:
            device.send_json({"role":"device","token":"android-testing-secret","deviceId":"android-main"})
            assert device.receive_json()["type"]=="auth.ok"
            # Recovery is fail-closed, never re-queues an unknown delivery.
            for _ in range(40):
                orphan=client.get("/api/v1/jobs/"+orphan_id,
                                   headers=auth_a).json()
                if orphan["status"]=="failed":break
                import time
                time.sleep(.025)
            assert orphan["status"]=="failed",orphan
            assert orphan["stage"]=="server_restarted",orphan
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
            assert dispatched["job"]["drive_links"]==[]
            assert client.get("/api/v1/jobs/"+jid,headers=auth_a).json()["status"]=="running"

            # The Android relay downloads the original exact file bytes over HTTPS.
            fetched=client.get("/api/v1/device/jobs/"+jid+"/files/"+fid,
                               headers={"Authorization":"Bearer android-testing-secret"})
            assert fetched.status_code==200 and fetched.content==b"procurement-details-original"
            # Only job-attached files can be fetched by the device.
            other=client.get("/api/v1/device/jobs/"+jid+"/files/"+image_id,
                             headers={"Authorization":"Bearer android-testing-secret"})
            assert other.status_code==403
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

            # Clicking an existing room issues a navigation-only job:
            # Android must verify an old completed message; no new message
            # is sent, and no assistant reply is created.
            assert client.post("/api/v1/rooms/"+rid+"/open",headers=auth_b).status_code==404
            reopened=client.post("/api/v1/rooms/"+rid+"/open",headers=auth_a)
            assert reopened.status_code==200,reopened.text
            assert reopened.json()["action"]=="room.open"
            open_packet=device.receive_json()
            assert open_packet["type"]=="job"
            assert open_packet["job"]["action"]=="room.open"
            assert open_packet["job"]["room"]["id"]==rid
            assert any(x["text"]=="Document processed and verified"
                       for x in open_packet["job"]["room_anchors"])
            open_jid=reopened.json()["id"]
            device.send_json({"type":"job.result","job_id":open_jid,"verified":True,
                              "result_text":"","room_id":rid,"room_state":"active",
                              "stage":"room_open_verified"})
            for _ in range(40):
                opened=client.get("/api/v1/jobs/"+open_jid,headers=auth_a).json()
                if opened["status"]=="completed":break
                time.sleep(.025)
            assert opened["status"]=="completed",opened
            assert len(client.get("/api/v1/rooms/"+rid+"/messages",
                                  headers=auth_a).json()["messages"])==2

            # A controller reinstalled after the first job must be able to
            # identify the correct room from the server's completed history.
            # Single API request with files: multipart/form-data -> Railway
            # storage -> queued job -> authenticated Android download.
            follow=client.post("/api/v1/rooms/"+rid+"/turns",headers=auth_a,
                               data={"text":"Analyze both pictures after restart","user_id":"alice"},
                               files=[
                                 ("files",("first.png",tiny_png,"image/png")),
                                 ("files",("second.txt",b"second attachment","text/plain"))
                               ])
            assert follow.status_code==200,follow.text
            follow_jid=follow.json()["id"]
            follow_packet=device.receive_json()
            assert follow_packet["type"]=="job" and follow_packet["job"]["id"]==follow_jid
            follow_files=follow.json()["files"]
            assert len(follow_files)==2
            assert follow_packet["job"]["attachment_ids"]==[f["id"] for f in follow_files]
            assert [x["name"] for x in follow_packet["job"]["attachment_details"]]==["first.png","second.txt"]
            for file,expected_bytes in zip(follow_files,[tiny_png,b"second attachment"]):
                fetched=client.get("/api/v1/device/jobs/"+follow_jid+"/files/"+file["id"],
                                   headers={"Authorization":"Bearer android-testing-secret"})
                assert fetched.status_code==200 and fetched.content==expected_bytes
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

            # Cross-user and invalid-file requests cannot enqueue a turn.
            assert client.post("/api/v1/rooms/"+rid+"/turns",headers=auth_b,
                 data={"text":"wrong user"},files=[("files",("a.png",tiny_png,"image/png"))]).status_code==404
            assert client.post("/api/v1/rooms/"+rid+"/turns",headers=auth_a,
                 data={"text":"bad type","user_id":"alice"},
                 files=[("files",("attack.exe",b"bad","application/octet-stream"))]).status_code==415

            # Legacy chat with only tiny messages cannot be verified by a
            # fabricated long anchor. A deliberate one-time bind message
            # creates a searchable durable marker for this exact room.
            short_room=client.post("/api/v1/rooms",headers=auth_a,
                                   json={"title":"Short legacy room"}).json()["id"]
            short_job=client.post("/api/v1/rooms/"+short_room+"/messages",headers=auth_a,
                                  json={"text":"Hi"}).json()["id"]
            packet=device.receive_json()
            assert packet["type"]=="job" and packet["job"]["id"]==short_job
            device.send_json({"type":"job.result","job_id":short_job,"verified":True,
                              "result_text":"Hello","room_id":short_room,
                              "room_state":"active","stage":"assistant_reply_stable"})
            for _ in range(40):
                v=client.get("/api/v1/jobs/"+short_job,headers=auth_a).json()
                if v["status"]=="completed": break
                time.sleep(.025)
            assert v["status"]=="completed"
            old_open=client.post("/api/v1/rooms/"+short_room+"/open",headers=auth_a)
            assert old_open.status_code==200
            old_packet=device.receive_json()
            assert old_packet["job"]["room_anchors"]==[]
            device.send_json({"type":"job.error","job_id":old_open.json()["id"],
                              "verified":False,
                              "reason":"LEGACY_BIND_REQUIRED",
                              "stage":"legacy_bind_required"})
            for _ in range(40):
                v=client.get("/api/v1/jobs/"+old_open.json()["id"],
                             headers=auth_a).json()
                if v["status"]=="failed":break
                time.sleep(.025)
            assert v["status"]=="failed"
            assert client.post("/api/v1/rooms/"+short_room+"/bind",headers=auth_b).status_code==404
            binding=client.post("/api/v1/rooms/"+short_room+"/bind",headers=auth_a)
            assert binding.status_code==200,binding.text
            bound_packet=device.receive_json()
            assert bound_packet["job"]["action"]=="room.bind"
            marker=bound_packet["job"]["text"]
            assert marker=="HITEL Relay room marker "+short_room
            device.send_json({"type":"job.result","job_id":binding.json()["id"],
                              "verified":True,"result_text":"Linked",
                              "room_id":short_room,"room_state":"active",
                              "stage":"assistant_reply_stable"})
            for _ in range(40):
                v=client.get("/api/v1/jobs/"+binding.json()["id"],
                             headers=auth_a).json()
                if v["status"]=="completed":break
                time.sleep(.025)
            assert v["status"]=="completed",v
            recovered=client.post("/api/v1/rooms/"+short_room+"/open",headers=auth_a)
            assert recovered.status_code==200,recovered.text
            recovery_packet=device.receive_json()
            assert any(x["text"]==marker
                       for x in recovery_packet["job"]["room_anchors"])
            assert marker[:34] in recovery_packet["job"]["room_search_terms"]
            device.send_json({"type":"job.result","job_id":recovered.json()["id"],
                              "verified":True,"result_text":"",
                              "room_id":short_room,"room_state":"active",
                              "stage":"room_open_verified"})
            for _ in range(40):
                v=client.get("/api/v1/jobs/"+recovered.json()["id"],
                             headers=auth_a).json()
                if v["status"]=="completed":break
                time.sleep(.025)
            assert v["status"]=="completed",v
            # No silent extra user message is created by navigation-only opens.
            messages=client.get("/api/v1/rooms/"+short_room+"/messages",
                                headers=auth_a).json()["messages"]
            assert sum(m["role"]=="user" for m in messages)==2

            # Actual ChatGPT Android APK 1.2026.300 declares ACTION_VIEW
            # intent filter for /c/, /c2/, /uc/ paths. Map the canonical URL
            # to a Railway room; Android job MUST carry that exact target.
            url="https://chatgpt.com/c/11111111-2222-3333-4444-555555555555"
            bad=client.post("/api/v1/rooms",headers=auth_a,
                json={"title":"Reject shared snapshot",
                      "chatgpt_url":"https://chatgpt.com/share/11111111-2222-3333-4444-555555555555"})
            assert bad.status_code==422,bad.text
            malicious=client.post("/api/v1/rooms",headers=auth_a,
                json={"title":"Reject hostile URL",
                      "chatgpt_url":"https://chatgpt.com.evil.test/c/11111111-2222-3333-4444-555555555555"})
            assert malicious.status_code==422,malicious.text
            linked=client.post("/api/v1/rooms",headers=auth_a,
                json={"title":"Existing real ChatGPT conversation",
                      "chatgpt_url":"https://chat.openai.com/c/11111111-2222-3333-4444-555555555555",
                      "chatgpt_title":"Procurement analysis"})
            assert linked.status_code==200,linked.text
            linked_id=linked.json()["id"]
            assert linked.json()["chatgpt_url"]==url
            assert linked.json()["chatgpt_title"]=="Procurement analysis"
            assert linked.json()["android_state"]=="unverified"
            assert client.post("/api/v1/rooms",headers=auth_a,
                json={"title":"Duplicate target","chatgpt_url":url}).status_code==409
            assert client.patch("/api/v1/rooms/"+linked_id,headers=auth_b,
                json={"chatgpt_title":"Denied"}).status_code==404
            renamed=client.patch("/api/v1/rooms/"+linked_id,headers=auth_a,
                json={"chatgpt_title":"Renamed ChatGPT actual title"})
            assert renamed.status_code==200
            assert renamed.json()["chatgpt_url"]==url
            opened=client.post("/api/v1/rooms/"+linked_id+"/open",headers=auth_a)
            assert opened.status_code==200,opened.text
            linked_packet=device.receive_json()
            assert linked_packet["type"]=="job"
            assert linked_packet["job"]["target_chatgpt_url"]==url
            assert linked_packet["job"]["target_conversation_id"]=="11111111-2222-3333-4444-555555555555"
            assert linked_packet["job"]["target_chatgpt_title"]=="Renamed ChatGPT actual title"
            assert linked_packet["job"]["room"]["chatgpt_url"]==url
            assert linked_packet["job"]["action"]=="room.open"
            device.send_json({"type":"job.result","job_id":opened.json()["id"],
                              "verified":True,"result_text":"",
                              "room_id":linked_id,"room_state":"active",
                              "stage":"deeplink_app_landed"})
            # A deep-link landing is not proof of an existing room.
            for _ in range(40):
                opened_status=client.get("/api/v1/jobs/"+opened.json()["id"],
                                         headers=auth_a).json()
                if opened_status["status"]=="failed":break
                time.sleep(.025)
            assert opened_status["status"]=="failed",opened_status
            assert opened_status["stage"]=="UNVERIFIED_JOB_COMPLETION"
            assert client.get("/api/v1/rooms/"+linked_id,
                              headers=auth_a).json()["android_state"]=="unverified"
            verified_open=client.post("/api/v1/rooms/"+linked_id+"/open",headers=auth_a)
            assert verified_open.status_code==200,verified_open.text
            assert device.receive_json()["job"]["id"]==verified_open.json()["id"]
            device.send_json({"type":"job.result","job_id":verified_open.json()["id"],
                "verified":True,"result_text":"","room_id":linked_id,
                "room_state":"active","stage":"room_open_verified"})
            for _ in range(40):
                opened_status=client.get("/api/v1/jobs/"+verified_open.json()["id"],
                                         headers=auth_a).json()
                if opened_status["status"]=="completed":break
                time.sleep(.025)
            assert opened_status["status"]=="completed",opened_status
            assert client.get("/api/v1/rooms/"+linked_id,headers=auth_a).json()["android_state"]=="active"
            # Adversarial routing test: one valid Android device must NOT
            # complete Alice's job while reporting Bob's unrelated room.
            foreign_room=client.post("/api/v1/rooms",headers=auth_b,
                json={"title":"Bob private room"}).json()["id"]
            bad_job=client.post("/api/v1/rooms/"+linked_id+"/messages",
                headers=auth_a,json={"text":"Check wrong-room completion"}).json()["id"]
            # The API must reject relinking while that message is in flight.
            assert client.patch("/api/v1/rooms/"+linked_id,headers=auth_a,
                json={"chatgpt_url":None}).status_code==409
            bad_packet=device.receive_json()
            assert bad_packet["type"]=="job" and bad_packet["job"]["id"]==bad_job
            device.send_json({"type":"job.result","job_id":bad_job,"verified":True,
                "result_text":"MUST NEVER SAVE AS AN ANSWER","room_id":foreign_room,
                "room_state":"active","stage":"assistant_reply_stable"})
            for _ in range(40):
                wrong_state=client.get("/api/v1/jobs/"+bad_job,headers=auth_a).json()
                if wrong_state["status"]=="failed":break
                time.sleep(.025)
            assert wrong_state["status"]=="failed",wrong_state
            assert wrong_state["stage"]=="ROOM_ID_MISMATCH",wrong_state
            assert client.get("/api/v1/rooms/"+foreign_room,
                              headers=auth_b).json()["android_state"]=="uncreated"
            messages=client.get("/api/v1/rooms/"+linked_id+"/messages",
                                headers=auth_a).json()["messages"]
            assert not any(m["role"]=="assistant" and
                           m["text"]=="MUST NEVER SAVE AS AN ANSWER" for m in messages)

            # An unbound Android success without room_id is rejected as well.
            missing_job=client.post("/api/v1/rooms/"+linked_id+"/messages",
                headers=auth_a,json={"text":"Check missing room identity"}).json()["id"]
            assert device.receive_json()["job"]["id"]==missing_job
            device.send_json({"type":"job.result","job_id":missing_job,
                "verified":True,"result_text":"MISSING ROOM INVALID",
                "stage":"assistant_reply_stable"})
            for _ in range(40):
                missing_state=client.get("/api/v1/jobs/"+missing_job,
                                         headers=auth_a).json()
                if missing_state["status"]=="failed":break
                time.sleep(.025)
            assert missing_state["status"]=="failed",missing_state
            assert missing_state["stage"]=="ROOM_ID_MISMATCH",missing_state

            # Once no job is pending, unlinking invalidates the previous
            # Android verification and does not keep the old ChatGPT title.
            update=client.patch("/api/v1/rooms/"+linked_id,headers=auth_a,
                                json={"chatgpt_url":None})
            assert update.status_code==200 and update.json()["chatgpt_url"] is None
            assert update.json()["android_state"]=="uncreated",update.json()
            assert update.json()["chatgpt_title"] is None,update.json()

            # A -> B -> A is verified at the SERVER routing layer only.
            # Each dispatched job must bind its own URL, owner and room ID,
            # and must never inherit the other room's assistant history.
            urls=[
                "https://chatgpt.com/c/aaaaaaaa-1111-2222-3333-444444444444",
                "https://chatgpt.com/c/bbbbbbbb-1111-2222-3333-444444444444",
            ]
            rooms_ab=[]
            for room_index in range(2):
                created=client.post("/api/v1/rooms",headers=auth_a,
                    json={"title":"Switch test "+str(room_index),
                          "chatgpt_url":urls[room_index]})
                assert created.status_code==200,created.text
                rooms_ab.append(created.json()["id"])
            turns=[
                (rooms_ab[0],"A uniquely isolated first request",
                 "A assistant response alpha unique"),
                (rooms_ab[1],"B uniquely isolated first request",
                 "B assistant response bravo unique"),
                (rooms_ab[0],"A second request after visiting B",
                 "A assistant response after return"),
            ]
            for turn_index,(target_id,prompt,answer) in enumerate(turns):
                created=client.post("/api/v1/rooms/"+target_id+"/messages",
                    headers=auth_a,json={"text":prompt})
                assert created.status_code==200,created.text
                turn_id=created.json()["id"]
                packet=device.receive_json()
                assert packet["type"]=="job",packet
                item=packet["job"]
                assert item["id"]==turn_id and item["room"]["id"]==target_id
                assert item["user_id"]=="alice"
                assert item["target_chatgpt_url"]==urls[0 if target_id==rooms_ab[0] else 1]
                if turn_index==2:
                    anchors=item["room_anchors"]
                    assert any(a["text"]=="A assistant response alpha unique" for a in anchors),anchors
                    assert not any("B assistant response bravo" in a["text"] for a in anchors),anchors
                device.send_json({"type":"job.result","job_id":turn_id,
                    "verified":True,"result_text":answer,"room_id":target_id,
                    "room_state":"active","stage":"assistant_reply_stable"})
                for _ in range(40):
                    current=client.get("/api/v1/jobs/"+turn_id,headers=auth_a).json()
                    if current["status"]=="completed":break
                    time.sleep(.025)
                assert current["status"]=="completed",current
            a_messages=client.get("/api/v1/rooms/"+rooms_ab[0]+"/messages",
                                  headers=auth_a).json()["messages"]
            b_messages=client.get("/api/v1/rooms/"+rooms_ab[1]+"/messages",
                                  headers=auth_a).json()["messages"]
            assert [m["role"] for m in a_messages]==[
                "user","assistant","user","assistant"],a_messages
            assert [m["role"] for m in b_messages]==["user","assistant"],b_messages
            assert not any("bravo" in m["text"] for m in a_messages)
            assert not any("alpha" in m["text"] for m in b_messages)

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

            # Replacing the Android WebSocket must FAIL the in-flight job
            # without retrying it or accepting an obsolete session's ack.
            interrupted=client.post("/api/v1/rooms/"+rooms_ab[1]+"/messages",
                headers=auth_a,json={"text":"Unacknowledged work before reconnect"})
            assert interrupted.status_code==200,interrupted.text
            interrupted_jid=interrupted.json()["id"]
            first_device_job=device.receive_json()
            assert first_device_job["type"]=="job"
            assert first_device_job["job"]["id"]==interrupted_jid
            with client.websocket_connect("/ws") as replacement_device:
                replacement_device.send_json({
                    "role":"device","token":"android-testing-secret",
                    "deviceId":"android-main"})
                assert replacement_device.receive_json()["type"]=="auth.ok"
                for _ in range(40):
                    stopped=client.get("/api/v1/jobs/"+interrupted_jid,
                                       headers=auth_a).json()
                    if stopped["status"]=="failed":break
                    time.sleep(.025)
                assert stopped["status"]=="failed",stopped
                assert stopped["stage"]=="connection_lost",stopped
                assert not any(m["role"]=="assistant" and m["job_id"]==interrupted_jid
                    for m in client.get("/api/v1/rooms/"+rooms_ab[1]+"/messages",
                                        headers=auth_a).json()["messages"])
                # A fresh subsequent job is assigned to the new controller.
                continued=client.post("/api/v1/rooms/"+rooms_ab[1]+"/messages",
                    headers=auth_a,json={"text":"New connection can receive work"})
                assert continued.status_code==200,continued.text
                new_id=continued.json()["id"]
                new_packet=replacement_device.receive_json()
                assert new_packet["type"]=="job" and new_packet["job"]["id"]==new_id
                replacement_device.send_json({
                    "type":"job.result","job_id":new_id,"verified":True,
                    "result_text":"Completed by replacement session",
                    "room_id":rooms_ab[1],"room_state":"active",
                    "stage":"assistant_reply_stable"})
                for _ in range(40):
                    reconnected=client.get("/api/v1/jobs/"+new_id,
                                           headers=auth_a).json()
                    if reconnected["status"]=="completed":break
                    time.sleep(.025)
                assert reconnected["status"]=="completed",reconnected

                # Remove the original test attachment bytes after upload.
                # This poisoned job MUST fail, then permit a later valid
                # queued job to reach the same authenticated device.
                lost=client.post("/api/v1/files",headers=auth_a,
                    data={"user_id":"alice","room_id":rooms_ab[0]},
                    files={"file":("lost-document.txt",b"temp payload","text/plain")})
                assert lost.status_code==200,lost.text
                lost_fid=lost.json()["id"]
                with api_v1.connection() as db:
                    stored=db.execute("SELECT relative_path FROM file_objects WHERE id=?",
                                      (lost_fid,)).fetchone()
                (api_v1.FILES / stored["relative_path"]).unlink()
                poison=client.post("/api/v1/rooms/"+rooms_ab[0]+"/messages",
                    headers=auth_a,json={
                        "text":"Should not send this document after its bytes vanished",
                        "attachment_ids":[lost_fid]})
                assert poison.status_code==200,poison.text
                poison_jid=poison.json()["id"]
                for _ in range(40):
                    blocked=client.get("/api/v1/jobs/"+poison_jid,
                                      headers=auth_a).json()
                    if blocked["status"]=="failed":break
                    time.sleep(.025)
                assert blocked["status"]=="failed",blocked
                assert blocked["stage"]=="input_file_unavailable",blocked
                valid=client.post("/api/v1/rooms/"+rooms_ab[0]+"/messages",
                    headers=auth_a,json={"text":"Valid job after missing file"})
                assert valid.status_code==200,valid.text
                valid_jid=valid.json()["id"]
                verified_packet=replacement_device.receive_json()
                assert verified_packet["type"]=="job",verified_packet
                assert verified_packet["job"]["id"]==valid_jid
                replacement_device.send_json({
                    "type":"job.result","job_id":valid_jid,"verified":True,
                    "result_text":"Valid job executed after poison recovery",
                    "room_id":rooms_ab[0],"room_state":"active",
                    "stage":"assistant_reply_stable"})
                for _ in range(40):
                    final_ok=client.get("/api/v1/jobs/"+valid_jid,
                                        headers=auth_a).json()
                    if final_ok["status"]=="completed":break
                    time.sleep(.025)
                assert final_ok["status"]=="completed",final_ok

    print("PASS: API users/authorization/rooms/messages/jobs/input-output files/Android websocket",flush=True)

if __name__=="__main__":
    main()
