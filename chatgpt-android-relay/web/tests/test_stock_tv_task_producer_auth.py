#!/usr/bin/env python3
"""Fail-closed producer ownership tests for stock-tv; no network and no browser."""
import unittest
from unittest.mock import patch
from types import SimpleNamespace

import gh_oidc


class StockTVProducerAuth(unittest.TestCase):
    def setUp(self):
        self.claims = {
            "repository": "lyonbegin/autonomous-investor-backend",
            "repository_id": "1427623630",
            "repository_owner_id": gh_oidc.OWNER_ID,
            "ref": "refs/heads/main",
            "workflow_ref": "lyonbegin/autonomous-investor-backend/.github/workflows/stock-tv-task-isolated-research.yml@refs/heads/main",
            "event_name": "workflow_dispatch",
            "runner_environment": "github-hosted",
        }

    def verify(self, claims, task="stock-tv"):
        with patch.object(gh_oidc, "_jwk_client", return_value=SimpleNamespace(
             get_signing_key_from_jwt=lambda token: SimpleNamespace(key="test-key"))), \
             patch.object(gh_oidc.jwt, "decode", return_value=claims):
            return gh_oidc.verify_isolated_task_producer("x"*120, task)

    def test_exact_stock_tv_workflow_allowed(self):
        self.assertTrue(self.verify(self.claims))

    def test_stock_a_signed_token_cannot_submit_stock_tv(self):
        wrong = {**self.claims, "workflow_ref":
             "lyonbegin/autonomous-investor-backend/.github/workflows/stock-a-task-isolated-chrome.yml@refs/heads/main"}
        self.assertFalse(self.verify(wrong))

    def test_stock_tv_cannot_submit_other_task(self):
        self.assertFalse(self.verify(self.claims, "stock-a"))
        self.assertFalse(self.verify(self.claims, "scribd-18109"))

    def test_only_main_workflow_dispatch(self):
        for key, value in (("ref", "refs/heads/feature"),
                           ("event_name", "push"),
                           ("runner_environment", "self-hosted"),
                           ("repository_owner_id", "another")):
            with self.subTest(field=key):
                self.assertFalse(self.verify({**self.claims, key: value}))

    def test_bad_unverified_token_rejected_without_jwks(self):
        self.assertFalse(gh_oidc.verify_isolated_task_producer("bad-token", "stock-tv"))


if __name__ == "__main__":
    unittest.main()
