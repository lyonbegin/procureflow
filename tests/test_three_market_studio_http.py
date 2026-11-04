#!/usr/bin/env python3
"""End-to-end live HTTP to local shared Studio using ONLY synthetic fixtures."""
import http.cookiejar, json, os, urllib.request, urllib.error
from urllib.parse import urlencode
base=os.environ.get("STUDIO_BASE","http://127.0.0.1:3031").rstrip("/")
jar=http.cookiejar.CookieJar()
client=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
names=["A01-public-win-strategy","B01-private-software-proposal","C01-staffing-service-proposal"]
expected=["HOLD_OFFICIAL_EVIDENCE","REVIEW_FOR_CLIENT_PROPOSAL","HOLD_LEGAL_AND_REAL_STAFF_CHECK"]
def request(method,path,body=None,header=None):
    data=json.dumps(body).encode() if body is not None else None
    req=urllib.request.Request(base+path,data=data,method=method,
        headers={**({"Content-Type":"application/json"} if data else {}),**(header or {})})
    with client.open(req,timeout=20) as r:return r.status,json.load(r)
status,health=request("GET","/api/studio/health")
assert status==200 and health["projectAdapterConnected"] is True and not health["executionEnabled"]
run_ids=[]
for name,verdict in zip(names,expected):
    path="operations/"+name+".json"
    _,result=request("GET","/api/studio/workflows/"+path)
    wf=result["workflow"]
    assert result["version"]==0 and wf["active"] is False
    steps=wf["nodes"]
    status,res=request("POST","/api/studio/node01/execute",
        {"workflow":path,"node_id":steps[0]["id"],"input_json":wf["meta"]["studioDefaultInput"]},
        {"X-Studio-Node-Run":"N01"})
    assert status==200 and res["status"]=="SUCCESS",res
    assert res["engine"]=="python" and res["n8n_workflow_started"] is False
    workflow_run_id=res["workflow_run_id"]
    run_ids.append(workflow_run_id)
    upstream=res["run_id"]
    for node in steps[1:]:
        status,r=request("POST","/api/studio/nodes/execute",
            {"workflow":path,"node_id":node["id"],"source_run_id":upstream},
            {"X-Studio-Node-Run":"APPROVED"})
        assert status==200 and r["status"]=="SUCCESS",r
        assert r["workflow_run_id"]==workflow_run_id
        upstream=r["run_id"]
        res=r
    output=res["output_json"]
    assert (output.get("strategy_decision") if name.startswith("A01") else output.get("decision"))==verdict
    assert output["source_provenance"]=="fictional_test_fixture"
    if name.startswith("A01"):
        assert len(steps)==43
        assert len(output["feature_results"])==104
        assert len(output["completed_blocks"])==43
        assert output["results"]["H07"]["mock_windows_processed"]==121
        assert not output["results"]["H07"]["official_10_year_coverage_complete"]
        assert output["results"]["P07"]["selected"]["name"]=="balanced"
        assert output["results"]["O04"]["official_verified_features"]==0
    assert res["output_json"]["bid_submitted"] is False
    _,history=request("GET","/api/studio/nodes/history?"+urlencode({"workflow":path,"node_id":steps[-1]["id"]}))
    assert history["executions"],history
    _,graph=request("GET","/api/studio/nodes/graph-state?"+urlencode({"workflow":path}))
    assert graph,graph
    print("STUDIO_PYTHON_NODE_HTTP_PASS",name,"stages",len(steps),"final",verdict,flush=True)
_,dashboard=request("GET","/api/procurement/console/status")
assert dashboard["status"]=="ok" and dashboard["scope"]=="this_browser_session"
assert dashboard["metrics"]["workflow_runs"]==3,dashboard
assert dashboard["metrics"]["node_runs"]==57,dashboard
assert dashboard["metrics"]["edge_transfers"]==54,dashboard
assert len(dashboard["recent_runs"])==3,dashboard
for run_id in run_ids:
    _,trace=request("GET","/api/procurement/console/run?workflow_run_id="+run_id)
    assert trace["workflow_run_id"]==run_id and trace["simulation_only"]
    assert not trace["actual_n8n_execution"]
    assert all(x["input_json"] and x["output_json"] for x in trace["nodes"])
print("PROCUREMENT_CONSOLE_SQLITE_COUNTS_AND_THREE_RUN_TRACES_PASS")
print("PUBLIC_ORIGINAL_43_AND_UNCHANGED_BC_7_7_HTTP_PASS_57_NODES_NO_CRAWL")
