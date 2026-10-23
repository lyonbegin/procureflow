"""Regression checks for private public-supply detail pagination and resilience."""
import inspect
import unittest

from private_supply_schedule import progress_for_result,SOURCES
from wishket_collector import collect as wishket_collect
from freemoa_deep_collector import collect as freemoa_collect


class PublicSupplyScheduleTests(unittest.TestCase):
    def test_each_source_is_a_distinct_cursored_job(self):
        self.assertEqual(set(SOURCES),{"wishket_portfolios","freemoa_partners","freemoa_portfolios"})
        self.assertIn("page_start",inspect.signature(wishket_collect).parameters)
        self.assertIn("page_start",inspect.signature(freemoa_collect).parameters)

    def test_advance_after_complete_two_pages(self):
        result={"status":"collected","saved":24,"new":12,
                "last_page":4,"has_more":True,"errors":[]}
        self.assertEqual(progress_for_result(3,result)["next_page"],5)

    def test_short_page_marks_cycle_complete(self):
        result={"status":"collected","saved":7,"last_page":4,
                "has_more":False,"errors":[]}
        step=progress_for_result(4,result)
        self.assertEqual(step["next_page"],1)
        self.assertTrue(step["cycle_complete"])

    def test_empty_page_is_not_an_error(self):
        result={"status":"empty","saved":0,"last_page":7,
                "has_more":False,"errors":[]}
        step=progress_for_result(7,result)
        self.assertEqual(step["next_page"],1)
        self.assertTrue(step["advance"])

    def test_failed_page_must_not_skip_records(self):
        result={"status":"error","saved":0,"last_page":6,
                "has_more":True,"errors":["timeout"]}
        step=progress_for_result(6,result)
        self.assertEqual(step["next_page"],6)
        self.assertFalse(step["advance"])

    def test_same_listing_at_different_numbered_page_resets_cycle(self):
        result={"status":"collected","saved":10,"last_page":3,
                "page_fingerprint":"a01","has_more":True,"errors":[]}
        step=progress_for_result(3,result,"a01")
        self.assertEqual(step["next_page"],1)
        self.assertTrue(step["repeated"])

    def test_partial_success_records_errors_but_advances(self):
        result={"status":"partial","saved":8,"last_page":2,
                "has_more":True,"errors":["one detail missing"]}
        step=progress_for_result(2,result)
        self.assertEqual(step["next_page"],3)


if __name__=="__main__":
    unittest.main()
