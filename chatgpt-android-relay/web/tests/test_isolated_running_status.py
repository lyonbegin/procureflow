#!/usr/bin/env python3
"""Isolated Chrome heartbeat is authoritative for isolated job status."""
import time
import unittest
from unittest.mock import patch

import api_v1
import integration_public as p
import long_job_events
import task_worker_isolation as isolation

JID = "job_" + "a" * 32


class FakeDB:
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def execute(self, sql, args):
        class Result:
            def fetchone(self):
                return {"task_id": "stock-tv"}
        return Result()


class IsolatedStatusTest(unittest.TestCase):
    def row(self):
        return {
            "status": "running", "stage": "web2api_assistant_seen",
            "error_code": None, "result_text": None,
            "request_id": "stock-tv-test-fixed-request-id",
            "room_id": "room_" + "b"*32, "room_name": "TV",
            "chatgpt_send_confirmed": True, "assistant_reply_observed": True,
            "worker_heartbeat_at": 123, "job_last_progress_at": 123,
            "event_stage": "web2api_assistant_seen", "error_stage": None,
            "error": None, "created_at": 123, "updated_at": 123,
        }

    def check(self, session):
        with patch.object(api_v1, "connection", return_value=FakeDB()), \
             patch.object(long_job_events, "job_row", return_value=self.row()), \
             patch.dict(isolation.sessions, {"stock-tv": session}, clear=True):
            return p.read_public_result(JID)

    def test_isolated_active_job_is_running_even_if_not_in_shared_browser(self):
        sess=isolation.Session(ws=None,run_id=12345,generation=2)
        sess.bootstrapped=True
        sess.heartbeat=time.monotonic()
        sess.active[JID]="room_" + "b"*32
        result=self.check(sess)
        self.assertEqual(result["status"],"running")
        self.assertIsNone(result["error_code"])
        self.assertTrue(result["worker_connected"])
        self.assertTrue(result["assistant_reply_observed"])

    def test_disconnected_isolated_job_is_not_falsely_completed(self):
        sess=isolation.Session(ws=None,run_id=12345,generation=2)
        sess.bootstrapped=True
        sess.heartbeat=time.monotonic()-1000
        sess.active[JID]="room_" + "b"*32
        result=self.check(sess)
        self.assertEqual(result["status"],"stalled")
        self.assertFalse(result["result_ready"])


if __name__ == "__main__":
    unittest.main()
