"""G2B exact official classification code extraction contract tests.

No LLM, guessed title categories, bidder registration-number confusion,
or fuzzy 8-digit fallback in exact 10-digit searches.
"""
from g2b_categories import extract_codes, normalize_code

def test_exact_official_item10():
    data={"result":{"bidPbancNo":"R26BK01726104",
                    "dtilPrdctClsfcNo":"4110450901",
                    "prdlstClsfcNo":"41104509",
                    "prcmBsneSeCd":"조070001"}}
    x=extract_codes(data)
    assert len(x)==2
    assert {p["code_type"] for p in x}=={"detail10","parent8"}
    assert any(p["code"]=="4110450901" for p in x)

def test_no_business_registration_false_category():
    data={"pbancMap":{"bidPbancNo":"R26BK01726104",
                     "prcmBsneSeCd":"조070001"},
          "oobsRsltList":[{"ibxBzmnRegNo":"1548103787","ibxGrpNm":"X"},
                          {"ibxBzmnRegNo":"2018631018","ibxGrpNm":"Y"}]}
    assert extract_codes(data)==[]

def test_only_exact_field_and_code_format():
    assert normalize_code("dtilPrdctClsfcNo","4110450901")==("detail10","4110450901")
    assert normalize_code("bidPbancNo","4110450901") is None
    assert normalize_code("dtilPrdctClsfcNo","41104509") is None
    assert normalize_code("prdlstClsfcNo","4110450901") is None
    assert normalize_code("vendorBusinessNumber","4110450901") is None

def test_multi_codes_and_no_headline_semantics():
    x=extract_codes({"noticeName":"영상감시장치","items":[
       {"dtilPrdctClsfcNo":"4617161001"},
       {"dtilPrdctClsfcNo":"4617161002"},
       {"dtilPrdctClsfcNo":"4617161001"}]})
    assert sorted(z["code"] for z in x)==["4617161001","4617161002"]
    assert extract_codes({"bidPbancNm":"카메라 4617161001 구매"})==[]
