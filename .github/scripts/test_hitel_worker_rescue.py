#!/usr/bin/env python3
import datetime as dt
import unittest
from unittest.mock import patch
import hitel_worker_rescue as m


def ts(minutes=0):
    return (dt.datetime.now(dt.timezone.utc)-dt.timedelta(minutes=minutes)).isoformat()


def run(id=8,status="in_progress",minutes=20,title="normal"):
    return {"id":id,"name":m.TITLE_PREFIX+title,
            "path":".github/workflows/"+m.WORKFLOW,
            "status":status,"head_branch":"main",
            "display_title":m.TITLE_PREFIX+title,
            "created_at":ts(minutes)}


class Fake:
    def __init__(self,replies=()):
        self.replies=list(replies);self.calls=[]
    def request(self,verb,path,data=None):
        self.calls.append((verb,path,data))
        return self.replies.pop(0)


def status(connected=False,jobs=0):
    return {"worker_connected":connected,
            "worker_heartbeat_recent":connected,
            "worker_bootstrap_ready":connected,
            "worker_active_jobs_count":jobs}


class WorkerRescueTests(unittest.TestCase):
    def test_healthy_never_launches(self):
        api=Fake()
        self.assertEqual(m.monitor(api,status(True),[run()]),"healthy")
        self.assertEqual(api.calls,[])
    def test_keep_active_chatgpt_request(self):
        api=Fake()
        self.assertEqual(m.monitor(api,status(False,1),[run()]),"inflight_preserved")
        self.assertEqual(api.calls,[])
    def test_existing_queued_worker_prevents_dispatch(self):
        api=Fake()
        self.assertEqual(m.monitor(api,status(),[run(status="queued")]),
                         "startup_or_queued")
        self.assertEqual(api.calls,[])
    def test_startup_under_eight_minutes_not_cancelled(self):
        api=Fake()
        self.assertEqual(m.monitor(api,status(),[run(minutes=4)]),
                         "startup_grace")
        self.assertEqual(api.calls,[])
    def test_disconnect_recovers_during_second_check(self):
        api=Fake()
        self.assertEqual(m.monitor(api,status(),[run(minutes=11)],
                         probe=lambda:status(True),sleep=lambda _:None),
                         "reconnected_or_inflight_preserved")
        self.assertEqual(api.calls,[])
    def test_old_disconnected_with_zero_jobs_gets_one_replacement(self):
        api=Fake([(202,None),(204,None)])
        r=m.monitor(api,status(),[run(minutes=20)],
                    probe=lambda:status(),sleep=lambda _:None)
        self.assertEqual(r,"replacement_queued")
        self.assertEqual([c[0] for c in api.calls],["POST","POST"])
        self.assertIn("cancel",api.calls[0][1])
        self.assertEqual(api.calls[1][2]["inputs"]["rescue_token"],
                         "rescue-replace-8")
    def test_old_but_has_jobs_on_second_probe_is_not_cancelled(self):
        api=Fake()
        self.assertEqual(m.monitor(api,status(),[run(minutes=20)],
                        probe=lambda:status(False,2),sleep=lambda _:None),
                         "reconnected_or_inflight_preserved")
        self.assertEqual(api.calls,[])
    def test_no_active_run_dispatches_original_worker_with_fixed_identity(self):
        api=Fake([(200,{"workflow_runs":[]}), (204,None)])
        result=m.monitor(api,status(),[run(status="completed")],
                         sleep=lambda _:None)
        self.assertEqual(result,"accepted")
        self.assertEqual([c[0] for c in api.calls],["GET","POST"])
        self.assertEqual(api.calls[-1][2]["inputs"]["rescue_token"],
                         "rescue-after-8")
    def test_token_dedup_prevents_another_worker(self):
        api=Fake()
        with patch.object(m,"list_worker_runs",
                 return_value=[run(status="completed",
                                   title="rescue-after-8")]):
            result=m.launch_existing_worker(api,"rescue-after-8")
        self.assertEqual(result,("already_dispatched",8))
        self.assertEqual(api.calls,[])
    def test_worker_listing_recognizes_dynamic_run_name_by_immutable_path(self):
        api=Fake([(200,{"workflow_runs":[run(11,"in_progress",8),
             {"id":12,"name":"irrelevant","path":".github/workflows/other.yml",
              "created_at":ts(2),"head_branch":"main"}]})])
        actual=m.list_worker_runs(api)
        self.assertEqual([x["id"] for x in actual],[11])

    def test_session_end_dispatches_exactly_one_successor(self):
        run_self=run(123,"in_progress",240)
        api=Fake([(200,{"workflow_runs":[run_self]}),(204,None)])
        self.assertEqual(
            m.handoff_after_previous_session(api,"123"),
            "successor_accepted")
        self.assertEqual(sum(c[0]=="POST" for c in api.calls),1)
        self.assertEqual(api.calls[-1][2]["inputs"]["rescue_token"],
                         "rescue-after-123")

    def test_session_end_with_queued_successor_does_not_launch(self):
        me=run(123,"in_progress",240)
        next_run=run(124,"queued",1,"rescue-after-123")
        api=Fake([(200,{"workflow_runs":[next_run,me]})])
        self.assertEqual(
            m.handoff_after_previous_session(api,"123"),
            "successor_already_queued")
        self.assertFalse(any(c[0]=="POST" for c in api.calls))

    def test_session_end_ambiguous_500_never_reposts(self):
        api=Fake([(200,{"workflow_runs":[run(123,"in_progress",240)]}),
                  (500,None)])
        self.assertEqual(
            m.handoff_after_previous_session(api,"123"),
            "ambiguous_session_handoff_watchdog_will_recheck")
        self.assertEqual(sum(c[0]=="POST" for c in api.calls),1)

    def test_bad_worker_list_fails_closed(self):
        api=Fake([(500,None)])
        with self.assertRaisesRegex(RuntimeError,"DISCOVERY_HTTP_500"):
            m.list_worker_runs(api)
        self.assertEqual(len(api.calls),1)
    def test_dispatch_500_ambiguous_no_immediate_repost(self):
        empty=(200,{"workflow_runs":[]})
        api=Fake([empty,(500,None)]+[empty]*6)
        result=m.launch_existing_worker(api,"rescue-after-9",sleep=lambda _:None)
        self.assertEqual(result,("ambiguous_5xx_recheck_next_schedule",None))
        self.assertEqual(sum(x[0]=="POST" for x in api.calls),1)
    def test_500_accepted_but_indexed_never_reposts(self):
        empty=(200,{"workflow_runs":[]})
        found=(200,{"workflow_runs":[run(10,"queued",1,"rescue-after-8")]})
        api=Fake([empty,(500,None),found])
        result=m.launch_existing_worker(api,"rescue-after-8",sleep=lambda _:None)
        self.assertEqual(result,("accepted_after_5xx",10))
        self.assertEqual(sum(x[0]=="POST" for x in api.calls),1)


if __name__=="__main__":
    unittest.main()
