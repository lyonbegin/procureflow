from g2b_selected_public import parse_selected_page,BID

def test_selected_bid_meta_and_genuine_document_links():
    html='''<h1>철강·금속 인공지능전환(AX)실증센터 스마트 실증장비 모니터링 시스템용 소프트웨어 개발 용역</h1>
    <p>재단법인전남테크노파크</p>
    <table><tr><td>공고번호</td><td>R26BK01787028</td></tr>
    <tr><td>공고일시</td><td>10월 22일(목) 17:53</td></tr>
    <tr><td>입찰마감</td><td>10월 29일(목) 10:00</td></tr>
    <tr><td>분류</td><td>정보시스템개발서비스 (81111599)</td></tr></table>
    <a href="https://www.g2b.go.kr/pn/pnp/pnpe/UntyAtchFile/downloadFile.do?bidPbancNo=R26BK01787028&amp;bidPbancOrd=000&amp;fileSeq=1&amp;fileType=&amp;prcmBsneSeCd=03">1. 공고문.hwp</a>
    <a href="https://evil.com/pn/pnp/pnpe/UntyAtchFile/downloadFile.do?bidPbancNo=R26BK01787028&amp;bidPbancOrd=000&amp;fileSeq=2">2. 과업지시서.hwp</a>
    '''
    x=parse_selected_page(html)
    assert x["posted"]=="2026-10-22 17:53"
    assert x["bid_deadline"]=="2026-10-29 10:00"
    assert x["category8"]=="81111599"
    assert x["file_count"]==1
    assert x["file_index"][0]["file_id"]=="official_attached_1"

def test_reject_other_code_or_wrong_notice():
    bad='<h1>철강·금속 모니터링 개발 용역</h1>공고번호 R26BK00000001 분류 정보시스템개발서비스 (81111599)'
    try:parse_selected_page(bad)
    except ValueError:pass
    else:raise AssertionError("wrong bid ID should be rejected")
