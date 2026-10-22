"""Offline checks for Freemoa Google sign-in safety and browser behavior."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from playwright.sync_api import sync_playwright
from tools.freemoa_headless_google import (
    LoginStop, click_google, encrypt_state, restore_state, cipher
)

class FakeContext:
    def storage_state(self):
        return {
            "cookies":[
                {"name":"freemoa","domain":".freemoa.net","value":"sensitive-cookie","path":"/"},
                {"name":"google","domain":".google.com","value":"NEVER-SAVE","path":"/"}
            ],
            "origins":[{"origin":"https://www.freemoa.net","localStorage":[]}]
        }

class HeadlessGoogleTests(unittest.TestCase):
    def test_only_freemoa_session_encrypted(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"session.enc"
            with patch.dict(os.environ,{"FREEMOA_SESSION_ENCRYPTION_KEY":"example-test-key-with-32-characters-abcdef"}):
                encrypt_state(FakeContext(),path)
                data=path.read_bytes()
                self.assertNotIn(b"sensitive-cookie",data)
                self.assertNotIn(b"NEVER-SAVE",data)
                parsed=restore_state(path)
                self.assertEqual(len(parsed["cookies"]),1)
                self.assertEqual(parsed["cookies"][0]["name"],"freemoa")

    def test_missing_encryption_key_fails_closed(self):
        with patch.dict(os.environ,{"FREEMOA_SESSION_ENCRYPTION_KEY":""}):
            with self.assertRaises(LoginStop):cipher()

    def test_click_real_google_label_in_headless_browser(self):
        with sync_playwright() as p:
            browser=p.chromium.launch(headless=True,args=["--no-sandbox"])
            try:
                page=browser.new_page()
                page.set_content('<button onclick="document.body.dataset.clicked=\'yes\'">Google 로그인</button>')
                self.assertTrue(click_google(page))
                self.assertEqual(page.locator("body").get_attribute("data-clicked"),"yes")
            finally:
                browser.close()

if __name__=="__main__":unittest.main()
