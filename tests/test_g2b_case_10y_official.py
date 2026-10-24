from g2b_case_10y_official import _category_from,_parse
def test_only_official_numeric_category_value():
    assert _category_from({"prdctClsfcNo":"81111599"}) is True
    assert _category_from({"dtilPrdctClsfcNo":"8111159901"}) is True
    assert _category_from({"prdctClsfcNo":"81112299"}) is False
    assert _category_from({"bidNtceNm":"정보시스템개발서비스 81111599"}) is None

def test_pagination_envelope():
    body={"response":{"header":{"resultCode":"00","resultMsg":"NORMAL SERVICE."},
                      "body":{"totalCount":2,"items":[{"bidNtceNo":"20240924109"},
                                                         {"bidNtceNo":"20240913450"}]}}}
    result,total=_parse(body)
    assert len(result)==2 and total==2
