"""Private public supplier/portfolio full detail must not be a list-only label."""
import unittest
from private_detail_utils import parse_public_sections,validated_public_url
from freemoa_deep_collector import PARTNER_RE,PORT_RE
from wishket_collector import CUSTOMER


class FullDetailsTests(unittest.TestCase):
    def test_real_freemoa_partner_id(self):
        m=PARTNER_RE.search("https://www.freemoa.net/m7/freelance_detail?fno=1674&tab=2")
        self.assertEqual(m.group(1),"1674")
    def test_real_title_only_does_not_count_as_full(self):
        v=parse_public_sections("파트너스 목록 회사명 A")
        self.assertLess(v["body_length"],260)
    def test_tech_and_sections_preserve_public_evidence(self):
        text=("기본정보\n소프트웨어 법인\n보유기술\nReact, Python, FastAPI, MongoDB"
              "\n포트폴리오\nAI 검색 구축, 총 8개월\n경력정보\n총 6년")
        v=parse_public_sections(text)
        self.assertIn("React",v["technologies"])
        self.assertIn("Python",v["technologies"])
        self.assertIn("포트폴리오",v["sections"])
        self.assertIn("8개월",v["sections"]["포트폴리오"])
    def test_terms_modal_not_misclassified_as_profile(self):
        sample="A"*400+"제 1 조 (목적) :::\n"+"비교견적"*15000
        v=parse_public_sections(sample)
        self.assertLess(len(v["text"]),550)
    def test_customer_regex_does_not_invent_client_names(self):
        body="고객사는 긴 설명입니다\n고객사: 법인A\n발주처: 한국B"
        labels=[m.group(2).strip() for m in CUSTOMER.finditer(body)]
        self.assertEqual(labels,["법인A","한국B"])
    def test_reject_foreign_or_insecure_partner_links(self):
        self.assertTrue(validated_public_url(
             "https://www.freemoa.net/m7/freelance_detail?fno=1674","www.freemoa.net"))
        self.assertFalse(validated_public_url(
             "https://evil.net/m7/freelance_detail?fno=1674","www.freemoa.net"))


if __name__=="__main__": unittest.main()
