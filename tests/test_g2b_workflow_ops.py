"""Workflow planning must not pretend a queued job or partial G2B data is complete."""
from unittest.mock import patch
import unittest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from g2b_workflow_ops import next_step, router

BID="R26BK01787028"
OFFICIAL={"bid_no":BID,"bid_ord":"000","original_notice_verified":True,
          "official_detail10":["8111159901"]}
DOCS_OK={"files_listed":3,"files_downloaded":3,
         "all_listed_files_obtained":True,
         "all_documents_text_extracted":True}


class PlannerRules(unittest.TestCase):
    def test_missing_key_cannot_automatically_claim_official_original(self):
        context={**OFFICIAL,"original_notice_verified":False}
        step=next_step(context,set(),{},False)
        self.assertEqual(step["status"],"blocked")
        self.assertIsNone(step["feature_no"])

    def test_official_notice_is_the_first_action_when_api_available(self):
        context={**OFFICIAL,"original_notice_verified":False}
        step=next_step(context,set(),{},True)
        self.assertEqual(step["feature_no"],1)
        self.assertEqual(step["status"],"actionable")

    def test_unverified_10_digit_code_blocks_history(self):
        c={**OFFICIAL,"official_detail10":[]}
        step=next_step(c,set(),DOCS_OK,True)
        self.assertEqual(step["status"],"blocked")
        self.assertEqual(step["group"],"detail")

    def test_unlisted_attachments_are_not_assumed_empty_or_complete(self):
        step=next_step(OFFICIAL,set(),{},True)
        self.assertEqual(step["status"],"blocked")
        self.assertIn("attachment_index",step["required"])

    def test_binary_files_and_extracted_text_are_separate_gates(self):
        docs={**DOCS_OK,"all_listed_files_obtained":False}
        step=next_step(OFFICIAL,set(),docs,True)
        self.assertEqual(step["feature_no"],29)
        docs={**DOCS_OK,"all_documents_text_extracted":False}
        step=next_step(OFFICIAL,set(),docs,True)
        self.assertEqual(step["feature_no"],31)

    def test_10_year_missing_coverage_remains_an_actionable_partial_batch(self):
        step=next_step(OFFICIAL,{"opening_evidence","award_evidence"},DOCS_OK,True)
        self.assertEqual(step["feature_no"],50)
        self.assertEqual(step["full_ten_year_complete_not_assumed"],True)

    def test_manual_eligibility_quotes_and_signoff_are_not_queued(self):
        evidence={"outcome_10years_complete"}
        step=next_step(OFFICIAL,evidence,DOCS_OK,True)
        self.assertEqual(step["status"],"manual_input_required")
        evidence |= {"requirements","company_registration","qualification_evaluation"}
        step=next_step(OFFICIAL,evidence,DOCS_OK,True)
        self.assertEqual(step["status"],"manual_input_required")
        self.assertEqual(step["group"],"pricing")
        evidence |= {"verified_base_amount","price_rules","supplier_quotes","cost_breakdown"}
        step=next_step(OFFICIAL,evidence,DOCS_OK,True)
        self.assertEqual(step["status"],"manual_review_required")


class PlannerRoutes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app=FastAPI()
        app.include_router(router)
        cls.client=TestClient(app)

    def plan(self,status="actionable",feature=50,jobs=None):
        return {"bid_no":BID,"recommended_next":{
                    "status":status,"feature_no":feature,"group":"history",
                    "reason":"resume_exact_10_digit_10_year_outcomes"},
                "active_jobs":jobs or [],"allowed_to_enqueue":status=="actionable" and not jobs}

    def test_plan_get_uses_selected_notice(self):
        with patch("g2b_workflow_ops.workflow_plan",return_value=self.plan()):
            r=self.client.get(f"/api/g2b/cases/{BID}/workflow/plan")
        self.assertEqual(r.status_code,200)
        self.assertEqual(r.json()["recommended_next"]["feature_no"],50)

    def test_wrong_selected_case_does_not_run(self):
        r=self.client.get("/api/g2b/cases/WRONG/workflow/plan")
        self.assertEqual(r.status_code,404)

    def test_run_is_never_triggered_on_get(self):
        with patch("g2b_workflow_ops.queue_one",side_effect=AssertionError("unexpected side effect")),patch(
            "g2b_workflow_ops.workflow_plan",return_value=self.plan()):
            r=self.client.get(f"/api/g2b/cases/{BID}/workflow/plan")
        self.assertEqual(r.status_code,200)

    def test_stale_confirmation_rejected(self):
        with patch("main.guard",return_value=None),patch("g2b_workflow_ops.workflow_plan",return_value=self.plan()),patch(
            "g2b_workflow_ops.queue_one") as queued:
            r=self.client.post(f"/api/g2b/cases/{BID}/workflow/advance",
                               json={"confirm_feature_no":33})
        self.assertEqual(r.status_code,409)
        queued.assert_not_called()

    def test_running_job_prevents_competing_collector(self):
        with patch("main.guard",return_value=None),patch(
            "g2b_workflow_ops.workflow_plan",return_value=self.plan(jobs=[{"id":72,"state":"running"}])),patch(
            "g2b_workflow_ops.queue_one") as queued:
            r=self.client.post(f"/api/g2b/cases/{BID}/workflow/advance",
                               json={"confirm_feature_no":50})
        self.assertEqual(r.status_code,409)
        queued.assert_not_called()

    def test_manual_review_is_not_executable(self):
        with patch("main.guard",return_value=None),patch(
            "g2b_workflow_ops.workflow_plan",return_value=self.plan("manual_input_required",66)),patch(
            "g2b_workflow_ops.queue_one") as queued:
            r=self.client.post(f"/api/g2b/cases/{BID}/workflow/advance",
                               json={"confirm_feature_no":66})
        self.assertEqual(r.status_code,409)
        queued.assert_not_called()

    def test_only_one_confirmed_action_can_queue(self):
        response={"job_id":71,"job_status":"queued","feature_no":50,"source_bid_no":BID}
        with patch("main.guard",return_value=None),patch(
            "g2b_workflow_ops.workflow_plan",return_value=self.plan()),patch(
            "g2b_workflow_ops.queue_one",return_value=response) as queued:
            r=self.client.post(f"/api/g2b/cases/{BID}/workflow/advance",
                               json={"confirm_feature_no":50})
        self.assertEqual(r.status_code,200)
        self.assertEqual(r.json()["job_id"],71)
        self.assertFalse(r.json()["auto_execute_following_steps"])
        self.assertFalse(r.json()["submitted"])
        self.assertEqual(queued.call_count,1)


if __name__=="__main__":
    unittest.main()
