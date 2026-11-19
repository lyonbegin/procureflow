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

    def test_legitimate_post_json_explanation_is_not_discarded(self):
        raw='{"rows":[{"id":"A123","title":"example"}]}\n설명: 데이터는 참고용입니다.'
        self.assertEqual(worker.discard_verified_duplicate_json_tail(raw),raw)

    def test_existing_valid_json_unmodified(self):
        raw='{"rows":[{"id":1}]}'
        self.assertEqual(worker.discard_verified_duplicate_json_tail(raw),raw)

    def test_nonjson_answer_unmodified(self):
        raw="이 문장은 일반 자연어 답변입니다."
        self.assertEqual(worker.discard_verified_duplicate_json_tail(raw),raw)


if __name__=="__main__":
    unittest.main()
