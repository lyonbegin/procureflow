"""No-credential, no-Worker unit contract for ProcureFlow automatic N01/N02/N04."""
from pathlib import Path
import importlib.util
import json
import sqlite3
import sys
import tempfile
import types
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"n8n/unified"))
import procurement_auto_test as target

class NoTokenAutoTest(unittest.TestCase):
    def setUp(self):
        self.workflow=json.loads((ROOT/"n8n/strategy-workflows/PF00-public-nine-real.json").read_text())
    def test_node_04_is_pinned_and_valid_without_agency(self):
        params=target.approved_filter(self.workflow)
        self.assertEqual(params["detail10"],"8111159901")
        self.assertEqual(params["kind"],"opening")
        self.assertEqual(params["agency"],"")
    def test_modified_http_url_blocked(self):
        next(n for n in self.workflow["nodes"] if n["id"]=="public9-04")["parameters"]["url"]="https://example.com/collect"
        with self.assertRaises(ValueError):
            target.approved_filter(self.workflow)
    def test_no_worker_is_ever_called(self):
        with tempfile.TemporaryDirectory() as td:
            db=Path(td)/"studio.sqlite3"
            with sqlite3.connect(db) as conn:
                conn.execute("CREATE TABLE snapshots(sid TEXT,path TEXT,payload TEXT)")
            calls=[]
            def fake_get(route,query=""):
                calls.append(("GET",route))
                if route!="stage1":raise AssertionError("Unapproved route "+route)
                return 200,{"source":"actual_procureflow_postgresql_g2b_notices",
                            "selected_route":{"selected":{"bid_no":target.CASE,"branch":"unknown_unverified"},"route":"unverified_hold"}}
            def fake_request(path,method="GET",**kwargs):
                calls.append((method,path))
                if method!="GET" or "/selected/search?" not in path:
                    raise AssertionError("Write attempted")
                return 200,{"mode":"real_one_tender_search_first","source":"existing_procureflow_postgresql","no_simulated_records":True,"bid_submitted":False,"history":{"source":"existing_procureflow_original_verified_10digit_outcomes","real_records_only":True,"total":3,"rows":[{}]}}
            fake=types.SimpleNamespace(proxy_get=fake_get,_request=fake_request,
                                       start_real_case=lambda *x,**y:(_ for _ in ()).throw(AssertionError("Real worker called")))
            old=sys.modules.get("procurement_live_gateway")
            sys.modules["procurement_live_gateway"]=fake
            try:
                result=target.run("e"*48,db,lambda x: ROOT/"n8n/strategy-workflows"/Path(x).name,
                    {"bid_no":target.CASE,"detail10":target.DETAIL})
            finally:
                if old is None:sys.modules.pop("procurement_live_gateway",None)
                else:sys.modules["procurement_live_gateway"]=old
            self.assertEqual(result["status"],"PARTIAL_READ_ONLY_VERIFIED")
            self.assertFalse(result["worker_executed"])
            self.assertFalse(result["bid_submitted"])
            self.assertEqual([c[0] for c in calls],["GET","GET"])
            self.assertEqual(len(result["verified_steps"]),3)

if __name__=="__main__":unittest.main()
