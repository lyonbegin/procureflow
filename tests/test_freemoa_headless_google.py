"""Headless Chromium Google-button unit test."""
import unittest
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

if __name__=="__main__":unittest.main()
