"""Stage-1 N01/N02: real source contract, identifier fidelity and branch safety."""
import importlib.util
from pathlib import Path
from unittest.mock import patch

p=Path(__file__).resolve().parents[1]/"n8n/strategy-runtime/procurement_live_gateway.py"
spec=importlib.util.spec_from_file_location("procurement_live_gateway",p)
g=importlib.util.module_from_spec(spec)
spec.loader.exec_module(g)
source={"source":"actual_procureflow_postgresql_g2b_notices","items":[
 {"bid_no":"R26BK01787028","bid_ord":"000","title":"A","agency":"기관","notice_date":"2026-10-22","deadline":"2026-10-29","can_run_full_evidence":True},
 {"bid_no":"R26BK01787028","bid_ord":"000","title":"A","agency":"기관"},
 {"bid_no":"R26BK01788888","bid_ord":"001","is_amended":True},
 {"bid_no":"R26BK01799999","bid_ord":"000","is_cancelled":True},
 {"bid_no":"R26BK01777777","bid_ord":"000","is_new":True}
],"total":4}
def fake_request(path,**kw):
 assert path.startswith("/api/g2b/public/notices?")
 return 200,source
with patch.object(g,"_request",side_effect=fake_request):
 status,r=g.proxy_get("stage1","status=all&limit=30&offset=0&q=")
 assert status==200
 assert r["source"]=="actual_procureflow_postgresql_g2b_notices"
 assert r["crawler_executed"] is False and r["worker_executed"] is False
 assert [x["id"] for x in r["nodes"]]==["N01","N02"]
 n01,n02=r["nodes"]
 assert n01["output"]["records"]==source["items"]
 assert n02["input"]["records"]==n01["output"]["records"]
 assert n02["output"]["unique_count"]==4
 assert n02["output"]["duplicate_rows_filtered"]==1
 assert n02["output"]["branches"]=={"new":1,"amended":1,"cancelled":1,"unknown_unverified":1}
 assert n02["output"]["tender_identifiers"][0]["bid_no"]=="R26BK01787028"
 assert len(r["connections"])==5
bad={**source,"source":"mock"}
with patch.object(g,"_request",return_value=(200,bad)):
 try:g.proxy_get("stage1","")
 except ValueError as e:assert str(e)=="STAGE1_REQUIRES_ACTUAL_POSTGRESQL_NOTICES"
 else:raise AssertionError("mock source accepted")
print("STAGE1_N01_N02_REAL_SOURCE_IO_BRANCH_CONTRACT_PASS")
