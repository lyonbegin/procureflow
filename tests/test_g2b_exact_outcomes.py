"""Never conflate a G2B notice/category 8 with a past bid/award outcome."""
from g2b_exact_outcome_history import (
    DETAIL,PARENT,CASE_BID,BEGIN,END,
    original_has_exact_code,_urls_from_mirror)

def test_selected_exact_code_not_broad_category():
    assert DETAIL=="8111159901"
    assert PARENT=="81111599"
    assert DETAIL!=PARENT
    assert (END-BEGIN).days>=3650
    assert CASE_BID=="R26BK01787028"

def test_accept_only_explicit_detail_code_in_original_attachment():
    assert original_has_exact_code(
      "입찰참가자격 직접생산확인증명서 【세부품명번호 : 8111159901】 보유 업체")
    assert not original_has_exact_code("홈페이지 구축 81111599 용역")
    assert not original_has_exact_code("다른 항목 8111159902")
    assert not original_has_exact_code("공고제목 8111159901 포함")
    assert not original_has_exact_code("세부품명번호 81111599010 잘못된 번호")

def test_original_document_link_scoped_to_same_notice_and_government_host():
    target="R26BK01753504"
    html=f'''<a href="https://www.g2b.go.kr/pn/pnp/pnpe/UntyAtchFile/downloadFile.do?bidPbancNo={target}&amp;bidPbancOrd=000&amp;fileSeq=1">원문.pdf</a>
       <a href="https://evil.example.org/pdf?bidPbancNo={target}">원문.pdf</a>
       <a href="https://www.g2b.go.kr/pn/pnp/pnpe/UntyAtchFile/downloadFile.do?bidPbancNo=R26BK01787028&amp;bidPbancOrd=000&amp;fileSeq=1">다른공고.pdf</a>'''
    links=_urls_from_mirror(html,target,"000","https://bid24.kr/b/"+target)
    assert len(links)==1 and links[0][1]=="원문.pdf"


def test_no_award_from_first_rank_without_explicit_winner(monkeypatch):
    from g2b_exact_outcome_history import _award_from_official_opening
    entry={"bid_no":"R26BK01753504","bid_ord":"000",
           "bid_info":{"bidPbancNm":"test","bidPbancPgstCdNm":"개찰완료"},
           "etc_data":{},
           "bidders":[{"grpNm":"업체A","onbsRnkg":1,"bdngAmt":"10000000"}]}
    result=_award_from_official_opening("R26BK01753504","000",entry)
    assert result["winner_confirmed"] is False
    assert result["status"]=="winner_not_confirmed_in_available_official_opening"

def test_genuine_explicit_winner_needs_amount_and_unique_match(monkeypatch):
    from g2b_exact_outcome_history import _award_from_official_opening
    import g2b_bid_collector as b
    monkeypatch.setattr(b,"_final_award",lambda info,etc:"업체A")
    empty={"bid_no":"R26BK01753504","bid_ord":"000",
           "bid_info":{},"etc_data":{},
           "bidders":[{"grpNm":"업체A","bdngAmt":""}]}
    r=_award_from_official_opening("R26BK01753504","000",empty)
    assert r["winner_confirmed"] is False
    assert r["status"]=="final_winner_exists_but_amount_not_released"
    duplicate={**empty,"bidders":[{"grpNm":"업체A"},{"grpNm":"업체A"}]}
    r=_award_from_official_opening("R26BK01753504","000",duplicate)
    assert r["status"]=="winner_name_not_unique_in_bidder_rows"
