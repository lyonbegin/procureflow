"""G2B browser-origin opening-results scraper regression tests."""
import unittest
from g2b_bid_collector import normalize_id,normalize_item,configured,_final_award,ID_ONLY_RE

class G2BBidResultContracts(unittest.TestCase):
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

    def test_first_place_is_not_final_award(self):
        self.assertIsNone(_final_award({"bidPbancNm":"구매"},{}))
        self.assertIsNone(_final_award({"fnlSucsfbdCorpNm":"A사"},{}))
        self.assertEqual(_final_award({"fnlSucsfbdCorpNm":"A사",
                     "progress":"최종낙찰확정"},{}),"A사")

if __name__=="__main__":
    unittest.main()
