from g2b_case_10y import parse_8digit_notice,BEGIN,END,CASE_BID,CAT8
def test_legacy_notice_exact_cat():
    html="""<h1>통합전산시스템 구축</h1>
    <table><tr><td>공고번호</td><td>20200604893 (차수 000)</td></tr>
    <tr><td>게시일</td><td>2020-06-03 15:54</td></tr>
    <tr><td>수요기관</td><td>신용회복위원회</td></tr>
    <tr><td>사업금액</td><td>15,900,548,600원</td></tr>
    <tr><td>조달분류</td><td>정보시스템개발서비스 (81111599)</td></tr></table>"""
    row,err=parse_8digit_notice(html,"https://sujubut.com/bid/domestic/2903402/")
    assert err is None and row["notice_no"]=="20200604893"
    assert row["published_on"]=="2020-06-03"
    assert row["amount"]==15900548600

def test_current_notice_exact_cat_but_not_target():
    html="""<h1>시스템 구축</h1><table><tr><td>공고번호</td>
    <td>R26BK01730736</td></tr><tr><td>공고일시</td>
    <td>10월 1일(목) 12:00</td></tr>
    <tr><td>분류</td><td>정보시스템개발서비스 (81111599)</td></tr></table>"""
    row,err=parse_8digit_notice(html,"https://bid24.kr/b/R26BK01730736")
    assert err is None and row["notice_no"]=="R26BK01730736"
    assert row["published_on"]=="2026-10-01"

def test_other_category_rejected():
    row,reason=parse_8digit_notice("<h1>통합시스템</h1>공고번호 20200604893 (차수 000) 게시일 2020-06-03 조달분류 정보시스템개발서비스 (81111598)",
                                   "https://sujubut.com/bid/domestic/2903402/")
    assert row is None and reason=="no_explicit_81111599"

def test_horizon_and_legacy_formats():
    assert (END.year-BEGIN.year)==10
    assert CASE_BID=="R26BK01787028" and CAT8=="81111599"
    html="<h1>테스트</h1>공고번호 20160111111 (차수 000) 게시일 2016-01-01 조달분류 정보시스템개발서비스 (81111599)"
    row,reason=parse_8digit_notice(html,"https://sujubut.com/bid/domestic/5/")
    assert row is None and reason=="outside_10year_window"
