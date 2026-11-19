"""Regression: an old GitHub Actions worker cannot process new named rooms.

A 4-hour Actions worker keeps its original Python modules even when the
Railway feature branch is updated. Server must refuse old Web2API protocol
and let a newly dispatched v2 worker connect. No network or real account.
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

_temp=tempfile.TemporaryDirectory(prefix="hitel-upgrade-")
os.environ["RELAY_DATA_DIR"]=_temp.name
os.environ["WEB_SESSION_SIGNING_KEY"]="test-only-worker-upgrade-contract"
os.environ["PUBLIC_SMOKE_ONLY"]="1"
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
import app


class WorkerProtocolUpgradeTests(unittest.TestCase):
    def test_legacy_worker_without_version_rejected_without_creating_online_state(self):
        with patch.object(app,"verify_worker_identity",return_value=True):
            with TestClient(app.app) as client:
                with client.websocket_connect("/ws") as ws:
                    ws.send_json({
                        "role":"web2api","deviceId":"web2api-main",
                        "oidc_token":"synthetic-github-oidc"
                    })
                    item=ws.receive_json()
                    self.assertEqual(item["type"],"auth.error")
                    self.assertEqual(item["reason"],"WORKER_PROTOCOL_UPGRADE_REQUIRED")
                    self.assertIsNone(app.web2api_device)

    def test_version_two_worker_rejected_after_api_redeployment(self):
        with patch.object(app,"verify_worker_identity",return_value=True):
            with TestClient(app.app) as client:
                with client.websocket_connect("/ws") as ws:
                    ws.send_json({
                        "role":"web2api","deviceId":"web2api-main",
                        "oidc_token":"synthetic-github-oidc",
                        "hitel_protocol_version":2
                    })
                    item=ws.receive_json()
                    self.assertEqual(item["type"],"auth.error")
                    self.assertEqual(item["reason"],"WORKER_PROTOCOL_UPGRADE_REQUIRED")
                    self.assertIsNone(app.web2api_device)

    def test_current_worker_still_connects_without_reenrollment(self):
        with patch.object(app,"verify_worker_identity",return_value=True):
            with TestClient(app.app) as client:
                with client.websocket_connect("/ws") as ws:
                    ws.send_json({
                        "role":"web2api","deviceId":"web2api-main",
                        "oidc_token":"synthetic-github-oidc",
                        "hitel_protocol_version":3
                    })
                    item=ws.receive_json()
                    self.assertEqual(item["type"],"auth.ok")
                    self.assertIsNotNone(app.web2api_device)


if __name__=="__main__":
    unittest.main()
