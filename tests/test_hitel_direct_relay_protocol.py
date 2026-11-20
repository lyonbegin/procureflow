"""Offline syntax/contract smoke for signed direct_http Railway protocol.

No network, database, ChatGPT send, Chrome, Railway deployment or credentials.
"""
import ast
import re
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
APP=ROOT/"chatgpt-android-relay"/"web"/"app.py"
PUBLIC=ROOT/"chatgpt-android-relay"/"web"/"integration_public.py"


class DirectRelayProtocolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source=APP.read_text(encoding="utf-8")
        cls.public=PUBLIC.read_text(encoding="utf-8")
        cls.ast=ast.parse(cls.source)

    def test_explicit_direct_transport_identity(self):
        self.assertIn('auth.get("transport","chrome")', self.source)
        self.assertIn('("direct_http", "chrome")', self.source)
        self.assertIn('web2api_transport_mode=auth.get("transport","chrome")', self.source)

    def test_http_binding_is_not_chrome_target(self):
        self.assertIn('tid=info.get("transport_id")', self.source)
        self.assertIn('re.fullmatch(r"direct-http-[a-f0-9]{28}",tid)', self.source)
        self.assertIn('tid=info.get("target_id")', self.source)
        self.assertTrue(re.fullmatch(r"direct-http-[a-f0-9]{28}",
                            "direct-http-"+"a"*28))
        self.assertFalse(re.fullmatch(r"direct-http-[a-f0-9]{28}",
                             "target-chrome-123"))

    def test_both_existing_rooms_required(self):
        self.assertIn('expected==set(ready)', self.source)
        self.assertIn('len(set(ready.values()))==len(ready)', self.source)
        self.assertIn('worker_bootstrap_ready',self.source)

    def test_original_room_ids_preserved(self):
        self.assertIn('room_e43054eed81d46fba991b946ede92d1b',self.source)
        self.assertIn('room_e31b6755688748f6a9ddb5a0f6b3cdaf',self.source)

    def test_no_secret_or_room_information_in_public_transport_status(self):
        self.assertIn('"worker_transport":web2api_transport_mode',self.public)
        self.assertNotIn('"target_id":',self.public)
        self.assertNotIn('"transport_id":',self.public)
        self.assertNotIn('"account_token":',self.public)

    def test_no_syntax_errors(self):
        ast.parse(self.source)
        ast.parse(self.public)


if __name__=="__main__":
    unittest.main(verbosity=2)
