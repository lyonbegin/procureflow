"""Headless Chromium Google-button unit test."""
import unittest
import base64
import json
from tools.freemoa_google_login import export_session_secret,import_session_secret
from playwright.sync_api import sync_playwright
from tools.freemoa_headless_google import click_google

class HeadlessGoogleTests(unittest.TestCase):
    def test_google_button_click(self):
        with sync_playwright() as p:
            browser=p.chromium.launch(channel="chrome",headless=True,args=["--no-sandbox"])
            try:
                page=browser.new_page()
                page.set_content("<button>Google 로그인</button>")
                self.assertTrue(click_google(page))
            finally:
                browser.close()

    def test_absent_google_button(self):
        with sync_playwright() as p:
            browser=p.chromium.launch(channel="chrome",headless=True,args=["--no-sandbox"])
            try:
                page=browser.new_page()
                page.set_content("<button>일반 로그인</button>")
                self.assertFalse(click_google(page))
            finally:
                browser.close()

    def test_one_session_secret_keeps_only_freemoa(self):
        source={
            "cookies":[
                {"name":"session","domain":".freemoa.net","value":"example"},
                {"name":"sensitive_google","domain":".google.com","value":"exclude"},
                {"name":"impostor","domain":"notfreemoa.net","value":"exclude"}
            ],
            "origins":[{"origin":"https://www.freemoa.net","localStorage":[]},
                       {"origin":"https://accounts.google.com","localStorage":[]}]
        }
        encoded=export_session_secret(source)
        decoded=import_session_secret(encoded)
        self.assertEqual([c["name"] for c in decoded["cookies"]],["session"])
        self.assertEqual([o["origin"] for o in decoded["origins"]],["https://www.freemoa.net"])
        self.assertNotIn("exclude",base64.b64decode(encoded).decode())

    def test_secret_must_contain_freemoa_session(self):
        with self.assertRaises(RuntimeError):
            import_session_secret(base64.b64encode(
                json.dumps({"cookies":[],"origins":[]}).encode()).decode())

    def test_reject_invalid_base64(self):
        with self.assertRaises(RuntimeError):
            import_session_secret("not valid base64!")

if __name__=="__main__":unittest.main()
