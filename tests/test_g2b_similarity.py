"""Contract checks for true dated G2B bidder similarity; no synthetic success claims."""
from datetime import datetime, timedelta
from g2b_similarity import _auction_time, _category, _score, backtest

def make(bid, date, bidder, title="서버 유지보수 사업", category="goods", agency="기관A"):
    return [
      dict(bid_ntce_no=bid,bid_ntce_ord="000",bid_clsfc_no="0",rbid_no="000",
           title=title,agency=agency,category=category,
           result_kind="opening_status",company="",amount="",rank="",
           raw={"listing":{"onbsPrnmntDt":date,"prcmBsneSeCd":"조070001"}}),
      dict(bid_ntce_no=bid,bid_ntce_ord="000",bid_clsfc_no="0",rbid_no="000",
           title=title,agency=agency,category=category,
           result_kind="opening",company=bidder,amount="10000",rank="1",
           raw={"bidder_business_no":"1234567890"})]

def test_timestamps_only_official_opening():
    assert _auction_time("20261024073411")==datetime(2026,10,24,7,34,11)
    assert _auction_time("2026-10-24 07:34:11")==datetime(2026,10,24,7,34,11)
    assert _auction_time("not known") is None
    assert _category("조070001")=="goods"
    assert _category("조070002")=="service"

def test_category_mismatch_blocks_historical_similarity():
    t=dict(category="goods",title="서버",agency="A",date=datetime(2026,10,24))
    h=dict(category="service",title="서버",agency="A",date=datetime(2026,10,23))
    assert _score(t,h) is None

def test_strict_time_split_and_missing_date_exclusion():
    rows=[]
    for i in range(15):
        dt=(datetime(2026,1,1)+timedelta(days=i)).strftime("%Y%m%d%H%M%S")
        rows+=make("R26BK"+str(i).zfill(8),dt,"업체A" if i%2==0 else "업체B")
    # An undated future record must never be used for the historical model.
    b=make("R26BK99999999","","미래업체")
    rows+=b
    x=backtest(rows)
    assert x["coverage"]["executions_with_bidders"]==16
    assert x["coverage"]["with_official_opening_date"]==15
    assert x["coverage"]["no_official_opening_date"]==1
    assert x["status"]=="completed"
    assert x["results"]["similarity"]["evaluated_executions"]>=3
    assert x["results"]["popularity_baseline"]["evaluated_executions"]>=3

def test_missing_date_cannot_be_substituted_with_ingestion_time():
    rows=[dict(bid_ntce_no="R26BK00000001",bid_ntce_ord="000",bid_clsfc_no="0",
         rbid_no="000",title="보안제품",agency="기관",category="goods",
         result_kind="opening",company="업체X",amount="100",rank="1",
         raw={"bidder_business_no":"123"},last_seen="2026-10-24")]
    x=backtest(rows)
    assert x["status"]=="insufficient_temporal_coverage"
    assert x["coverage"]["with_official_opening_date"]==0
