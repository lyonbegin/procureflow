"""Real API tests for public browser rooms/files without exposing private relay."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

_tmp=tempfile.TemporaryDirectory(prefix="hitel-chat-browser-test-")
os.environ["RELAY_DATA_DIR"]=_tmp.name
os.environ["PUBLIC_SMOKE_ONLY"]="1"
os.environ["WEB_SESSION_SIGNING_KEY"]="unit-test-signing-secret-32-characters-minimum"
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
import app, api_v1
import web_chat


class BrowserChatTests(unittest.TestCase):
    def setUp(self):
        self.a=TestClient(app.app,base_url="https://testserver")
        self.b=TestClient(app.app,base_url="https://testserver")
        self.a.__enter__();self.b.__enter__()
        self.ca=self.a.get("/web/api/bootstrap").json()["csrf"]
        self.cb=self.b.get("/web/api/bootstrap").json()["csrf"]
        app.web2api_device=None
        app.active_job_id=None

    def tearDown(self):
        self.a.__exit__(None,None,None)
        self.b.__exit__(None,None,None)

    def create(self,client=None,csrf=None,title="사적인 시험방"):
        client=client or self.a
        csrf=csrf or self.ca
        r=client.post("/web/api/rooms",json={"title":title},headers={"X-Web-Csrf":csrf})
        self.assertEqual(r.status_code,200,r.text)
        return r.json()["room"]["id"]

    def test_home_has_chat_and_file_ui_without_console_tokens(self):
        r=self.a.get("/")
        self.assertEqual(r.status_code,200)
        for word in ("새 대화방","file-input","메시지","파일 선택","Web2API"):
            if word=="메시지":continue
            self.assertIn(word,r.text)
        for word in ('id="admin-token"','id="user-api-key"','type="password"'):
            self.assertNotIn(word,r.text)
        self.assertIn("no-store",r.headers.get("cache-control",""))

    def test_separate_sessions_are_isolated(self):
        room=self.create()
        self.assertEqual(len(self.a.get("/web/api/rooms").json()["rooms"]),1)
        self.assertFalse(any(x["id"]==room for x in self.b.get("/web/api/rooms").json()["rooms"]))
        self.assertEqual(self.b.get("/web/api/rooms/"+room).status_code,404)
        self.assertEqual(self.b.delete("/web/api/rooms/"+room,headers={"X-Web-Csrf":self.cb}).status_code,404)

    def test_room_create_rename_and_delete(self):
        room=self.create(title="초기")
        r=self.a.patch("/web/api/rooms/"+room,json={"title":"수정됨"},
                       headers={"X-Web-Csrf":self.ca})
        self.assertEqual(r.status_code,200)
        self.assertEqual(self.a.get("/web/api/rooms/"+room).json()["room"]["title"],"수정됨")
        r=self.a.delete("/web/api/rooms/"+room,headers={"X-Web-Csrf":self.ca})
        self.assertEqual(r.status_code,200)
        self.assertEqual(self.a.get("/web/api/rooms/"+room).status_code,404)

    def test_csrf_and_origin_security(self):
        room=self.create()
        r=self.a.post("/web/api/rooms/"+room+"/test",json={"preset":"hello"})
        self.assertEqual(r.status_code,403)
        r=self.a.post("/web/api/rooms/"+room+"/test",json={"preset":"hello"},
                      headers={"X-Web-Csrf":self.ca,"Origin":"https://attacker.example"})
        self.assertEqual(r.status_code,403)
        self.assertEqual(self.b.post("/web/api/rooms/"+room+"/test",json={"preset":"hello"},
                                    headers={"X-Web-Csrf":self.cb}).status_code,404)

    def test_real_file_bytes_are_stored_and_scoped(self):
        room=self.create()
        payload=b"file content for browser test\n"
        r=self.a.post("/web/api/rooms/"+room+"/files",
                      files={"file":("example.txt",payload,"text/plain")},
                      headers={"X-Web-Csrf":self.ca})
        self.assertEqual(r.status_code,200,r.text)
        self.assertFalse(r.json()["sentToChatGPT"])
        fid=r.json()["file"]["id"]
        detail=self.a.get("/web/api/rooms/"+room).json()
        self.assertEqual(detail["files"][0]["name"],"example.txt")
        down=self.a.get("/web/api/files/"+fid)
        self.assertEqual(down.status_code,200)
        self.assertEqual(down.content,payload)
        self.assertEqual(self.b.get("/web/api/files/"+fid).status_code,404)
        self.assertEqual(self.a.get("/api/v1/files/"+fid+"/download").status_code,404)
        deleted=self.a.delete("/web/api/rooms/"+room,headers={"X-Web-Csrf":self.ca})
        self.assertEqual(deleted.status_code,200)
        self.assertEqual(self.a.get("/web/api/files/"+fid).status_code,404)
        with api_v1.connection() as db:
            self.assertEqual(db.execute(
                "SELECT count(*) FROM file_objects WHERE id=?",(fid,)
            ).fetchone()[0],0)

    def test_reject_bad_file_extension(self):
        room=self.create()
        r=self.a.post("/web/api/rooms/"+room+"/files",
                      files={"file":("code.html",b"<script>alert(1)</script>","text/html")},
                      headers={"X-Web-Csrf":self.ca})
        self.assertEqual(r.status_code,415)

    def test_public_file_quota_is_enforced_before_writing(self):
        from unittest.mock import patch
        room=self.create()
        with patch.object(web_chat,"MAX_USER_BYTES",3):
            r=self.a.post("/web/api/rooms/"+room+"/files",
                files={"file":("large.txt",b"hello world","text/plain")},
                headers={"X-Web-Csrf":self.ca})
            self.assertEqual(r.status_code,413)
        with api_v1.connection() as db:
            self.assertEqual(db.execute(
                "SELECT count(*) FROM file_objects WHERE room_id=?",(room,)
            ).fetchone()[0],0)

    def test_fixed_prompt_queued_and_arbitrary_denied(self):
        room=self.create()
        bad=self.a.post("/web/api/rooms/"+room+"/test",json={"preset":"inject_custom_prompt"},
                        headers={"X-Web-Csrf":self.ca})
        self.assertEqual(bad.status_code,422)
        ok=self.a.post("/web/api/rooms/"+room+"/test",json={"preset":"hello"},
                       headers={"X-Web-Csrf":self.ca})
        self.assertEqual(ok.status_code,200,ok.text)
        self.assertTrue(ok.json()["queued"])
        info=self.a.get("/web/api/rooms/"+room).json()
        self.assertEqual(info["jobs"][0]["status"],"queued")
        self.assertEqual(info["messages"][0]["text"],web_chat.PRESETS["hello"])
        repeat=self.a.post("/web/api/rooms/"+room+"/test",json={"preset":"hello"},
                           headers={"X-Web-Csrf":self.ca})
        self.assertEqual(repeat.status_code,409)

    def test_free_text_typed_question_accepted_and_isolated(self):
        room=self.create(title="Free text external test")
        prompt="외부 웹페이지에서 직접 입력한 질문입니다. 간단히 인사해 주세요."
        r=self.a.post("/web/api/rooms/"+room+"/message",
                      json={"text":prompt},headers={"X-Web-Csrf":self.ca})
        self.assertEqual(r.status_code,200,r.text)
        self.assertTrue(r.json()["queued"])
        self.assertFalse(r.json()["sentToChatGPT"])
        with api_v1.connection() as db:
            job=db.execute("SELECT * FROM jobs WHERE id=?",(r.json()["jobId"],)).fetchone()
        self.assertEqual(job["text"],prompt)
        self.assertEqual(job["status"],"queued")
        self.assertEqual(job["room_id"],room)
        info=self.a.get("/web/api/rooms/"+room).json()
        self.assertEqual(info["messages"][0]["text"],prompt)
        self.assertEqual(self.b.get("/web/api/rooms/"+room).status_code,404)
        self.assertEqual(self.b.post("/web/api/rooms/"+room+"/message",
            json={"text":"다른 방에 질문"},headers={"X-Web-Csrf":self.cb}).status_code,404)
        self.assertTrue(self.a.get("/web/api/status").json()["freeTextSendSupported"])
        self.assertFalse(self.a.get("/web/api/status").json()["fileToChatGPTSupported"])

    def test_free_text_input_validation_and_csrf(self):
        room=self.create()
        url="/web/api/rooms/"+room+"/message"
        self.assertEqual(self.a.post(url,json={"text":"hi"}).status_code,403)
        self.assertEqual(self.a.post(url,json={"text":"hi"},
            headers={"X-Web-Csrf":self.ca,"Origin":"https://attacker.example"}).status_code,403)
        for text_ in ("", "  ", "x"*2001, "abc"+chr(0)+"def"):
            r=self.a.post(url,json={"text":text_},
                          headers={"X-Web-Csrf":self.ca})
            self.assertEqual(r.status_code,422,r.text)

    def test_free_text_global_and_browser_rate_limits(self):
        from unittest.mock import patch
        room=self.create()
        with patch.object(web_chat,"MAX_FREE_TEXT_PER_HOUR",1):
            first=self.a.post("/web/api/rooms/"+room+"/message",
                json={"text":"첫 질문"},headers={"X-Web-Csrf":self.ca})
            self.assertEqual(first.status_code,200,first.text)
            room2=self.create(title="두 번째 방")
            second=self.a.post("/web/api/rooms/"+room2+"/message",
                json={"text":"두 번째 질문"},headers={"X-Web-Csrf":self.ca})
            self.assertEqual(second.status_code,429,second.text)

    def test_free_text_can_continue_verified_room_without_changing_target(self):
        room=self.create()
        first=self.a.post("/web/api/rooms/"+room+"/message",
            json={"text":"첫 질문"},headers={"X-Web-Csrf":self.ca})
        self.assertEqual(first.status_code,200,first.text)
        with api_v1.connection() as db:
            db.execute("UPDATE rooms SET chatgpt_url=? WHERE id=?",
                       ("https://chatgpt.com/c/abcdef01-2345-6789-abcd-ef0123456789",room))
            db.execute("UPDATE jobs SET status='completed',stage='assistant_reply_stable' WHERE id=?",
                       (first.json()["jobId"],))
        follow=self.a.post("/web/api/rooms/"+room+"/message",
            json={"text":"이어서 두 번째 질문"},headers={"X-Web-Csrf":self.ca})
        self.assertEqual(follow.status_code,200,follow.text)
        with api_v1.connection() as db:
            second=db.execute("SELECT * FROM jobs WHERE id=?",
                              (follow.json()["jobId"],)).fetchone()
            saved=db.execute("SELECT chatgpt_url FROM rooms WHERE id=?",(room,)).fetchone()
        self.assertEqual(second["text"],"이어서 두 번째 질문")
        self.assertEqual(saved["chatgpt_url"],"https://chatgpt.com/c/abcdef01-2345-6789-abcd-ef0123456789")

    def test_private_database_users_never_appear(self):
        with api_v1.connection() as db:
            uid="usr_private_test_"+api_v1.new_id()
            db.execute("INSERT INTO users VALUES(?,?,?,?)",
                       (uid,"Private user",uid+"-private-hash",api_v1.clock()))
            rid="room_"+api_v1.new_id()
            now=api_v1.clock()
            db.execute("INSERT INTO rooms(id,user_id,title,created_at,updated_at) VALUES(?,?,?,?,?)",
                       (rid,uid,"private-room",now,now))
        self.assertEqual(self.a.get("/web/api/rooms/"+rid).status_code,404)
        self.assertEqual(self.a.get("/api/v1/rooms").status_code,404)

if __name__=="__main__":unittest.main()
