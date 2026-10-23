"""G2B browser-origin opening-results scraper regression tests."""
import unittest
from g2b_bid_collector import normalize_id,normalize_item,configured,_final_award,ID_ONLY_RE

class G2BBidResultContracts(unittest.TestCase):
    def test_true_websquare_listing_page_bounds_and_execution_dedup(self):
        from g2b_bid_collector import fetch_opening_listing,LIST_URL
        class Resp:
            status=200
            def __init__(self,n):self.n=n
            def json(self):
                return {"result":{"onbsRsltClsfList":[
                    {"bidPbancNo":"R26BK01788962","bidPbancOrd":"000",
                     "bidClsfNo":"0","bidPrgrsOrd":"000",
                     "prcmBsneSeCd":"01","bidPgstCd":"입160004"}] if self.n==1 else [
                    {"bidPbancNo":"R26BK01788962","bidPbancOrd":"000",
                     "bidClsfNo":"1","bidPrgrsOrd":"000",
                     "prcmBsneSeCd":"01","bidPgstCd":"입160004"}]}}
        class API:
            def __init__(self):self.calls=[]
            def post(self,url,data,headers,timeout):
                import json
                self.calls.append((url,json.loads(data),headers))
                return Resp(len(self.calls))
        class Ctx:
            def __init__(self):self.request=API()
        ctx=Ctx()
        x=fetch_opening_listing(ctx,days=1,pages=2,max_results=20)
        self.assertEqual(len(x),1)
        self.assertEqual(x[0]["bid_no"],"R26BK01788962")
        reqs=ctx.request.calls
        self.assertEqual(reqs[0][0],LIST_URL)
        self.assertEqual(reqs[0][1]["dlSrchOnbsRsltClsfListInM"]["firstIndex"],1)
        # A full first page is required to proceed to page 2. This sample is
        # deliberately one row, so pagination must stop at the first page.
        self.assertEqual(len(reqs),1)

    def test_no_public_data_api_key_needed(self):
        self.assertTrue(configured())

    def test_actual_g2b_bid_identifiers(self):
        self.assertEqual(normalize_id("R26BK01787048-000"),("R26BK01787048","000"))
        self.assertEqual(normalize_id("R26BK01783626"),("R26BK01783626","000"))
        self.assertEqual(normalize_id("20240516360-000"),("20240516360","000"))
        self.assertIsNone(normalize_id("R26DD20902084"))
        self.assertIsNone(normalize_id("javascript:alert(1)"))

    def test_different_bidder_rows_not_merged(self):
        base={"bid_no":"R26BK01787048","bid_ord":"000","bid_name":"물품구매",
              "onbsRnkg":"1","bzmnRegNo":"0000000001","grpNm":"A사",
              "bdngAmt":"1000000","bdrt":"89.22","participant_count":"3"}
        first=normalize_item(base,"unspecified","opening","g2b_web_opening",0)
        second=normalize_item({**base,"onbsRnkg":"2","grpNm":"B사",
                               "bzmnRegNo":"0000000002"},
                              "unspecified","opening","g2b_web_opening",1)
        self.assertNotEqual(first["record_key"],second["record_key"])
        self.assertEqual(first["company"],"A사")
        self.assertEqual(first["rate"],"89.22")

    def test_verified_websquare_business_categories(self):
        from g2b_bid_collector import business_category,normalize_public_listing
        self.assertEqual(business_category("01"),"goods")
        self.assertEqual(business_category("03"),"service")
        self.assertEqual(business_category("07"),"unspecified")
        listing={"bid_no":"R26BK01787048","bid_ord":"000",
                 "bid_clsfc_no":"1","bid_progress_ord":"000",
                 "business_code":"01","status":"개찰완료",
                 "title":"실제 공고명","agency":"수요기관"}
        item=normalize_public_listing(listing)
        self.assertEqual(item["category"],"goods")
        self.assertEqual(item["agency"],"수요기관")
        self.assertEqual(item["result_kind"],"opening_status")

    def test_first_place_is_not_final_award(self):
        self.assertIsNone(_final_award({"bidPbancNm":"구매"},{}))
        self.assertIsNone(_final_award({"fnlSucsfbdCorpNm":"A사"},{}))
        self.assertEqual(_final_award({"fnlSucsfbdCorpNm":"A사",
                     "progress":"최종낙찰확정"},{}),"A사")

if __name__=="__main__":
    unittest.main()
