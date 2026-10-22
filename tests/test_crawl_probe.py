"""Offline unit tests for crawl URL matching and record extraction."""
import unittest
from tools.crawl_probe import recognized,parse_record,redact,SITES

class CrawlProbeTests(unittest.TestCase):
    def test_all_sites_have_three_sections(self):
        for site in ("wishket","freemoa","wanted"):
            self.assertEqual(set(SITES[site]),{"projects","partners","portfolios"})
    def test_wishket_projects(self):
        self.assertTrue(recognized("wishket","projects","https://www.wishket.com/project/159219/"))
        self.assertFalse(recognized("wishket","projects","https://www.wishket.com/project/"))
    def test_wishket_partners_and_portfolios(self):
        self.assertTrue(recognized("wishket","partners","https://www.wishket.com/partners/p/sampledev/"))
        self.assertTrue(recognized("wishket","portfolios","https://www.wishket.com/partners/wishket-portfolio/308430/"))
    def test_freemoa_mobile_project(self):
        u="https://m.freemoa.net/m4/s41?pno=41284"
        self.assertTrue(recognized("freemoa","projects",u))
        self.assertFalse(recognized("freemoa","projects","https://www.freemoa.net/m4/s41"))
        self.assertFalse(recognized("freemoa","projects","https://www.freemoa.net/m4/regProject"))
        rec=parse_record("freemoa","projects",u,"Sample","예산: 300만원")
        self.assertEqual(rec["source_id"],"41284")
    def test_freemoa_partner(self):
        u="https://www.freemoa.net/m7/freelance_detail?fno=37837"
        self.assertTrue(recognized("freemoa","partners",u))
        self.assertEqual(parse_record("freemoa","partners",u,"Developer","abc")["source_id"],"37837")
    def test_wanted(self):
        self.assertTrue(recognized("wanted","projects","https://www.wanted.co.kr/gigs/projects/14181"))
        self.assertTrue(recognized("wanted","partners","https://www.wanted.co.kr/gigs/premium/52474"))
        self.assertFalse(recognized("wanted","projects","https://gigs.wanted.co.kr/gigs/projects/14181"))
    def test_redaction_and_fields(self):
        rec=parse_record("wishket","projects","https://www.wishket.com/project/159219/","test",
             "예산: 3,000,000원\n고객사: ABC 주식회사\n연락처: 010-1234-5678\n이메일: abc@example.com")
        self.assertEqual(rec["fields"]["budget"],"3,000,000원")
        self.assertEqual(rec["fields"]["customer"],"ABC 주식회사")
        self.assertNotIn("010-1234-5678",rec["body_excerpt"])
        self.assertNotIn("abc@example.com",rec["body_excerpt"])

if __name__=="__main__": unittest.main()
