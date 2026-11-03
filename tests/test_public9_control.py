"""Verify public9 live gateway whitelisting and real Worker authorization.
All backend values in this test are isolated HTTP stubs, not deployed records.
"""
import sys
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"n8n/strategy-runtime"))
import procurement_live_gateway as g

calls=[]
def local_backend(path,method="GET",body=None,token=None,**kw):
    calls.append((path,method,body,token))
    return 202 if method=="POST" else 200, {
      "source":"actual_procureflow_postgresql_g2b_notices",
      "items":[],"job_id":1728,"worker_source":"g2b_public_prepare",
      "bid_submitted":False}
with patch.object(g,"_request",side_effect=local_backend):
    s,data=g.proxy_get("notices","status=all&limit=10&q=SW&offset=0")
    assert s==200 and data["items"]==[]
    assert calls[-1][0]=="/api/g2b/public/notices?q=SW&status=all&limit=10&offset=0"
    assert g.proxy_get("latest")[0]==200
    assert g.proxy_get("job/1728")[0]==200
    assert g.proxy_get("catalog")[1]["business_nodes"]==9
    assert g.proxy_get("catalog")[1]["native_n8n_execution_connected"] is False
    req={"bid_no":"R26BK01787028","detail10":"8111159901",
       "start":"2016-10-24","end":"2026-10-22","agency":""}
    status,res=g.start_real_case(req,"Bearer a-valid-admin-secret-token")
    assert status==202 and res["worker_source"]=="g2b_public_prepare"
    assert calls[-1][1]=="POST"
    assert calls[-1][3]=="a-valid-admin-secret-token"
    assert "bid_no" not in calls[-1][2]
    assert calls[-1][2]["detail10"]=="8111159901"
    for invalid in ("../../admin","job/0","job/a","notices/more","job/01",""):
        try:g.proxy_get(invalid)
        except ValueError:pass
        else:raise AssertionError("unregistered read route "+invalid)
    for invalid in ("status=all&evil=y","limit=9999","status=delete","q=abc%0Adef"):
        try:g.proxy_get("notices",invalid)
        except ValueError:pass
        else:raise AssertionError("unexpected filter "+invalid)
    for bad in ({**req,"bid_no":"R26BK99999999"},
                {**req,"detail10":"8111159902"},
                {**req,"end":"2026-11-03"},
                {**req,"extra":"force_submit"}):
        try:g.start_real_case(bad,"Bearer a-valid-admin-secret-token")
        except ValueError:pass
        else:raise AssertionError("invalid bid request accepted")
    try:g.start_real_case(req,None)
    except ValueError:pass
    else:raise AssertionError("unknown user queued real worker")
import json
wf=json.loads((Path(__file__).resolve().parents[1]/
  "n8n/strategy-workflows/PF00-public-nine-real.json").read_text())
real=wf["nodes"]
assert len(real)==10
assert len([n for n in real if n["id"].startswith("public9-0")])==9
assert wf["meta"]["simulation_only"] is False
assert wf["meta"]["read_only_workflow"] is True
assert wf["meta"]["native_n8n_verified"] is False
assert all("httpRequest" in n["type"] or n["type"]=="n8n-nodes-base.code"
           for n in real[1:])
assert all("g2b" in n["parameters"].get("url","g2b")
           for n in real[1:])
print("REAL_G2B_NEWEST_LIST_NINE_NODE_EDITOR_AND_ADMIN_ONLY_WORKER_QUEUE_CONTRACT_PASS")
