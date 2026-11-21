"""JSON-only stock-tv completion decisions: no browser gates and no network."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from hitel_stocktv_json_receipt import matches_stocktv_research_json

FIRST = [
    ("02yfhjiz","Strategy A"),("03zgCMqx","Strategy B"),
    ("04erUlJM","Strategy C"),("06s9ohae","Strategy D"),
    ("06wt9GNj","Strategy E"),("06zatx1k","Strategy F"),
    ("07CF7RMb","Strategy G"),("07xDq1rh","Strategy H"),
    ("089fmfw1","Strategy I"),("08R4aSqS","Strategy J")
]

def make_prompt(batch=1, length=10):
    first=(batch-1)*10+1
    originals=[dict(source_order=first+i,script_id=s,title=t)
               for i,(s,t) in enumerate(FIRST[:length])]
    return ('실제 거래 조사입니다.\n원본:'+json.dumps(originals,ensure_ascii=False)+
            '\n필수 단일 JSON:{\"schema\":\"TV-TRADE-EVIDENCE-10-v2\",'
            '\"batch_number\":'+str(batch)+',\"research_only\":true}')


def make_answer(batch=1, length=10):
    first=(batch-1)*10+1
    return {
      "schema":"TV-TRADE-EVIDENCE-10-v2",
      "batch_number":batch,
      "research_only":True,
      "source_results":[
       {"source_order":first+i,"script_id":s,"title":t,
        "research_status":"SEARCHED","search_queries":["evidence query"],
        "cases":[],"exclusions":[],"limitations":"No verified trade"}
       for i,(s,t) in enumerate(FIRST[:length])
      ]
    }


class JSONOnlyCompletion(unittest.TestCase):
    def test_complete_json_accepted_without_any_ui_signal(self):
        self.assertTrue(matches_stocktv_research_json(json.dumps(make_answer()),make_prompt()))

    def test_complete_fenced_json_accepted(self):
        reply="```json\n"+json.dumps(make_answer())+"\n```"
        self.assertTrue(matches_stocktv_research_json(reply,make_prompt()))

    def test_partial_json_not_completed(self):
        reply=json.dumps(make_answer())
        for cut in (1,100,len(reply)//2,len(reply)-1):
            with self.subTest(cut=cut):
                self.assertFalse(matches_stocktv_research_json(reply[:cut],make_prompt()))

    def test_wrong_batch_rejected(self):
        self.assertFalse(matches_stocktv_research_json(json.dumps(make_answer(batch=2)),make_prompt()))

    def test_old_or_different_source_rejected(self):
        old=make_answer()
        old["source_results"][0]["script_id"]="ZZZZZZZZ"
        self.assertFalse(matches_stocktv_research_json(json.dumps(old),make_prompt()))

    def test_wrong_sequence_and_missing_source_rejected(self):
        bad=make_answer()
        bad["source_results"][2],bad["source_results"][3]=bad["source_results"][3],bad["source_results"][2]
        self.assertFalse(matches_stocktv_research_json(json.dumps(bad),make_prompt()))
        bad=make_answer()
        bad["source_results"].pop()
        self.assertFalse(matches_stocktv_research_json(json.dumps(bad),make_prompt()))

    def test_invalid_case_evidence_rejected(self):
        bad=make_answer()
        bad["source_results"][0]["cases"]=[{"case_type":"EXECUTED_TRADE"}]
        self.assertFalse(matches_stocktv_research_json(json.dumps(bad),make_prompt()))

    def test_not_stocktv_prompt_rejected(self):
        self.assertFalse(matches_stocktv_research_json(json.dumps(make_answer()),"Hello Scribd"))

    def test_last_batch_eight_accepted(self):
        self.assertTrue(matches_stocktv_research_json(
            json.dumps(make_answer(batch=443,length=8)),make_prompt(batch=443,length=8)))

    def test_final_batch_wrong_length_rejected(self):
        self.assertFalse(matches_stocktv_research_json(
            json.dumps(make_answer(batch=443,length=10)),make_prompt(batch=443,length=10)))

    def test_missing_or_extra_content_rejected(self):
        reply=json.dumps(make_answer())
        self.assertFalse(matches_stocktv_research_json("Here's the answer: "+reply,make_prompt()))
        self.assertFalse(matches_stocktv_research_json(reply+" more text",make_prompt()))


if __name__=="__main__":
    unittest.main()
