"""No-network regressions for the EXISTING WebSquare exact-ten-digit pipeline."""
import unittest
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from datetime import date
from unittest.mock import patch
import g2b_search_first as m

DATE=date(2022,1,17)
BID="20220123456"
ORD="000"

def candidate(bid_no=BID,bid_ord=ORD):
    return {"bid_no":bid_no,"bid_ord":bid_ord,"published_on":DATE}

def opening(days=0,pages=0,bid_numbers=None):
    assert bid_numbers==[BID+"-"+ORD]
    return {"status":"partial","examined":3,"saved":2,"new":1,
            "final_winners":0,"bid_details":[{"bid_no":BID,"bid_ord":ORD,"bidders":3}],
            "errors":[]}

def award_yes(no,ord_,published):
    assert (no,ord_,published)==(BID,ORD,DATE)
    return {"bid_no":no,"bid_ord":ord_,
            "status":"official_explicit_final_winner_confirmed",
            "winner_confirmed":True,"saved":1}

def selection():
    return m.filters(start="2016-10-24",end="2026-10-22",kind="all")

class WebSquareReuseTest(unittest.TestCase):
    def test_selected_websquare_reuse_and_real_final_award(self):
        attempts=[]
        with patch.object(m,"_filtered_gaps",return_value=[candidate()]), \
             patch.object(m,"_save_filtered_attempts",side_effect=lambda *a:attempts.append("opening")), \
             patch.object(m,"_save_filtered_award_attempt",side_effect=lambda *a,**k:attempts.append("award")):
            r=m.collect_filtered_gaps(selection(),max_notices=2,
                   collector=opening,award_lookup=award_yes,connection=object())
        self.assertEqual(r["selected_notice_ids"],[BID+"-"+ORD])
        self.assertEqual(r["opening_notice_ids_queried"],1)
        self.assertEqual(r["final_award_notice_ids_queried"],1)
        self.assertEqual(r["explicit_final_awards"],1)
        self.assertEqual(r["status"],"partial_source_evidence")
        self.assertEqual(r["actual_g2b_requests"],None)
        self.assertFalse(r["website_10digit_server_search_verified"])
        self.assertFalse(r["ten_year_history_complete"])
        self.assertEqual(attempts,["opening","award"])
    def test_do_not_accept_rank_1_as_final_winner(self):
        def false_winner(no,ord_,d):
            return {"bid_no":no,"bid_ord":ord_,
                    "status":"first_ranked","winner_confirmed":True}
        with patch.object(m,"_filtered_gaps",return_value=[candidate()]), \
             patch.object(m,"_save_filtered_attempts"), \
             patch.object(m,"_save_filtered_award_attempt"):
            r=m.collect_filtered_gaps(selection(),collector=opening,
                    award_lookup=false_winner,connection=object())
        self.assertEqual(r["explicit_final_awards"],0)
        self.assertEqual(r["status"],"partial_source_errors")
        self.assertIn("OFFICIAL_FINAL_AWARD_PROVENANCE_CONFLICT",r["errors"][0])
    def test_cross_bid_data_is_rejected(self):
        with patch.object(m,"_filtered_gaps",return_value=[candidate()]), \
             patch.object(m,"_save_filtered_attempts"), \
             patch.object(m,"_save_filtered_award_attempt"):
            r=m.collect_filtered_gaps(selection(),collector=opening,
              award_lookup=lambda no,ord_,d:{"bid_no":"OTHER","bid_ord":ord_,
                  "status":"official_explicit_final_winner_confirmed",
                  "winner_confirmed":True},
              connection=object())
        self.assertEqual(r["explicit_final_awards"],0)
        self.assertIn("OFFICIAL_FINAL_AWARD_IDENTITY_MISMATCH",r["errors"][0])
    def test_missing_final_is_not_claimed_award(self):
        with patch.object(m,"_filtered_gaps",return_value=[candidate()]), \
             patch.object(m,"_save_filtered_attempts"), \
             patch.object(m,"_save_filtered_award_attempt"):
            r=m.collect_filtered_gaps(selection(),collector=opening,
             award_lookup=lambda no,ord_,d:{"bid_no":no,"bid_ord":ord_,
                     "status":"official_opening_not_published","winner_confirmed":False},
             connection=object())
        self.assertEqual(r["explicit_final_awards"],0)
        self.assertEqual(r["official_award_checks"][0]["status"],"official_opening_not_published")
    def test_zero_candidates_never_calls_g2b(self):
        with patch.object(m,"_filtered_gaps",return_value=[]):
            r=m.collect_filtered_gaps(selection(),collector=lambda **k:self.fail("G2B called"),
                    award_lookup=lambda *a:self.fail("award called"),connection=object())
        self.assertEqual(r["selected"],0)
        self.assertEqual(r["actual_g2b_requests"],0)
    def test_preview_is_readonly_exposes_ids_only(self):
        with patch.object(m,"_filtered_gaps",return_value=[candidate()]):
            r=m.preview_filtered_gaps(selection(),connection=object())
        self.assertEqual(r["external_requests"],0)
        self.assertEqual(r["candidate_ids"][0]["bid_no"],BID)
        self.assertFalse(r["official_webside_10digit_search_verified"])
    def test_only_three_verified_ids_per_job(self):
        with self.assertRaisesRegex(ValueError,"MAX_THREE"):
            m.collect_filtered_gaps(selection(),max_notices=10,connection=object())
    def test_exact_ten_digit_must_match_case(self):
        with self.assertRaisesRegex(ValueError,"TEN_DIGIT"):
            m.filters(detail10="81111599")
    def test_stage04_not_marked_10yr_verified(self):
        import g2b_public_workflow as w
        result,state,summary=w._history({"source":"official_real_data",
            "exact_detail10":"8111159901",
            "summary":{"opening_rows":500,"source_notice_rounds":16},
            "websquare_enrichment":{"status":"partial_source_evidence",
                                   "opening_notice_ids_queried":2,
                                   "final_award_notice_ids_queried":2,
                                   "explicit_final_awards":1}})
        self.assertEqual(state,"partial")
        self.assertFalse(summary["ten_year_search_complete"])
        self.assertEqual(summary["real_websquare_final_award_lookups"],2)
    def test_existing_sql_has_official_exact_match_before_remote_lookup(self):
        class SQLCapture:
            def execute(self,sql,params):
                self.sql=sql
                self.params=params
                return self
            def fetchall(self):
                return []
        con=SQLCapture()
        m._filtered_gaps(con,selection(),2)
        self.assertIn("c.code_type='detail10' AND c.code=%s",con.sql)
        self.assertIn("c.evidence_level='official_direct'",con.sql)
        self.assertIn("v.status='verified_exact_10'",con.sql)
        self.assertEqual(con.params[0],"8111159901")
        self.assertNotIn("SELECT * FROM procureflow.g2b_case_10yr_history",con.sql)

if __name__=="__main__":
    unittest.main(verbosity=2)
