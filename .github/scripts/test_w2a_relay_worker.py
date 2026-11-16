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

    def test_account_job_missing_server_verified_email_refused_before_send(self):
        for requested in ("oai_A", "oai_B", ""):
            with patch.object(worker, "post_chat") as send:
                with self.assertRaises(ValueError):
                    asyncio.run(worker.process_job(dict(JOB, account_id=requested)))
            send.assert_not_called()

    def test_real_chrome_identity_match_permits_single_send(self):
        job=dict(JOB,account_id="oai_A",account_email="Owner@Example.com")
        with patch.object(worker,"actual_chrome_account",return_value="owner@example.com") as gate, \
             patch.object(worker,"verify_same_session",return_value=True) as check, \
             patch.object(worker,"post_chat",return_value=("Account answer",CID)) as sender:
            result=asyncio.run(worker.process_job(job))
        gate.assert_called_once_with("owner@example.com")
        self.assertEqual(check.call_count,2)
        sender.assert_called_once_with("Please answer",None)
        self.assertEqual(result["execution_account_id"],"oai_A")
        self.assertEqual(result["execution_account_email"],"owner@example.com")
        self.assertIs(result["session_verified"],True)

    def test_wrong_chrome_identity_stops_before_post(self):
        from w2a_account_runtime import AccountGateError
        job=dict(JOB,account_id="oai_B",account_email="b@example.com")
        with patch.object(worker,"actual_chrome_account",side_effect=AccountGateError(
                "ACCOUNT_LOGIN_WRONG_IDENTITY")), \
             patch.object(worker,"post_chat") as sender:
            with self.assertRaisesRegex(AccountGateError,"ACCOUNT_LOGIN_WRONG_IDENTITY"):
                asyncio.run(worker.process_job(job))
        sender.assert_not_called()

    def test_session_drift_just_before_post_stops(self):
        job=dict(JOB,account_id="oai_A",account_email="a@example.com")
        with patch.object(worker,"actual_chrome_account",return_value="a@example.com"), \
             patch.object(worker,"verify_same_session",return_value=False), \
             patch.object(worker,"post_chat") as sender:
            with self.assertRaisesRegex(ValueError,"ACCOUNT_EXECUTION_NOT_VERIFIED"):
                asyncio.run(worker.process_job(job))
        sender.assert_not_called()

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
