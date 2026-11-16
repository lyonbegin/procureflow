"""Security checks for temporary GitHub Actions Chrome login URL locator.

Only protected Cloudflare /grant URLs freshly posted by the exact repo's
workflow may be shown. No credentials appear in the HITEL landing page.
"""
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch

_temp=tempfile.TemporaryDirectory(prefix="hitel-remote-login-")
os.environ["RELAY_DATA_DIR"]=_temp.name
os.environ["PUBLIC_SMOKE_ONLY"]="1"
os.environ["WEB_SESSION_SIGNING_KEY"]="remote-login-integration-test-sufficiently-long-20261117"
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

import remote_login_landing as mod
from fastapi.testclient import TestClient
import app


class RealAccountLoginLandingTests(unittest.TestCase):
    def setUp(self):
        self.now=datetime(2026,11,17,0,0,tzinfo=timezone.utc)
        self.valid={
            "context":"hitel-two-manual-chrome-logins",
            "state":"pending",
            "target_url":"https://private-test.trycloudflare.com/grant",
            "created_at":(self.now-timedelta(minutes=2)).isoformat(),
        }

    def test_01_valid_protected_current_link_allowed(self):
        self.assertEqual(mod.verified_link(self.valid,self.now),self.valid["target_url"])

    def test_02_other_hosts_denied(self):
        for url in (
            "http://private-test.trycloudflare.com/grant",
            "https://private-test.trycloudflare.com.evil.com/grant",
            "https://other.example/grant",
            "https://private-test.trycloudflare.com/vnc.html",
            "https://private-test.trycloudflare.com/grant?code=secret",
            "https://user:password@private-test.trycloudflare.com/grant",
        ):
            entry=dict(self.valid,target_url=url)
            self.assertIsNone(mod.verified_link(entry,self.now),url)

    def test_03_expired_or_success_status_denied(self):
        self.assertIsNone(mod.verified_link(
            dict(self.valid,created_at=(self.now-timedelta(hours=1)).isoformat()),self.now))
        self.assertIsNone(mod.verified_link(dict(self.valid,state="success"),self.now))
        self.assertIsNone(mod.verified_link(dict(self.valid,context="other"),self.now))

    def test_04_landing_page_and_link_api_work_without_login_credentials(self):
        with TestClient(app.app,base_url="https://testserver") as client:
            response=client.get("/remote-login")
            self.assertEqual(response.status_code,200)
            self.assertIn("ChatGPT 계정 2개",response.text)
            self.assertNotIn("type=\"password\"",response.text)
            self.assertNotIn("Google 비밀번호를 입력",response.text)
            with patch.object(mod,"_cache",{"until":mod.time.monotonic()+30,
                                            "value":{"ready":True,
                                                "workflowUrl":mod.WORKFLOW_URL,
                                                "remoteUrl":self.valid["target_url"]}}):
                status=client.get("/web/api/remote-login/status")
            self.assertEqual(status.status_code,200)
            self.assertTrue(status.json()["ready"])


if __name__=="__main__":
    unittest.main()
