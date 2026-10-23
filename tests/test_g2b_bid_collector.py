"""Contract regressions for official G2B award/opening data adapter."""
import os
import unittest
from unittest.mock import patch
from g2b_bid_collector import (
    OPERATIONS,configured,credentials,normalize_item,parse_response,collect
)

class G2BBidResultContracts(unittest.TestCase):
    def test_bid_result_operations_are_distinct_from_announcements(self):
        self.assertEqual(OPERATIONS[("service","award")],"getScsbidListSttusServc")
        self.assertEqual(OPERATIONS[("goods","opening")],"getOpengResultListInfoThng")
        self.assertEqual(len(OPERATIONS),4)

    def test_no_key_never_claims_empty_results(self):
        with patch.dict(os.environ,{},clear=True):
            self.assertFalse(configured())
            with self.assertRaisesRegex(RuntimeError,"g2b_bid_api_key_missing"):
                credentials()
            with self.assertRaisesRegex(RuntimeError,"g2b_bid_api_key_missing"):
                collect()

    def test_official_response_and_paginated_count(self):
        data={"response":{"header":{"resultCode":"00"},
             "body":{"totalCount":2,"items":{"item":[
               {"bidNtceNo":"R26BK00000001","bidNtceNm":"미화 일반용역","sucsfbidAmt":"1200000"},
               {"bidNtceNo":"R26BK00000002","bidNtceNm":"서버 구축","sucsfbidAmt":"2300000"}
             ]}}}}
        rows,total=parse_response(data)
        self.assertEqual(total,2)
        self.assertEqual(len(rows),2)
        self.assertEqual(rows[0]["bidNtceNo"],"R26BK00000001")

    def test_api_error_is_not_zero_results(self):
        payload={"response":{"header":{"resultCode":"30","resultMsg":"invalid key"},"body":{}}}
        with self.assertRaisesRegex(RuntimeError,"g2b_bid_api_result_30"):
            parse_response(payload)

    def test_compound_execution_key_and_no_contact_fields(self):
        first={"bidNtceNo":"R26BK00123456","bidNtceOrd":"00",
               "bidClsfcNo":"01","rbidNo":"000","bidNtceNm":"입찰명",
               "sucsfbidAmt":"100000000","fnlSucsfbdCorpNm":"법인 A",
               "buyerEmail":"secret@example.org","buyerPhone":"01012345678"}
        a=normalize_item(first,"service","award","getScsbidListSttusServc",0)
        b=normalize_item({**first,"bidClsfcNo":"02"},"service","award","getScsbidListSttusServc",0)
        self.assertNotEqual(a["record_key"],b["record_key"])
        self.assertEqual(a["company"],"법인 A")
        self.assertNotIn("buyerEmail",a["raw"])
        self.assertNotIn("buyerPhone",a["raw"])

    def test_empty_genuine_response_remains_separate_from_missing_key(self):
        rows,total=parse_response({"response":{"header":{"resultCode":"00"},
                             "body":{"items":{},"totalCount":0}}})
        self.assertEqual(rows,[])
        self.assertEqual(total,0)

if __name__=="__main__":
    unittest.main()
