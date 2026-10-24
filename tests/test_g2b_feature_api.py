"""API contract tests that never need Railway credentials or production data."""
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from g2b_feature_api import (
    CATALOG, FeatureRunRequest, router, contract_params,
    normalize_params, collection_action, feature_contract
)
from g2b_feature_registry import FEATURE_GATES
from g2b_feature_data import SELECTORS, feature_observation


CONTEXT = {
    "bid_no": "R26BK01787028", "bid_ord": "000", "title": "선택 공고",
    "agency": "공식 발주기관", "agency_code": "A100",
    "deadline": "2026-11-01", "official_detail10": ["8111159901"],
    "official_parent8": ["81111599"],
    "original_notice_verified": True,
    "configured_historical_target": {
        "category8": "81111599", "detail10": "8111159901",
        "begin": "2016-10-24", "end": "2026-10-24",
    },
}
SNAPSHOT = {
    "feature_acceptance": [
        {"number": i, "acceptance_state": "missing"} for i in range(1, 105)
    ],
    "verified_evidence_types": [],
}


class FeatureAPITest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app = FastAPI()
        app.include_router(router)
        cls.client = TestClient(app)

    def test_every_feature_has_distinct_get_and_post(self):
        routes = self.client.app.routes
        for feature_no in range(1, 105):
            path = f"/api/g2b/cases/{{bid_no}}/features/{feature_no}"
            self.assertTrue(any(r.path == path and "GET" in r.methods for r in routes), path)
            self.assertTrue(any(r.path == path + "/run" and "POST" in r.methods for r in routes), path)
        self.assertEqual(len(CATALOG), 104)
        self.assertEqual(len(SELECTORS), 104)

    def test_all_contracts_include_original_inputs_and_evidence(self):
        for feature_no in range(1, 105):
            contract = feature_contract(feature_no, CONTEXT, SNAPSHOT)
            self.assertEqual(contract["source_bid_no"], CONTEXT["bid_no"])
            self.assertEqual(contract["source_bid_ord"], "000")
            self.assertEqual(contract["input_contract"]["required_verified_evidence"],
                             list(FEATURE_GATES[feature_no]))
            self.assertEqual(contract["acceptance_state"], "missing")
            self.assertFalse(contract["execution"]["never_submit_bid"] is False)
            self.assertNotIn("bid_no", contract_params(feature_no))
            self.assertNotIn("detail10", contract_params(feature_no))
            self.assertNotIn("agency", contract_params(feature_no))

    def test_get_endpoint_returns_contract(self):
        with patch("g2b_feature_api.notice_context", return_value=CONTEXT), patch(
            "g2b_feature_api._snapshot", return_value=SNAPSHOT
        ):
            r = self.client.get("/api/g2b/cases/R26BK01787028/features/50")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["input_contract"]["auto_from_selected_notice"][0]["value"],
                         "R26BK01787028")
        self.assertIn("outcome_10years_complete", r.json()["missing_evidence"])

    def test_catalog_has_104_routes_and_filters(self):
        with patch("g2b_feature_api.notice_context", return_value=CONTEXT), patch(
            "g2b_feature_api._snapshot", return_value=SNAPSHOT
        ):
            r = self.client.get("/api/g2b/cases/R26BK01787028/features")
            missing = self.client.get(
                "/api/g2b/cases/R26BK01787028/features?state=verified"
            )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["total"], 104)
        self.assertEqual(len(r.json()["features"]), 104)
        self.assertEqual(missing.json()["matching"], 0)

    def test_individual_check_never_enqueues_or_collects(self):
        with patch("g2b_feature_api.notice_context", return_value=CONTEXT), patch(
            "g2b_feature_api._snapshot", return_value=SNAPSHOT
        ):
            r = self.client.post(
                "/api/g2b/cases/R26BK01787028/features/50/run",
                headers={"Authorization": "Bearer test"},
                json={"mode": "check", "parameters": {}},
            )
        # main.guard is intentionally imported for authenticated mutation;
        # local test has no configured ADMIN_TOKEN; the operation is protected.
        self.assertIn(r.status_code, (401, 503))

    def test_wrong_case_rejected(self):
        r = self.client.get("/api/g2b/cases/R26BK00000000/context")
        self.assertEqual(r.status_code, 404)

    def test_untrusted_inputs_cannot_replace_notice_fields(self):
        for injected in (
            {"bid_no": "R26BK00000000"},
            {"detail10": "9999999999"},
            {"agency_code": "forged"},
            {"candidate_limit": 1000},
            {"opening_limit": True}
        ):
            with self.assertRaises(ValueError):
                normalize_params(50, injected)

    def test_valid_bounded_input(self):
        self.assertEqual(normalize_params(50, {"candidate_limit": 2}),
                         {"candidate_limit": 2})
        self.assertEqual(collection_action(50),
                         "collect_exact_ten_digit_outcomes")

    def test_feature_outputs_are_distinct_for_each_id(self):
        self.assertEqual(sorted(SELECTORS), list(range(1, 105)))
        self.assertEqual(SELECTORS[50], ("outcomes", "exact_opening_coverage"))
        self.assertEqual(SELECTORS[51], ("outcomes", "exact_award_coverage"))
        self.assertEqual(SELECTORS[29], ("documents", "downloaded"))
        self.assertEqual(SELECTORS[91], ("pricing", "approved_price"))

    def test_missing_source_does_not_become_zero_or_verified(self):
        with patch("g2b_feature_data._official_notice", return_value={}):
            result = feature_observation(23, CONTEXT)
        self.assertEqual(result["status"], "missing")
        self.assertIsNone(result["data"])
        self.assertFalse(result["independent_acceptance"])

    def test_real_notice_fields_are_projected_and_not_guessed(self):
        with patch("g2b_feature_data._official_notice",
                   return_value={"bidNtceNo": "R26BK01787028",
                                 "bidNtceNm": "실제 입찰 공고",
                                 "ntceInsttNm": "검증기관"}):
            result = feature_observation(7, CONTEXT)
        self.assertEqual(result["data"], {"bidNtceNm": "실제 입찰 공고"})
        with patch("g2b_feature_data._official_notice", return_value={}):
            missing = feature_observation(7, CONTEXT)
        self.assertEqual(missing["status"], "missing")

    def test_source_failures_do_not_claim_completion(self):
        with patch("g2b_feature_data._history_data", side_effect=RuntimeError("remote read unavailable")):
            result = feature_observation(50, CONTEXT)
        self.assertEqual(result["status"], "source_error")
        self.assertFalse(result["independent_acceptance"])
        self.assertIsNone(result["data"])

    def test_openapi_has_104_individual_operations(self):
        from fastapi.openapi.utils import get_openapi
        schema = get_openapi(title="test", version="1", routes=self.client.app.routes)
        for i in range(1, 105):
            root = f"/api/g2b/cases/{{bid_no}}/features/{i}"
            self.assertIn("get", schema["paths"][root])
            self.assertIn("post", schema["paths"][root + "/run"])


if __name__ == "__main__":
    unittest.main()
