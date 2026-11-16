#!/usr/bin/env python3
"""Case-by-case browser login state-machine tests without private sessions."""
import unittest

from w2a_account_runtime import (
    AccountGateError, canonical_email, ensure_requested_account,
    extract_verified_email, confirmed_signed_out,
)


class SimulatedBrowser:
    def __init__(self, signed_in=None):
        self.current=signed_in
        self.logout_count=0
        self.login_count=0
        self.login_to=None
        self.refuse_logout=False

    def read(self):
        return self.current

    def logout(self):
        self.logout_count+=1
        if not self.refuse_logout:
            self.current=None

    def login(self):
        self.login_count+=1
        self.current=self.login_to

    def ensure(self, email):
        self.login_to=email
        return ensure_requested_account(
            email, read=self.read,logout=self.logout,
            open_login=self.login,login_wait_seconds=0,
        )


class ChromeLoginCases(unittest.TestCase):
    def test_first_login_new_account(self):
        browser=SimulatedBrowser()
        self.assertEqual(browser.ensure("a@example.com"),"a@example.com")
        self.assertEqual(browser.login_count,1)
        self.assertEqual(browser.logout_count,0)

    def test_repeated_messages_same_account_never_logout(self):
        b=SimulatedBrowser("a@example.com")
        for _ in range(10):
            b.ensure("A@EXAMPLE.COM")
        self.assertEqual((b.login_count,b.logout_count),(0,0))

    def test_real_sequence_a_to_b_to_a(self):
        b=SimulatedBrowser("a@example.com")
        b.ensure("a@example.com")
        b.ensure("b@example.com")
        b.ensure("b@example.com")
        b.ensure("a@example.com")
        self.assertEqual((b.login_count,b.logout_count),(2,2))
        self.assertEqual(b.current,"a@example.com")

    def test_logout_not_confirmed_stops_before_login(self):
        b=SimulatedBrowser("a@example.com")
        b.refuse_logout=True
        with self.assertRaisesRegex(AccountGateError,"ACCOUNT_LOGOUT_NOT_VERIFIED"):
            b.ensure("b@example.com")
        self.assertEqual((b.logout_count,b.login_count),(1,0))

    def test_interactive_login_required_no_false_success(self):
        b=SimulatedBrowser("a@example.com")
        b.login=lambda: setattr(b,"current",None)
        with self.assertRaisesRegex(AccountGateError,"ACCOUNT_INTERACTIVE_LOGIN_REQUIRED"):
            b.ensure("b@example.com")
        self.assertIsNone(b.current)

    def test_google_auto_login_wrong_account_blocks(self):
        b=SimulatedBrowser("a@example.com")
        b.login=lambda: setattr(b,"current","c@example.com")
        with self.assertRaisesRegex(AccountGateError,"ACCOUNT_LOGIN_WRONG_IDENTITY"):
            b.ensure("b@example.com")
        self.assertEqual(b.logout_count,1)

    def test_no_unverified_session(self):
        for x in (
            {},{"status":200,"authenticated":True,"email":""},
            {"status":401,"authenticated":True,"email":"a@example.com"},
            {"status":200,"authenticated":False,"email":"a@example.com"},
            {"status":200,"authenticated":True,"email":"oops"},
        ):
            self.assertIsNone(extract_verified_email(x))
        self.assertEqual(extract_verified_email({"status":200,"authenticated":True,
             "email":"A@Example.com"}),"a@example.com")

    def test_network_failure_never_counts_as_chatgpt_logout(self):
        for state in ({}, {"status":0,"authenticated":False,"email":None},
                      {"status":500,"authenticated":False,"email":None},
                      {"status":200,"authenticated":True,"email":"a@example.com"}):
            self.assertFalse(confirmed_signed_out(state))
        for state in ({"status":200,"authenticated":False,"email":None},
                      {"status":401,"authenticated":False,"email":None}):
            self.assertTrue(confirmed_signed_out(state))

    def test_reject_malformed_email_and_unknown_identity(self):
        for x in ("",None,"no-email","a@bad space.example","x"*255):
            with self.assertRaises(AccountGateError):
                canonical_email(x)


if __name__=="__main__":
    unittest.main()
