"""Exact 10-digit G2B server-filter search must never bulk-fetch 8-digit notices."""
from urllib.parse import parse_qs, urlsplit

from g2b_detail10_search import search_one_page, _official_response, _normalize

CODE="8111159901"
START="2016-10-24"
END="2026-10-22"


def _fake(items,total=None):
    return {"response":{"header":{"resultCode":"00"},
        "body":{"items":items,"totalCount":len(items) if total is None else total}}}


def test_exact_server_side_filter_and_source_code_provenance():
    requested=[]
    def get(url):
        requested.append(parse_qs(urlsplit(url).query))
        return _fake([
            {"bidNtceNo":"R26BK01234567","bidNtceOrd":"000",
             "bidNtceNm":"정보시스템","dtilPrdctClsfcNo":CODE,
             "ntceInsttNm":"기관A","bidNtceDt":"2026-10-12"},
            {"bidNtceNo":"R26BK01234569","bidNtceOrd":"000",
             "prdctClsfcNo":"81111599"},
        ])
    r=search_one_page(CODE,START,END,request_fn=get,key="local-fixture-key")
    assert len(requested)==1
    assert requested[0]["dtilPrdctClsfcNo"]==[CODE]
    assert "prdctClsfcNo" not in requested[0]
    assert requested[0]["inqryBgnDt"]==["202610010000"]
    assert requested[0]["inqryEndDt"]==["202610222359"]
    assert len(r["matched"])==1 and r["matched"][0]["bid_no"]=="R26BK01234567"
    assert len(r["unverified_candidates"])==1
    assert r["rejected"].get("rejected_wrong_detail10",0)==0
    assert r["next"]=={"cursor":"2026-09","page":1}
    assert r["outcome_collection_executed"] is False
    assert r["bulk_8digit_discovery"] is False
    assert r["full_history_verified"] is False


def test_full_period_is_only_filter_not_121_immediate_http_calls():
    calls=[]
    def get(url):
        calls.append(url)
        return _fake([])
    r=search_one_page(CODE,START,END,request_fn=get,key="fixture")
    assert len(calls)==1
    assert r["status"]=="partial_more_filtered_windows"
    assert r["next"]=={"cursor":"2026-09","page":1}
    assert not r["matched"]


def test_pagination_within_month_and_empty_last_month():
    payload=[{"bidNtceNo":f"R26BK{i:08d}","dtilPrdctClsfcNo":CODE}
             for i in range(100)]
    first=search_one_page(CODE,START,END,request_fn=lambda _: _fake(payload,total=120),key="fixture")
    assert first["next"]=={"cursor":"2026-10","page":2}
    second=search_one_page(CODE,START,END,cursor="2026-10",page=2,
                           request_fn=lambda _: _fake(payload[:20],total=120),key="fixture")
    assert second["status"]=="partial_more_filtered_windows"
    assert second["next"]=={"cursor":"2026-09","page":1}
    end=search_one_page(CODE,START,END,cursor="2016-10",
                        request_fn=lambda _: _fake([]),key="fixture")
    assert end["status"]=="window_range_exhausted"
    assert end["next"] is None


def test_no_key_is_explicit_blocker_without_real_call(monkeypatch):
    import g2b_detail10_search as m
    monkeypatch.setattr(m,"api_key",lambda:"")
    r=m.search_one_page(CODE,START,END,request_fn=lambda _:1)
    assert r["api_requests"]==0
    assert r["status"]=="blocked_missing_official_api_credential"
    assert r["matched"]==[]


def test_reject_api_that_ignores_detail10_server_filter():
    r=search_one_page(CODE,START,END,key="fixture",
        request_fn=lambda _: _fake([
            {"bidNtceNo":"R26BK01234567","dtilPrdctClsfcNo":CODE},
            {"bidNtceNo":"R26BK01234568","dtilPrdctClsfcNo":"8111159902"}]))
    assert r["status"]=="blocked_official_filter_not_respected"
    assert r["matched"]==[]


def test_missing_official_response_body_does_not_mean_zero_matches():
    r=search_one_page(CODE,START,END,key="fixture",
       request_fn=lambda _:{"response":{"header":{"resultCode":"00"}}})
    assert r["status"]=="source_error"
    assert r["matched"]==[]


def test_wrong_code_never_claims_match():
    status,row=_normalize({"bidNtceNo":"R26BK01234567",
                           "dtilPrdctClsfcNo":"8111159902"},CODE,"")
    assert status=="rejected_wrong_detail10" and row is None


def test_bogus_and_short_page_fail_closed():
    r=search_one_page(CODE,START,END,
       request_fn=lambda _: _fake([{"bidNtceNo":"R26BK01234567","dtilPrdctClsfcNo":CODE}],total=150),
       key="fixture")
    assert r["status"]=="blocked_truncated_official_page"
    assert r["matched"]==[]


def test_invalid_filters_rejected_before_network():
    for invalid in ("81111599","8111159902xx","abc"):
        try:
            search_one_page(invalid,START,END,key="fixture",request_fn=lambda _:None)
        except ValueError:pass
        else:raise AssertionError("Must reject "+invalid)
    try:
        search_one_page(CODE,START,END,cursor="2016-09",key="fixture")
    except ValueError:pass
    else:raise AssertionError("out-of-range month must be rejected")
