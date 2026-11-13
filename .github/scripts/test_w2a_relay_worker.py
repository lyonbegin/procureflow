#!/usr/bin/env python3
"""Isolated worker protocol tests: no ChatGPT and no Railway traffic."""
import asyncio
import importlib.util
import os
import pathlib
import unittest
from unittest.mock import patch

source=pathlib.Path(__file__).resolve().with_name("w2a_relay_worker.py")
spec=importlib.util.spec_from_file_location("w2a_relay_worker",source)
worker=importlib.util.module_from_spec(spec)
spec.loader.exec_module(worker)

CID="e43a33a2-422a-46ab-9100-123456781234"
OTHER="e43a33a2-422a-46ab-9100-123456789999"
JOB={"id":"job_123","room_id":"room_test","action":"chat.send",
     "text":"Please answer",
     "attachment_ids":[],"target_conversation_id":None,
     "target_chatgpt_url":None}


class WorkerTests(unittest.TestCase):
    def test_first_send_pins_confirmed_chat(self):
        with patch.object(worker,"post_chat",return_value=("Actual answer",CID)) as f:
            result=asyncio.run(worker.process_job(dict(JOB)))
        self.assertEqual(result["stage"],"assistant_reply_stable")
        self.assertEqual(result["room_id"],"room_test")
        self.assertEqual(result["result_text"],"Actual answer")
        self.assertEqual(result["chatgpt_url"],"https://chatgpt.com/c/"+CID)
        f.assert_called_once_with("Please answer",None)

    def test_bound_room_id_sent_to_original_web2api(self):
        with patch.object(worker,"post_chat",return_value=("Second answer",CID)) as f:
            job=dict(JOB,target_conversation_id=CID,
                     target_chatgpt_url="https://chatgpt.com/c/"+CID)
            result=asyncio.run(worker.process_job(job))
        f.assert_called_once_with("Please answer",CID)
        self.assertEqual(result["result_text"],"Second answer")

    def test_reject_binary_attachments_before_chat(self):
        with patch.object(worker,"post_chat") as f:
            with self.assertRaisesRegex(ValueError,"WEB2API_BINARY_ATTACHMENT_NOT_VERIFIED"):
                asyncio.run(worker.process_job(dict(JOB,attachment_ids=["file_abc"])))
        f.assert_not_called()

    def test_unsupported_actions_fail_closed(self):
        with patch.object(worker,"post_chat") as f:
            for action in ("room.open","room.delete","room.bind","chat.new"):
                with self.assertRaisesRegex(ValueError,"UNSUPPORTED_WEB_WORKER_ACTION"):
                    asyncio.run(worker.process_job(dict(JOB,action=action)))
        f.assert_not_called()

    def test_wrong_room_from_web2api_rejected(self):
        with self.assertRaisesRegex(ValueError,"ROOM_CONVERSATION_ID_MISMATCH"):
            worker.parse_web2api_response(
                {"choices":[{"message":{"content":"good"}}],"conversation_id":OTHER},
                CID,
            )

    def test_unknown_conversation_id_rejected(self):
        with self.assertRaisesRegex(ValueError,"WEB2API_CONVERSATION_ID_MISSING"):
            worker.parse_web2api_response(
                {"choices":[{"message":{"content":"good"}}]},None,
            )

    def test_empty_answer_rejected(self):
        with self.assertRaisesRegex(ValueError,"WEB2API_ASSISTANT_REPLY_MISSING"):
            worker.parse_web2api_response(
                {"choices":[{"message":{"content":"  "}}],"conversation_id":CID},None,
            )

    def test_refuse_remote_host(self):
        for url in ("wss://evil.example/ws","ws://chatgpt-relay-web-production.up.railway.app/ws",
                    "wss://chatgpt-relay-web-production.up.railway.app:8000/ws"):
            with patch.dict(os.environ,{"RELAY_WS_URL":url}):
                with self.assertRaisesRegex(RuntimeError,"REFUSE_UNTRUSTED_RELAY_URL"):
                    worker.ws_destination()

    def test_authorized_host(self):
        with patch.dict(os.environ,{"RELAY_WS_URL":
             "wss://chatgpt-relay-web-production.up.railway.app/ws"}):
            self.assertTrue(worker.ws_destination().endswith("/ws"))


if __name__=="__main__":
    unittest.main()
