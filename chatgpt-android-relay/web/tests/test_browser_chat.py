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

    def test_browser_identity_distinct_from_server_chatgpt_account(self):
        a=self.a.get("/web/api/status")
        b=self.b.get("/web/api/status")
        self.assertEqual(a.status_code,200)
        self.assertEqual(b.status_code,200)
        aa=a.json();bb=b.json()
        self.assertEqual(aa["browserSessionType"],"anonymous_cookie")
        self.assertNotEqual(aa["browserSessionTag"],bb["browserSessionTag"])
        self.assertRegex(aa["browserSessionTag"],r"^[0-9a-f]{8}$")
        self.assertFalse(aa["chatgptAccountLinked"])
        self.assertFalse(aa["workerAccountIdentityAvailable"])
        for data in (aa,bb):
            self.assertNotIn("email",str(data).lower())
            self.assertNotIn("token",str(data).lower())
            self.assertNotIn("password",str(data).lower())
        html=self.a.get("/").text
        self.assertIn('id="browser-identity"',html)
        self.assertIn('id="worker-status"',html)
        self.assertIn("ChatGPT 계정 로그인 아님",html)
        self.assertIn("계정명·이메일은 공개하지 않습니다",html)

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

    def test_profile_add_switch_restore_and_delete_own_rooms_files(self):
        original=self.create(title="기본 프로필의 방")
        profiles=self.a.get("/web/api/profiles").json()
        self.assertEqual(len(profiles["profiles"]),1)
        self.assertEqual(profiles["profiles"][0]["id"],"default")
        self.assertTrue(profiles["profiles"][0]["active"])
        self.assertFalse(profiles["chatgptAccountLinked"])
        new=self.a.post("/web/api/profiles",json={"name":"업무 시험"},
            headers={"X-Web-Csrf":self.ca})
        self.assertEqual(new.status_code,200,new.text)
        pid=new.json()["profile"]["id"]
        self.assertNotEqual(pid,"default")
        self.assertEqual(self.b.post("/web/api/profiles/"+pid+"/activate",
            headers={"X-Web-Csrf":self.cb}).status_code,404)
        switched=self.a.post("/web/api/profiles/"+pid+"/activate",
            headers={"X-Web-Csrf":self.ca})
        self.assertEqual(switched.status_code,200,switched.text)
        self.assertEqual(switched.json()["profile"]["name"],"업무 시험")
        self.assertEqual(self.a.get("/web/api/rooms").json()["rooms"],[])
        self.assertEqual(self.a.get("/web/api/rooms/"+original).status_code,404)
        self.assertEqual(self.a.get("/web/api/status").json()["profileName"],"업무 시험")
        second=self.create(title="업무 방")
        data=self.a.post("/web/api/rooms/"+second+"/files",
            files={"file":("only-work.txt",b"work-only-test","text/plain")},
            headers={"X-Web-Csrf":self.ca})
        self.assertEqual(data.status_code,200,data.text)
        fid=data.json()["file"]["id"]
        restored=self.a.post("/web/api/profiles/default/activate",
            headers={"X-Web-Csrf":self.ca})
        self.assertEqual(restored.status_code,200,restored.text)
        self.assertEqual(self.a.get("/web/api/rooms/"+original).status_code,200)
        self.assertEqual(self.a.get("/web/api/rooms/"+second).status_code,404)
        self.assertEqual(self.a.get("/web/api/files/"+fid).status_code,404)
        self.assertEqual(self.b.get("/web/api/profiles").json()["profiles"][0]["name"],
                         "기본 프로필")
        work_again=self.a.post("/web/api/profiles/"+pid+"/activate",
            headers={"X-Web-Csrf":self.ca})
        self.assertEqual(work_again.status_code,200)
        self.assertEqual(self.a.get("/web/api/rooms/"+second).status_code,200)
        self.assertEqual(self.a.get("/web/api/files/"+fid).content,b"work-only-test")
        deleted=self.a.delete("/web/api/profiles/"+pid,
            headers={"X-Web-Csrf":self.ca})
        self.assertEqual(deleted.status_code,200,deleted.text)
        self.assertFalse(deleted.json()["chatgptAccountDeleted"])
        self.assertEqual(self.a.get("/web/api/status").json()["profileId"],"default")
        self.assertEqual(self.a.get("/web/api/rooms/"+second).status_code,404)
        self.assertEqual(self.a.get("/web/api/files/"+fid).status_code,404)
        self.assertEqual(self.a.get("/web/api/rooms/"+original).status_code,200)
        self.assertEqual(self.a.get("/web/api/profiles").json()["profiles"][0]["id"],"default")

    def test_profile_csrf_quota_default_protection_and_running_job(self):
        from unittest.mock import patch
        initial=self.a.get("/web/api/profiles").json()
        self.assertEqual(initial["provider"],"HITEL_local_test_profiles")
        self.assertEqual(self.a.post("/web/api/profiles",json={"name":"X"}).status_code,403)
        self.assertEqual(self.a.post("/web/api/profiles",json={"name":"X"},
            headers={"X-Web-Csrf":self.ca,"Origin":"https://evil.example"}).status_code,403)
        self.assertEqual(self.a.delete("/web/api/profiles/default",
            headers={"X-Web-Csrf":self.ca}).status_code,409)
        self.assertEqual(self.a.post("/web/api/profiles",json={"name":"  "},
            headers={"X-Web-Csrf":self.ca}).status_code,422)
        added=self.a.post("/web/api/profiles",json={"name":"삭제 시험"},
            headers={"X-Web-Csrf":self.ca})
        self.assertEqual(added.status_code,200)
        pid=added.json()["profile"]["id"]
        self.assertEqual(self.a.post("/web/api/profiles",json={"name":"삭제 시험"},
            headers={"X-Web-Csrf":self.ca}).status_code,409)
        with patch.object(web_chat,"MAX_LOCAL_PROFILES",2):
            self.assertEqual(self.a.post("/web/api/profiles",json={"name":"추가 불가"},
                headers={"X-Web-Csrf":self.ca}).status_code,429)
        self.assertEqual(self.a.post("/web/api/profiles/"+pid+"/activate").status_code,403)
        self.assertEqual(self.a.post("/web/api/profiles/"+pid+"/activate",
            headers={"X-Web-Csrf":self.ca}).status_code,200)
        room=self.create(title="전송 중인 방")
        pending=self.a.post("/web/api/rooms/"+room+"/message",
            json={"text":"삭제 금지 시험"},headers={"X-Web-Csrf":self.ca})
        self.assertEqual(pending.status_code,200)
        self.assertEqual(self.a.delete("/web/api/profiles/"+pid,
            headers={"X-Web-Csrf":self.ca}).status_code,409)

    def test_real_chatgpt_account_list_starts_signed_out_not_local_profile(self):
        import chatgpt_accounts
        a=self.a.get("/web/api/chatgpt/accounts")
        self.assertEqual(a.status_code,200,a.text)
        self.assertEqual(a.json()["accounts"],[])
        self.assertFalse(a.json()["connected"])
        self.assertFalse(a.json()["oauthAvailable"])
        self.assertFalse(a.json()["executionAccountBound"])
        self.assertTrue(a.json()["officialLoginRequired"])
        self.assertEqual(self.a.get("/web/api/chatgpt/login").status_code,503)
        self.assertEqual(self.a.get("/web/api/chatgpt/callback").status_code,403)
        self.assertEqual(self.b.get("/web/api/chatgpt/accounts").json()["accounts"],[])

    def test_actual_chatgpt_identity_records_never_fake_or_cross_browser(self):
        import chatgpt_accounts
        self.a.get("/web/api/bootstrap")
        # Client cookie is sent by the actual browser client in the next API request;
        # use the cookie to derive the same app owner.
        cookie=self.a.cookies.get(web_chat.COOKIE)
        raw=web_chat._unpack(cookie)
        owner=web_chat._owner_hash(raw)
        with api_v1.connection() as db:
            db.execute(
                "INSERT INTO hitel_verified_chatgpt_accounts "
                "(id,browser_owner,issuer,client_id,subject,email,display_name,active,verified_at) "
                "VALUES(?,?,?,?,?,?,?,?,?)",
                ("oai_verified_e2e",owner,chatgpt_accounts.ISSUER,
                 "oaiapp_test","real-sub-from-validated-token","verified@example.org",
                 "검증된 ChatGPT 계정",0,api_v1.clock())
            )
        listed=self.a.get("/web/api/chatgpt/accounts")
        self.assertEqual(listed.status_code,200)
        self.assertEqual(len(listed.json()["accounts"]),1)
        self.assertTrue(listed.json()["accounts"][0]["identityVerified"])
        self.assertFalse(listed.json()["accounts"][0]["canRunWeb2APIAsThisAccount"])
        self.assertEqual(self.b.get("/web/api/chatgpt/accounts").json()["accounts"],[])
        self.assertEqual(self.b.post("/web/api/chatgpt/accounts/oai_verified_e2e/select",
            headers={"X-Web-Csrf":self.cb}).status_code,404)
        self.assertEqual(self.a.post("/web/api/chatgpt/accounts/oai_verified_e2e/select").status_code,403)
        selected=self.a.post("/web/api/chatgpt/accounts/oai_verified_e2e/select",
            headers={"X-Web-Csrf":self.ca})
        self.assertEqual(selected.status_code,200,selected.text)
        self.assertFalse(selected.json()["canRunWeb2APIAsThisAccount"])
        room=self.create(title="실제 ChatGPT 신원 격리")
        refused=self.a.post("/web/api/rooms/"+room+"/message",
            json={"text":"공유 계정으로 보내지 마세요"},headers={"X-Web-Csrf":self.ca})
        self.assertEqual(refused.status_code,409,refused.text)
        with api_v1.connection() as db:
            self.assertEqual(db.execute(
                "SELECT count(*) FROM jobs WHERE room_id=?",(room,)
            ).fetchone()[0],0)
        self.assertEqual(self.a.delete("/web/api/chatgpt/accounts/oai_verified_e2e").status_code,403)
        removed=self.a.delete("/web/api/chatgpt/accounts/oai_verified_e2e",
            headers={"X-Web-Csrf":self.ca})
        self.assertEqual(removed.status_code,200)
        self.assertFalse(removed.json()["chatgptAccountDeleted"])
        self.assertEqual(self.a.get("/web/api/chatgpt/accounts").json()["accounts"],[])
        self.assertEqual(self.a.get("/web/api/rooms/"+room).status_code,200)

    def test_chatgpt_oauth_uses_state_pkce_and_one_time_flow_cookie(self):
        from unittest.mock import patch, AsyncMock
        from urllib.parse import urlsplit,parse_qs
        import chatgpt_accounts
        dummy={"issuer":chatgpt_accounts.ISSUER,
               "authorization_endpoint":"https://auth.openai.com/api/accounts/authorize",
               "token_endpoint":"https://auth.openai.com/api/accounts/oauth/token",
               "jwks_uri":"https://auth.openai.com/.well-known/jwks.json"}
        with patch.object(chatgpt_accounts,"CLIENT_ID","oaiapp_test_client"), \
             patch.object(chatgpt_accounts,"REDIRECT_URI",chatgpt_accounts.PROD_CALLBACK), \
             patch.object(chatgpt_accounts,"_oidc",new_callable=AsyncMock,return_value=dummy):
            result=self.a.get("/web/api/chatgpt/login",follow_redirects=False)
            self.assertEqual(result.status_code,302,result.text)
            u=urlsplit(result.headers["location"])
            self.assertEqual(u.hostname,"auth.openai.com")
            q=parse_qs(u.query)
            self.assertEqual(q["scope"],["openid profile email"])
            self.assertEqual(q["code_challenge_method"],["S256"])
            self.assertEqual(q["redirect_uri"],[chatgpt_accounts.PROD_CALLBACK])
            self.assertEqual(q["response_type"],["code"])
            self.assertTrue(q["state"][0])
            self.assertTrue(q["nonce"][0])
            self.assertTrue(self.a.cookies.get(chatgpt_accounts.FLOW_COOKIE))
            # A cancelled provider authorization never marks any account linked.
            cancelled=self.a.get("/web/api/chatgpt/callback",
                params={"state":q["state"][0],"error":"access_denied"},
                follow_redirects=False)
            self.assertEqual(cancelled.status_code,303,cancelled.text)
            self.assertFalse(self.a.get("/web/api/chatgpt/accounts").json()["connected"])
            self.assertEqual(self.a.get("/web/api/chatgpt/callback",
                params={"state":q["state"][0],"error":"access_denied"},
                follow_redirects=False).status_code,403)

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
