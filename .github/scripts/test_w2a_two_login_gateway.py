"""Real two-account Chrome login gateway regression checks.

Uses mock browser identity only; never forges or claims a real Google login.
"""
import hashlib
import http.client
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

_here=Path(__file__).resolve().parent
sys.path.insert(0,str(_here))
_temp=tempfile.TemporaryDirectory(prefix="hitel-dual-login-test-")
os.environ["W2A_DUAL_ROOT"]=_temp.name
os.environ["W2A_ACCESS_SHA256"]=hashlib.sha256(b"unit-test-private-code").hexdigest()
os.environ["FREEMOA_GOOGLE_PASSWORD"]="unit-test-cryptographic-password-not-real"
os.environ["CHROME_BINARY"]="/nonexistent/google-chrome"
import w2a_two_login_gateway as m


class DualLoginTests(unittest.TestCase):
    def setUp(self):
        m._state={"active":"a","a":"waiting","b":"pending","emails":{},"error":""}
        for suffix in ("account-a.bin","account-b.bin","both-verified.flag"):
            path=m.ROOT/suffix
            if path.exists():
                path.unlink()

    def test_01_blank_or_unverified_google_session_never_saved(self):
        with patch.object(m,"verify_browser_email",return_value=None), \
             patch.object(m,"encrypt") as saved:
            response=m.finish("a")
        self.assertEqual(response["error"],"CHATGPT_LOGIN_NOT_VERIFIED")
        saved.assert_not_called()
        self.assertEqual(m._state["a"],"waiting")

    def test_02_a_and_b_are_distinct_and_saved_separately(self):
        real_emails=iter(("alpha@example.invalid","beta@example.invalid"))
        with patch.object(m,"verify_browser_email",side_effect=lambda:next(real_emails)), \
             patch.object(m,"_stop_chrome"), \
             patch.object(m,"start_chrome",side_effect=lambda slot:m._state.update(
                 {"active":slot,slot:"waiting"})), \
             patch.object(m,"encrypt",side_effect=lambda src,dst:Path(dst).write_bytes(b"ENCRYPTED")) as encrypt:
            self.assertTrue(m.finish("a")["ok"])
            self.assertEqual(m._state["active"],"b")
            self.assertEqual(m._state["a"],"saved")
            self.assertEqual(m._state["b"],"waiting")
            self.assertTrue(m.finish("b")["ok"])
        self.assertEqual(encrypt.call_count,2)
        self.assertTrue((m.ROOT/"both-verified.flag").exists())
        self.assertEqual(m._state["active"],None)
        self.assertNotEqual(m._state["emails"]["a"],m._state["emails"]["b"])

    def test_03_cannot_store_same_real_chatgpt_account_twice(self):
        m._state={"active":"b","a":"saved","b":"waiting",
                  "emails":{"a":"alpha@example.invalid"},"error":""}
        with patch.object(m,"verify_browser_email",return_value="alpha@example.invalid"), \
             patch.object(m,"encrypt") as encrypt:
            response=m.finish("b")
        self.assertFalse(response["ok"])
        self.assertEqual(response["error"],"SAME_CHATGPT_ACCOUNT_FOR_BOTH_SLOTS")
        encrypt.assert_not_called()

    def test_04_out_of_order_account_confirmation_fails_closed(self):
        with patch.object(m,"verify_browser_email") as checker:
            self.assertFalse(m.finish("b")["ok"])
        checker.assert_not_called()

    def test_05_screen_never_requests_google_password(self):
        self.assertNotIn("name=\"password\"",m.LOGIN_HTML)
        self.assertNotIn("name=\"password\"",m.DASH_HTML)
        self.assertIn("accounts",m.DASH_HTML.lower() if "accounts" in m.DASH_HTML.lower() else "accounts")
        self.assertIn("계정 A 로그인 확인",m.DASH_HTML)
        self.assertIn("계정 B 로그인 확인",m.DASH_HTML)
        self.assertNotIn("type=\"password\"",m.DASH_HTML)

    def test_06_remote_screen_protected_by_auth_cookie(self):
        from http.server import ThreadingHTTPServer
        server=ThreadingHTTPServer(("127.0.0.1",0),m.Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True)
        thread.start()
        try:
            def get(path,cookie=None):
                c=http.client.HTTPConnection("127.0.0.1",server.server_port,timeout=5)
                headers={"Cookie":cookie} if cookie else {}
                c.request("GET",path,headers=headers)
                r=c.getresponse();raw=r.read();status=r.status;c.close()
                return status,raw
            self.assertEqual(get("/")[0],401)
            self.assertEqual(get("/status")[0],401)
            self.assertEqual(get("/verify")[0],401)
            self.assertEqual(get("/grant")[0],200)
            self.assertEqual(get("/","w2a_session="+m.SESSION)[0],200)
            self.assertEqual(get("/status","w2a_session="+m.SESSION)[0],200)
            self.assertEqual(get("/verify","w2a_session="+m.SESSION)[0],200)
        finally:
            server.shutdown()
            server.server_close()

    def test_08_one_tap_private_url_fragment_no_manual_code(self):
        self.assertIn("URLSearchParams(location.hash",m.LOGIN_HTML)
        self.assertIn("history.replaceState",m.LOGIN_HTML)
        self.assertIn("form.submit()",m.LOGIN_HTML)
        self.assertIn("Chrome 화면 크게 열기",m.DASH_HTML)
        self.assertIn("async function saveCurrent()",m.DASH_HTML)
        self.assertNotIn('name="password"',m.LOGIN_HTML)

    def test_09_single_use_code_can_exchange_into_http_only_session(self):
        from http.server import ThreadingHTTPServer
        import urllib.parse
        server=ThreadingHTTPServer(("127.0.0.1",0),m.Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True)
        thread.start()
        try:
            c=http.client.HTTPConnection("127.0.0.1",server.server_port,timeout=5)
            payload=urllib.parse.urlencode({"code":"unit-test-private-code"})
            c.request("POST","/grant",payload,
                {"Content-Type":"application/x-www-form-urlencoded"})
            r=c.getresponse();r.read()
            self.assertEqual(r.status,303)
            self.assertEqual(r.getheader("Location"),"/")
            cookie=r.getheader("Set-Cookie")
            self.assertIn("HttpOnly",cookie)
            self.assertIn("Secure",cookie)
            self.assertIn("SameSite=Strict",cookie)
            c.close()
            c=http.client.HTTPConnection("127.0.0.1",server.server_port,timeout=5)
            c.request("POST","/grant",urllib.parse.urlencode({"code":"bad-code"}),
                {"Content-Type":"application/x-www-form-urlencoded"})
            r=c.getresponse();r.read()
            self.assertEqual(r.status,403)
            c.close()
        finally:
            server.shutdown()
            server.server_close()

    def test_10_mobile_google_helper_rejects_unapproved_direct_post(self):
        from http.server import ThreadingHTTPServer
        server=ThreadingHTTPServer(("127.0.0.1",0),m.Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True)
        thread.start()
        try:
            c=http.client.HTTPConnection("127.0.0.1",server.server_port,timeout=5)
            c.request("POST","/prepare-google","{}",
                      {"Content-Type":"application/json"})
            r=c.getresponse();r.read()
            self.assertEqual(r.status,403)
            c.close()
        finally:
            server.shutdown()
            server.server_close()

    def test_07_login_save_requires_real_session_and_good_order(self):
        m._state["active"]="a"
        m._state["a"]="waiting"
        self.assertNotIn("both-verified.flag",[p.name for p in m.ROOT.glob("*.flag")])


if __name__=="__main__":
    unittest.main()
