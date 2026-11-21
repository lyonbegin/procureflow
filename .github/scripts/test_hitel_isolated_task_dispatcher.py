#!/usr/bin/env python3
import unittest
from unittest.mock import patch
import hitel_isolated_task_dispatcher as d


def tasks(stock=1,scribd=1):
    return [
        {"task_id":"stock-a","queued_jobs_count":stock,
         "worker_connected":False,"worker_active_jobs_count":0},
        {"task_id":"stock-tv","queued_jobs_count":0,
         "worker_connected":False,"worker_active_jobs_count":0},
        {"task_id":"scribd-18109","queued_jobs_count":scribd,
         "worker_connected":False,"worker_active_jobs_count":0},
    ]


class IsolationDispatcherTests(unittest.TestCase):
    def test_two_tasks_independently_dispatch(self):
        p=d.plan(tasks(),[])
        self.assertEqual(p["stock-a"],"dispatch")
        self.assertEqual(p["scribd-18109"],"dispatch")
        self.assertEqual(p["stock-tv"],"no_queued_job")

    def test_one_task_running_does_not_block_other(self):
        run={"head_branch":"main",
             "path":".github/workflows/"+d.WORKFLOW,
             "display_title":"HITEL isolated Chrome scribd-18109",
             "status":"in_progress"}
        p=d.plan(tasks(),[run])
        self.assertEqual(p["scribd-18109"],"worker_queued_or_running")
        self.assertEqual(p["stock-a"],"dispatch")

    def test_same_task_queued_cannot_launch_duplicate(self):
        run={"head_branch":"main",
             "path":".github/workflows/"+d.WORKFLOW,
             "display_title":"HITEL isolated Chrome stock-a",
             "status":"queued"}
        self.assertEqual(d.plan(tasks(),[run])["stock-a"],
                         "worker_queued_or_running")

    def test_live_worker_does_not_relaunch(self):
        x=tasks();x[0]["worker_connected"]=True
        self.assertEqual(d.plan(x,[])["stock-a"],"healthy")

    def test_invalid_unknown_task_is_rejected(self):
        t=tasks();t[0]["task_id"]="not-authorized"
        with self.assertRaisesRegex(ValueError,"UNKNOWN_TASK"):
            d.plan(t,[])

    def test_invalid_active_count_fails_closed(self):
        t=tasks();t[0]["worker_active_jobs_count"]="unknown"
        with self.assertRaisesRegex(ValueError,"INVALID_TASK_ACTIVE"):
            d.plan(t,[])

    def test_dynamic_legacy_worker_name_does_not_block_new_one(self):
        run={"head_branch":"main",
             "path":".github/workflows/hitel-integration-bridge-live-qa.yml",
             "display_title":"HITEL Chrome worker normal",
             "status":"in_progress"}
        self.assertEqual(d.plan(tasks(),[run])["stock-a"],"dispatch")

    def test_dispatch_includes_task_id_and_main(self):
        class FakeResponse:
            status=204
            def __enter__(self): return self
            def __exit__(self,*args): pass
        with patch.object(d.urllib.request,"urlopen",return_value=FakeResponse()) as fn:
            self.assertEqual(d.dispatch("hidden","lyonbegin/procureflow","stock-a"),
                             "worker_start_accepted")
            req=fn.call_args.args[0]
            self.assertIn(b'"task_id": "stock-a"',req.data)
            self.assertIn(b'"ref": "main"',req.data)
    def test_500_ambiguous_no_same_run_retry(self):
        import urllib.error
        with patch.object(d.urllib.request,"urlopen",
            side_effect=urllib.error.HTTPError("https://example",500,"",{},None)) as fn:
            self.assertEqual(d.dispatch("hidden","lyonbegin/procureflow","stock-tv"),
                "dispatch_ambiguous_recheck_next_schedule")
            self.assertEqual(fn.call_count,1)


if __name__=="__main__":
    unittest.main()
