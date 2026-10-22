"""Offline unit tests for crawl URL matching and record extraction."""
import unittest
from tools.crawl_probe import recognized,parse_record,redact,SITES,extract_freemoa_project_cards
from playwright.sync_api import sync_playwright
from tools.freemoa_google_login import filter_freemoa_state

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

    def test_freemoa_real_card_structure_without_href(self):
        # Mirrored from a user-provided /m4/s41?page=1 public listing card.
        html = """
        <ul id="projectListNew">
        <li class="proj-list-item_li_new">
          <div>
            <div class="projTitle projectInfo" data-pno="48536">
              <p class="title">온수 성능 시험장비 제어·계측 프로그램 개발 (LabVIEW)</p>
            </div>
            <div><p class="b">도급</p><p class="e">모집중</p></div>
          </div>
          <div class="projectInfo"><div>개발,디자인,기획</div></div>
          <div class="projectInfo">
             <p><span>예상비용</span><b>1,000 ~ 1,500 만원</b></p>
             <p><span>예상기간</span><b>60일</b></p>
             <p><span>지원자수</span><b>15명</b></p>
             <p><span>마감일정</span><b>D-13</b></p>
          </div>
          <div class="projectInfo"><div>시험장비 외주 프로젝트</div>
            <div><div><p><span>ram*</span><b>서울</b></p></div></div>
          </div>
        </li>
        <li class="proj-list-item_li_new">
          <div><div class="projTitle projectInfo" data-pno="48511">
             <p class="title">[상주] 녹취솔루션 구축 프로젝트 PL 인력 모집</p>
          </div><div><p class="d">기간제 상주</p><p class="e">모집중</p></div></div>
          <div class="projectInfo"><div>기획</div><p>PL</p></div>
          <div class="projectInfo">
             <p><span>월 임금</span><b>600 ~ 800 만원</b></p>
             <p><span>예상기간</span><b>210일</b></p>
          </div>
          <div class="projectInfo"><div>녹취솔루션 업체</div></div>
        </li>
        </ul>
        """
        with sync_playwright() as p:
            browser=p.chromium.launch(headless=True,args=["--no-sandbox"])
            try:
                page=browser.new_page()
                page.set_content(html)
                cards=extract_freemoa_project_cards(page)
            finally:
                browser.close()
        self.assertEqual(len(cards),2)
        self.assertEqual(cards[0]["source_id"],"48536")
        self.assertEqual(cards[0]["fields"]["budget"],"1,000 ~ 1,500 만원")
        self.assertEqual(cards[0]["fields"]["period"],"60일")
        self.assertEqual(cards[0]["fields"]["status"],"모집중")
        self.assertEqual(cards[0]["fields"]["work_type"],"도급")
        self.assertFalse(cards[0]["detail_verified"])
        self.assertEqual(cards[1]["fields"]["monthly_pay"],"600 ~ 800 만원")
        self.assertEqual(cards[1]["fields"]["work_type"],"기간제 상주")


    def test_freemoa_google_session_excludes_google_cookies(self):
        state={
            "cookies":[
                {"name":"sid","value":"x","domain":".freemoa.net","path":"/"},
                {"name":"google","value":"must-not-save","domain":".google.com","path":"/"},
                {"name":"hostile","value":"must-not-save","domain":"evilfreemoa.net","path":"/"},
                {"name":"sub","value":"y","domain":"www.freemoa.net","path":"/"},
            ],
            "origins":[
                {"origin":"https://www.freemoa.net","localStorage":[{"name":"test","value":"xyz"}]},
                {"origin":"https://accounts.google.com","localStorage":[{"name":"no","value":"secret"}]},
            ]
        }
        filtered=filter_freemoa_state(state)
        self.assertEqual([c["name"] for c in filtered["cookies"]],["sid","sub"])
        self.assertEqual([o["origin"] for o in filtered["origins"]],["https://www.freemoa.net"])

if __name__=="__main__": unittest.main()
