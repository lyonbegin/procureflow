"""Real adapter request-contract tests. No GitHub secrets or browser needed.

Covers the 2026-11-19 public API incident:
- Web2API reused its _last_conv_id when our code omitted new_conversation.
- ChatGPT DIL text extraction duplicated a tail after complete JSON.
"""
import importlib.util
import io
import json
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

root=Path(__file__).resolve().parents[3]
script=root/".github/scripts/w2a_relay_worker.py"
account=types.ModuleType("w2a_account_runtime")
account.AccountGateError=type("AccountGateError",(Exception,),{})
for name in ("actual_chrome_account","canonical_email",
             "verify_same_session","find_verified_cdp_port"):
    setattr(account,name,lambda *a,**kw:True)
sys.modules["w2a_account_runtime"]=account
spec=importlib.util.spec_from_file_location("hitel_worker_request_contract",script)
worker=importlib.util.module_from_spec(spec)
spec.loader.exec_module(worker)


class StubResponse(io.BytesIO):
    status=200


class TestChromeWorkerRequestContract(unittest.TestCase):
    def test_two_independent_rooms_explicitly_force_two_new_conversations(self):
        sent=[]
        def mocked_urlopen(request,timeout=None):
            payload=json.loads(request.data.decode("utf-8"))
            sent.append(payload)
            cid="synthetic-chat-000"+str(len(sent))
            return StubResponse(json.dumps({
                "choices":[{"message":{"content":"reply"+str(len(sent))}}],
                "conversation_id":cid,
            }).encode("utf-8"))
        with patch.object(worker.urllib.request,"urlopen",mocked_urlopen):
            one=worker.post_chat_uri("first independent room",None,worker.CHAT_API)
            two=worker.post_chat_uri("second independent room",None,worker.CHAT_API)
        self.assertNotEqual(one[1],two[1])
        self.assertTrue(sent[0]["new_conversation"])
        self.assertTrue(sent[1]["new_conversation"])
        self.assertNotIn("conversation_id",sent[0])
        self.assertNotIn("conversation_id",sent[1])
        self.assertEqual(len(sent),2)

    def test_followup_preserves_exact_existing_conversation(self):
        target="abc12345-room"
        capture=[]
        def mocked_urlopen(request,timeout=None):
            p=json.loads(request.data.decode("utf-8"))
            capture.append(p)
            return StubResponse(json.dumps({
                "choices":[{"message":{"content":"follow-up"}}],
                "conversation_id":target,
            }).encode("utf-8"))
        with patch.object(worker.urllib.request,"urlopen",mocked_urlopen):
            answer,cid=worker.post_chat_uri("second turn in existing room",
                                            target,worker.CHAT_API)
        self.assertEqual(cid,target)
        self.assertEqual(capture[0]["conversation_id"],target)
        self.assertNotIn("new_conversation",capture[0])

    def test_json_duplicate_tail_from_real_dom_shape_is_cleaned(self):
        record={"rows":[
            {"no":1,"reason":"대수는 2022 개정 고등학교 수학의 독립 과목명. 해당 과목의 문제 자료로 판단.","edition":"2022확인"},
            {"no":2,"reason":"중3-1은 중학교 3학년 1학기 수학 교재이며 2015개정이 명시됨. 중등 교재이므로 다운로드 대상."}
        ]}
        original=json.dumps(record,ensure_ascii=False,indent=2)
        repeated_tail=original[original.index("대수는"):].replace("  "," ")
        defective=original+repeated_tail
        self.assertNotEqual(defective,original)
        normalized=worker.discard_verified_duplicate_json_tail(defective)
        self.assertEqual(json.loads(normalized),record)
        self.assertEqual(normalized,original)

    def test_short_exact_suffix_from_live_chatgpt_reply_is_cleaned(self):
        actual='{"hitel_v4_smoke":"OK"}e":"OK"}'
        self.assertEqual(
            worker.discard_verified_duplicate_json_tail(actual),
            '{"hitel_v4_smoke":"OK"}')
        self.assertEqual(json.loads(worker.discard_verified_duplicate_json_tail(actual)),
                         {"hitel_v4_smoke":"OK"})

    def test_similar_short_tail_not_provably_repeated_remains_unchanged(self):
        raw='{"hitel_v4_smoke":"OK"}e":"NO"}'
        self.assertEqual(worker.discard_verified_duplicate_json_tail(raw),raw)

    def test_legitimate_post_json_explanation_is_not_discarded(self):
        raw='{"rows":[{"id":"A123","title":"example"}]}\n설명: 데이터는 참고용입니다.'
        self.assertEqual(worker.discard_verified_duplicate_json_tail(raw),raw)

    def test_existing_valid_json_unmodified(self):
        raw='{"rows":[{"id":1}]}'
        self.assertEqual(worker.discard_verified_duplicate_json_tail(raw),raw)

    def test_followup_prewarms_exact_room_before_send(self):
        import asyncio
        from unittest.mock import AsyncMock,Mock
        room="room_"+"a"*32
        target="abcdefgh-existing-2026"
        class PinnedPool:
            def __init__(self):
                self.calls=[]
            async def navigate_existing(self,rid,cdp,url):
                self.calls.append(("navigate",rid,cdp,url))
                return "target_browser_tab"
            async def endpoint(self,rid,cdp):
                self.calls.append(("endpoint",rid,cdp))
                return "http://127.0.0.1:18311/v1/chat/completions"
        pool=PinnedPool()
        def fake_post(text,cid,url,**kw):
            pool.calls.append(("send",cid))
            return '{"hitel_v4_smoke":"OK"}',cid
        job={"id":"job_"+"f"*32,"room_id":room,
             "action":"chat.send","text":"next turn",
             "target_conversation_id":target,
             "target_chatgpt_url":"https://chatgpt.com/c/"+target}
        with patch.object(worker,"post_chat_uri",side_effect=fake_post):
            reply=asyncio.run(worker.process_job(job,adapter_pool=pool))
        self.assertEqual(reply["type"],"job.result")
        self.assertEqual([x[0] for x in pool.calls],["navigate","endpoint","send"])
        self.assertEqual(pool.calls[0][1],room)
        self.assertEqual(pool.calls[0][3],job["target_chatgpt_url"])

    def test_vendor_http500_exposes_safe_stage_not_chat_text(self):
        import urllib.error
        body=io.BytesIO(json.dumps({"error":{
            "message":"Navigation to PRIVATE_CONVERSATION_123 failed after 15s - stage: composer missing",
            "code":"RuntimeError"
        }}).encode())
        exc=urllib.error.HTTPError("http://127.0.0.1:18311",500,"Oops",{},body)
        safe=worker._safe_vendor_http_error(exc)
        self.assertEqual(safe,"WEB2API_ADAPTER_HTTP_500_COMPOSER_UNAVAILABLE")
        self.assertNotIn("PRIVATE_CONVERSATION",safe)

    def test_nonjson_answer_unmodified(self):
        raw="이 문장은 일반 자연어 답변입니다."
        self.assertEqual(worker.discard_verified_duplicate_json_tail(raw),raw)


if __name__=="__main__":
    unittest.main()
