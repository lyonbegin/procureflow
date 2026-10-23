"""Public G2B final-award evidence regressions: never infer award from rank."""
import unittest
from g2b_final_award_collector import normalized_confirmed_award


def fixture(status="입160010",winner_label="낙찰",multiple=False):
    listing={"bidPbancNo":"R26BK01782764","bidPbancOrd":"001",
             "bidClsfNo":"1","bidPrgrsOrd":"000",
             "prcmBsneSeCd":"조070001",
             "bidPbancNm":"콩콤바인 구매"}
    rows=[
      {"sfbrSlctnRsltCd":winner_label,"ibxOnbsRnkg":"2",
       "ibxGrpNm":"(주)낙찰업체","ibxBdngAmt":"108350000",
       "ibxBzmnRegNo":"1234567890"},
      {"sfbrSlctnRsltCd":"낙찰" if multiple else "",
       "ibxOnbsRnkg":"1","ibxGrpNm":"1순위업체","ibxBdngAmt":"108000000"}
    ]
    detail={"pbancMap":{"bidPbancPgstCd":status,
               "bidPbancNo":"R26BK01782764","bidPbancOrd":"001",
               "bidClsfNo":"1","bidPrgrsOrd":"000",
               "bidPbancNm":"콩콤바인 구매"},
            "oobsRsltList":rows}
    return listing,detail


class ConfirmedAwardContractTests(unittest.TestCase):
    def test_explicitly_selected_winner_even_when_not_rank_one(self):
        item=normalized_confirmed_award(*fixture())
        self.assertEqual(item["company"],"(주)낙찰업체")
        self.assertEqual(item["amount"],"108350000")
        self.assertEqual(item["rank"],"2")
        self.assertEqual(item["result_kind"],"award")
        self.assertEqual(item["result_status"],"최종낙찰확정")
        self.assertEqual(item["bid_ntce_ord"],"001")

    def test_rank_one_without_selection_must_not_be_award(self):
        self.assertIsNone(normalized_confirmed_award(*fixture(winner_label="")))

    def test_two_selected_winners_are_ambiguous_and_not_saved(self):
        self.assertIsNone(normalized_confirmed_award(*fixture(multiple=True)))

    def test_unconfirmed_progress_is_not_award(self):
        self.assertIsNone(normalized_confirmed_award(*fixture(status="개찰완료")))

    def test_same_execution_has_stable_identity(self):
        item1=normalized_confirmed_award(*fixture())
        listing,detail=fixture()
        detail["oobsRsltList"][0]["ibxGrpNm"]="다른업체"
        item2=normalized_confirmed_award(listing,detail)
        self.assertEqual(item1["record_key"],item2["record_key"])

    def test_escaped_company_names_are_readable(self):
        listing,detail=fixture()
        detail["oobsRsltList"][0]["ibxGrpNm"]="&#40;주&#41;낙찰업체"
        item=normalized_confirmed_award(listing,detail)
        self.assertEqual(item["company"],"(주)낙찰업체")


if __name__=="__main__":
    unittest.main()
