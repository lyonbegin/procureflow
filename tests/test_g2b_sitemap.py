"""G2B site map fallback regression without live credentials."""
import importlib.util
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location("g2b_prod_nav",ROOT/"legacy"/"g2b_prod_nav.py")
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

class Element:
    clicked=False
    def is_visible(self): return True
    def click(self,timeout=0): self.clicked=True

class Locator:
    def __init__(self,element,match):self.element=element;self.match=match
    def count(self):return 1 if self.match else 0
    def nth(self,_):return self.element

class Frame:
    url="https://www.g2b.go.kr/"
    def __init__(self):
        self.element=Element()
    def locator(self,selector):
        return Locator(self.element,'사이트맵' in selector)

class Page:
    def __init__(self):self.frames=[Frame()]

class TestG2BSitemap(unittest.TestCase):
    def test_open_visible_public_sitemap(self):
        p=Page()
        module.LAST_TRACE.clear()
        self.assertTrue(module._open_sitemap([p]))
        self.assertTrue(p.frames[0].element.clicked)
        self.assertTrue(any(row.get('step')=='sitemap_opened' for row in module.LAST_TRACE))
    def test_reject_unknown_frames(self):
        module.LAST_TRACE.clear()
        self.assertFalse(module._open_sitemap([]))
        self.assertEqual(module.LAST_TRACE[-1]['step'],'sitemap_button_not_found')
    def test_no_guess_on_private_or_api_links(self):
        self.assertIsNone(module.safe_page_url('https://another.example/'))
        self.assertIsNone(module.safe_page_url(
            'https://www.g2b.go.kr/pr/prc/prca/OderReq/selectOderReqList.do'))
if __name__=="__main__":unittest.main()
