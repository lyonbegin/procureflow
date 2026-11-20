"""Offline-only regression tests for zero-Chrome HITEL direct Web2API transport."""
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/".github"/"scripts"))
import hitel_direct_http_transport as direct
import hitel_direct_web2api_worker as worker

ROOM_A="room_"+"a"*32
ROOM_S="room_"+"b"*32
CID_A="a"*8+"-"+"a"*4+"-"+"a"*4+"-"+"a"*4+"-"+"a"*12
CID_S="b"*8+"-"+"b"*4+"-"+"b"*4+"-"+"b"*4+"-"+"b"*12
PARENT_A="c"*8+"-"+"c"*4+"-"+"c"*4+"-"+"c"*4+"-"+"c"*12
PARENT_S="d"*8+"-"+"d"*4+"-"+"d"*4+"-"+"d"*4+"-"+"d"*12
NEXT_A="e"*8+"-"+"e"*4+"-"+"e"*4+"-"+"e"*4+"-"+"e"*12
NEXT_S="f"*8+"-"+"f"*4+"-"+"f"*4+"-"+"f"*4+"-"+"f"*12


class DirectTransportTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.oauth=Path(self.temp.name)/"codex.json"
        self.oauth.write_text(json.dumps({"tokens":{"access_token":"test-not-real-token",
                                                     "account_id":"oai_example"}}))
        self.client=direct.DirectWeb2API(oauth_file=str(self.oauth),api_key="isolated-qa-local-key")
        self.calls=[]

    def fake(self,url,*,method,headers,body=None,timeout=45,send=False):
        self.calls.append((url,method,dict(headers),body,send))
        if url.endswith("/readyz"):
            return {"ready":True,"checks":{"chatgpt_auth_configured":True,
                         "requirements_provider_configured":True,
                         "browser_transport_configured":False}},{}
        if "/backend-api/conversation/" in url:
            cid=url.rsplit("/",1)[-1]
            mid=PARENT_A if cid==CID_A else PARENT_S
            return {"conversation_id":cid,"current_node":mid,"mapping":{
                 mid:{"message":{"id":mid,"author":{"role":"assistant"}}}}},{}
        if url.endswith("/v1/chat/completions"):
            cid=headers.get("X-GPTWeb-Conversation-ID",CID_A)
            mid=NEXT_A if cid==CID_A else NEXT_S
            marker=body["messages"][0]["content"]
            return {"choices":[{"message":{"role":"assistant","content":"echo:"+marker}}]},{
                    "X-GPTWeb-Conversation-ID":cid,
                    "X-GPTWeb-Assistant-Message-ID":mid}
        self.fail("Unexpected URL "+url)

    def test_reject_remote_gateway_ssrf(self):
        for url in ("https://example.com", "http://localhost:8787",
                    "http://127.0.0.1:8787.evil.org",
                    "http://127.0.0.1:8787/?forward=evil",
                    "http://user@127.0.0.1:8787"):
            with self.subTest(url=url), self.assertRaises(direct.DirectError):
                direct.validate_gateway_url(url)

    def test_reject_untrusted_conversation_url(self):
        for url in ("http://chatgpt.com/c/"+CID_A,
                    "https://evil.com/c/"+CID_A,
                    "https://chatgpt.com/c/"+CID_A+"?x=1",
                    "https://chatgpt.com/c/abc",
                    "https://chatgpt.com.evil.org/c/"+CID_A):
            with self.subTest(url=url),self.assertRaises(direct.DirectError):
                direct.conversation_from_url(url)

    def test_two_rooms_readonly_bootstrap_and_independent_post(self):
        with patch.object(direct,"_http_json",side_effect=self.fake):
            a=self.client.bootstrap(ROOM_A,"https://chatgpt.com/c/"+CID_A)
            s=self.client.bootstrap(ROOM_S,"https://chatgpt.com/c/"+CID_S)
            self.assertNotEqual(a,s)
            self.assertTrue(a.startswith("direct-http-"))
            self.assertEqual([x[-1] for x in self.calls], [False,False,False,False])
            av,acid=self.client.send(ROOM_A,"A-qa","https://chatgpt.com/c/"+CID_A)
            sv,scid=self.client.send(ROOM_S,"S-qa","https://chatgpt.com/c/"+CID_S)
            self.assertEqual((av,acid),("echo:A-qa",CID_A))
            self.assertEqual((sv,scid),("echo:S-qa",CID_S))
            posts=[x for x in self.calls if x[-1]]
            self.assertEqual(len(posts),2)
            self.assertEqual(posts[0][2]["X-GPTWeb-Parent-Message-ID"],PARENT_A)
            self.assertEqual(posts[1][2]["X-GPTWeb-Parent-Message-ID"],PARENT_S)
            self.assertEqual(self.client.binding(ROOM_A,"https://chatgpt.com/c/"+CID_A).parent_message_id,NEXT_A)
            self.assertEqual(self.client.binding(ROOM_S,"https://chatgpt.com/c/"+CID_S).parent_message_id,NEXT_S)

    def test_bad_binding_refuses_any_post(self):
        with patch.object(direct,"_http_json",side_effect=self.fake):
            self.client.bootstrap(ROOM_A,"https://chatgpt.com/c/"+CID_A)
            with self.assertRaises(direct.DirectError):
                self.client.send(ROOM_A,"prompt","https://chatgpt.com/c/"+CID_S)
        self.assertFalse(any(x[-1] for x in self.calls))

    def test_after_post_429_never_retry_same_room(self):
        def rate(url,**kw):
            if kw.get("send"):
                raise direct.DirectError("DIRECT_SEND_HTTP_429_RATE_LIMIT",after_post=True)
            return self.fake(url,**kw)
        with patch.object(direct,"_http_json",side_effect=rate):
            self.client.bootstrap(ROOM_A,"https://chatgpt.com/c/"+CID_A)
            with self.assertRaises(direct.DirectError) as cm:
                self.client.send(ROOM_A,"first","https://chatgpt.com/c/"+CID_A)
            self.assertTrue(cm.exception.after_post)
            with self.assertRaises(direct.DirectError) as cm:
                self.client.send(ROOM_A,"second","https://chatgpt.com/c/"+CID_A)
            self.assertEqual(cm.exception.code,"DIRECT_ROOM_DELIVERY_UNCERTAIN")

    def test_post_wrong_conversation_is_quarantined(self):
        def redirect(url,**kw):
            if kw.get("send"):
                return {"choices":[{"message":{"content":"done"}}]},{
                    "X-GPTWeb-Conversation-ID":CID_S,
                    "X-GPTWeb-Assistant-Message-ID":NEXT_S}
            return self.fake(url,**kw)
        with patch.object(direct,"_http_json",side_effect=redirect):
            self.client.bootstrap(ROOM_A,"https://chatgpt.com/c/"+CID_A)
            with self.assertRaises(direct.DirectError):
                self.client.send(ROOM_A,"test","https://chatgpt.com/c/"+CID_A)
            with self.assertRaises(direct.DirectError):
                self.client.binding(ROOM_A,"https://chatgpt.com/c/"+CID_A)

    def test_missing_turn_ids_never_success(self):
        def no_ids(url,**kw):
            if kw.get("send"):
                return {"choices":[{"message":{"content":"answer"}}]},{}
            return self.fake(url,**kw)
        with patch.object(direct,"_http_json",side_effect=no_ids):
            with self.assertRaises(direct.DirectError) as cm:
                self.client.send(ROOM_A,"test",None)
            self.assertEqual(cm.exception.code,"DIRECT_RETURNED_TURN_IDS_MISSING")

    def test_remote_parent_absent_never_send(self):
        def missing(url,**kw):
            if "/backend-api/conversation/" in url:
                return {"mapping":{},"current_node":"unknown"},{}
            return self.fake(url,**kw)
        with patch.object(direct,"_http_json",side_effect=missing):
            with self.assertRaises(direct.DirectError):
                self.client.send(ROOM_A,"test","https://chatgpt.com/c/"+CID_A)
        self.assertFalse(any(x[-1] for x in self.calls))

    def test_worker_rejects_bad_target_mismatch(self):
        job={"id":"job_"+"a"*32,"room_id":ROOM_A,"text":"Hello",
             "action":"chat.send","target_conversation_id":CID_A,
             "target_chatgpt_url":"https://chatgpt.com/c/"+CID_S}
        with self.assertRaises(direct.DirectError):
            worker._job_contract(job)
        job["target_chatgpt_url"]="https://chatgpt.com/c/"+CID_A
        self.assertEqual(worker._job_contract(job)[3],job["target_chatgpt_url"])

    def test_worker_denies_account_bound_and_attachments(self):
        job={"id":"job_"+"a"*32,"room_id":ROOM_A,
             "text":"a","action":"chat.send","account_id":"oai_any"}
        with self.assertRaises(direct.DirectError):
            worker._job_contract(job)
        job.pop("account_id")
        job["attachment_ids"]=["file-any"]
        with self.assertRaises(direct.DirectError):
            worker._job_contract(job)

    def test_no_browser_import_or_ui_code(self):
        roots=[Path(direct.__file__),Path(worker.__file__)]
        contents="\n".join(p.read_text() for p in roots)
        for string in ("import playwright", "import selenium", "import pyautogui",
                       "import hitel_room_tab_pool", "click_send(", "type_message(",
                       "connect_over_cdp(", "Popen(", "subprocess.run("):
            with self.subTest(string=string):
                self.assertNotIn(string,contents)
        self.assertNotIn("api.openai.com",contents)


if __name__=="__main__":
    unittest.main(verbosity=2)
