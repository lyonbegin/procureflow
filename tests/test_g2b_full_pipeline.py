"""Contracts for 104-step case pipeline. No fabricated live success in tests."""
import io
import zipfile
from g2b_feature_registry import FEATURES,GROUP_BOUNDS,REQUIREMENTS
from g2b_official_notices import _items,_category_codes
from g2b_documents import extract_file,_government
from g2b_case_engine import _ready,_display_feature_state,GROUP_RANGES

def test_104_all_real_catalog_entries():
    assert len(FEATURES)==104
    assert [x["number"] for x in FEATURES]==list(range(1,105))
    assert sum(b-a+1 for a,b in GROUP_RANGES.values())==104
    assert len(REQUIREMENTS)==7

def test_official_notice_reply_handling():
    result={"response":{"header":{"resultCode":"00"},"body":{
        "totalCount":1,"items":[{"bidNtceNo":"R26BK01787028",
                                  "prdctClsfcNo":"81111599"}]}}}
    rows,n=_items(result)
    assert n==1 and rows[0]["bidNtceNo"]=="R26BK01787028"
    try:_items({"response":{"header":{"resultCode":"20","resultMsg":"no key"}}})
    except ValueError:pass
    else:raise AssertionError("official error was silently treated as success")

def test_official_codes_only_in_code_fields():
    assert any(x["code"]=="81111599" for x in
               _category_codes({"prdctClsfcNo":"81111599"}))
    assert _category_codes({"bidNtceNm":"정보시스템개발서비스 81111599"})==[]

def test_missing_evidence_never_passes_104_acceptance():
    verified,groups=_ready([])
    assert not verified
    assert all(not x["verified"] for x in groups.values())
    for f in FEATURES:
        assert _display_feature_state(f,groups,[])!="verified"

def test_document_reader_extracts_real_docx_bytes():
    f=io.BytesIO()
    with zipfile.ZipFile(f,"w") as z:
        z.writestr("word/document.xml",
          '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>원문 과업조건</w:t></w:r></w:p></w:body></w:document>')
    state,txt=extract_file("source.docx",f.getvalue())
    assert state=="parsed" and "원문 과업조건" in txt

def test_hwp_remains_unparsed():
    state,txt=extract_file("old.hwp",b"HWP Binary format")
    assert state=="binary_saved_hwp_parser_required" and not txt

def test_no_arbitrary_download_hosts():
    assert not _government("http://www.g2b.go.kr/test.pdf")
    assert not _government("https://example.com/signed.pdf")
    assert not _government("https://www.g2b.go.kr.attacker.example/f")
    assert _government("https://www.g2b.go.kr/official.pdf")
