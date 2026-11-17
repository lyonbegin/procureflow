"""Regression tests for real-session multi-account Chrome registration.

Never contacts Google or ChatGPT and never produces fake real login results.
"""
import hashlib
import http.client
import os
from pathlib import Path
import shutil
import sys
import tempfile
import threading
import unittest
import urllib.parse
from unittest.mock import patch

BASE=Path(__file__).resolve().parent
sys.path.insert(0,str(BASE))
TEMP=tempfile.TemporaryDirectory(prefix="w2a-multi-secure-tests-")
os.environ["W2A_MULTI_ROOT"]=TEMP.name
os.environ["W2A_ACCESS_SHA256"]=hashlib.sha256(b"test-private-browser-secret").hexdigest()
os.environ["FREEMOA_GOOGLE_PASSWORD"]="test-only-strong-encryption-key"
import w2a_multi_login_gateway as m


class MultiAccountTests(unittest.TestCase):
    def setUp(self):
        for x in m.ROOT.iterdir():
            if x.is_dir():
                shutil.rmtree(x)
            else:
                x.unlink()
        m.ACCOUNTS.clear()
        m.STATE.update({"active":1,"phase":"login","completed":False,"error":""})
        m.PROCESS=None

    def create_profile(self,idx):
        p=m.profile(idx)
        p.mkdir(parents=True,exist_ok=True)
        (p/"Preferences").write_text('{"dummy":"offline-test"}')
        return p

    def fake_start(self,idx):
        m.STATE.update({"active":idx,"phase":"login","error":""})

    def save(self,idx,email):
        self.create_profile(idx)
        with patch.object(m,"verify_browser_email",return_value=email), \
             patch.object(m,"stop_chrome"):
            return m.save_current()

    def test_01_no_verified_chatgpt_identity_no_profile_saved(self):
        self.create_profile(1)
        with patch.object(m,"verify_browser_email",return_value=None), \
             patch.object(m,"encrypt") as encrypted:
            r=m.save_current()
        self.assertFalse(r["ok"])
        self.assertEqual(r["error"],"CHATGPT_LOGIN_NOT_VERIFIED")
        encrypted.assert_not_called()
        self.assertFalse(m.archive(1).exists())

    def test_02_three_accounts_are_isolated_and_encrypted(self):
        for idx in (1,2,3):
            if idx>1:
                with patch.object(m,"start_chrome",side_effect=self.fake_start):
                    self.assertTrue(m.add_account()["ok"])
            self.assertTrue(self.save(idx,f"student{idx}@example.invalid")["ok"])
            self.assertTrue(m.archive(idx).read_bytes().startswith(b"W2APROF2"))
        self.assertEqual(len(m.ACCOUNTS),3)
        self.assertEqual(len(list(m.ROOT.glob("account-*.bin"))),3)
        self.assertTrue(m.complete_registration()["ok"])
        self.assertTrue((m.ROOT/"registration-complete.flag").exists())
        self.assertTrue((m.ROOT/"registry.bin").read_bytes().startswith(b"W2APROF2"))

    def test_03_duplicate_chatgpt_account_never_registered_twice(self):
        self.assertTrue(self.save(1,"one@example.invalid")["ok"])
        with patch.object(m,"start_chrome",side_effect=self.fake_start):
            self.assertTrue(m.add_account()["ok"])
        self.create_profile(2)
        with patch.object(m,"verify_browser_email",return_value="one@example.invalid"), \
             patch.object(m,"stop_chrome"), \
             patch.object(m,"encrypt") as crypt:
            r=m.save_current()
        self.assertEqual(r["error"],"ACCOUNT_ALREADY_REGISTERED")
        crypt.assert_not_called()
        self.assertFalse(m.archive(2).exists())

    def test_04_allow_one_account_to_complete(self):
        self.assertFalse(m.complete_registration()["ok"])
        self.assertTrue(self.save(1,"one@example.invalid")["ok"])
        self.assertTrue(m.complete_registration()["ok"])
        self.assertEqual(len(list(m.ROOT.glob("account-*.bin"))),1)

    def test_05_encrypted_registry_restores_accounts_on_another_run(self):
        self.assertTrue(self.save(1,"one@example.invalid")["ok"])
        with patch.object(m,"start_chrome",side_effect=self.fake_start):
            self.assertTrue(m.add_account()["ok"])
        self.assertTrue(self.save(2,"two@example.invalid")["ok"])
        self.assertTrue(m.complete_registration()["ok"])
        m.ACCOUNTS.clear()
        m.load_registry()
        self.assertEqual(m.ACCOUNTS,[{"id":1,"email":"one@example.invalid"},
                                      {"id":2,"email":"two@example.invalid"}])
        # No plaintext account registry is uploaded in the artifact set.
        self.assertFalse((m.ROOT/"registry-source"/"registry.json").exists())
        for p in m.ROOT.glob("*.bin"):
            self.assertNotIn(b"one@example.invalid",p.read_bytes())
            self.assertNotIn(b"two@example.invalid",p.read_bytes())

    def test_06_no_access_code_cannot_control_chrome(self):
        from http.server import ThreadingHTTPServer
        server=ThreadingHTTPServer(("127.0.0.1",0),m.Handler)
        t=threading.Thread(target=server.serve_forever,daemon=True);t.start()
        try:
            def call(method,path,body="{}",headers=None):
                c=http.client.HTTPConnection("127.0.0.1",server.server_port,timeout=5)
                c.request(method,path,body=body,headers=headers or {})
                r=c.getresponse();data=r.read();ans=(r.status,data,r.getheaders());c.close()
                return ans
            self.assertEqual(call("GET","/")[0],401)
            self.assertEqual(call("GET","/status")[0],401)
            self.assertEqual(call("GET","/verify")[0],401)
            self.assertEqual(call("POST","/save")[0],403)
            self.assertEqual(call("POST","/done")[0],403)
            self.assertEqual(call("POST","/add")[0],403)
            payload=urllib.parse.urlencode({"code":"test-private-browser-secret"})
            status,_,headers=call("POST","/grant",payload)
            self.assertEqual(status,303)
            cookie=dict(headers)["Set-Cookie"]
            self.assertIn("Secure",cookie)
            self.assertIn("HttpOnly",cookie)
            self.assertIn("SameSite=Strict",cookie)
        finally:
            server.shutdown();server.server_close()

    def test_07_public_source_does_not_contain_login_password_inputs(self):
        self.assertNotIn("name=\"password\"",m.DASH_HTML)
        self.assertNotIn("type=\"password\"",m.DASH_HTML)
        self.assertIn("이 계정 저장",m.DASH_HTML)
        self.assertIn("다른 계정 추가",m.DASH_HTML)
        self.assertIn("등록 마침",m.DASH_HTML)
        self.assertIn("URLSearchParams",m.LOGIN_HTML)

    def test_08_status_lists_only_masked_emails(self):
        self.assertTrue(self.save(1,"secret@example.invalid")["ok"])
        from http.server import ThreadingHTTPServer
        server=ThreadingHTTPServer(("127.0.0.1",0),m.Handler)
        t=threading.Thread(target=server.serve_forever,daemon=True);t.start()
        try:
            c=http.client.HTTPConnection("127.0.0.1",server.server_port,timeout=5)
            c.request("GET","/status",headers={"Cookie":"w2a_session="+m.SESSION})
            r=c.getresponse();raw=r.read();c.close()
            self.assertEqual(r.status,200)
            self.assertNotIn(b"secret@example.invalid",raw)
            self.assertIn("accounts",raw.decode())
        finally:
            server.shutdown();server.server_close()

    def test_09_no_complete_on_zero_profiles(self):
        self.assertFalse(m.complete_registration()["ok"])
        self.assertFalse((m.ROOT/"registration-complete.flag").exists())


if __name__=="__main__":
    unittest.main()
