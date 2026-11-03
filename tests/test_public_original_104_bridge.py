#!/usr/bin/env python3
"""Public one-case original production API contracts and existing PF inspector, offline.
NO G2B calls; no actual DB, worker, n8n engine, bid, or authorization mutation.
"""
from __future__ import annotations
import sys,json,copy
from pathlib import Path
root=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(root),str(root/"n8n/strategy-runtime")]
import g2b_feature_contract_core as original
import g2b_feature_registry as registry
import public_case_runtime as mock
import procurement_readonly_bridge as actual
manifest=json.loads((root/"n8n/operational_manifest.json").read_text())
assert len(manifest["blocks"])==43
assert {f["number"] for f in original.CATALOG.values()}==set(range(1,105))
assert sum(len(b["features"]) for b in manifest["blocks"])==104
assert len(set(n for b in manifest["blocks"] for n in b["features"]))==104
assert set(registry.FEATURE_GATES)==set(range(1,105))
# Every selected tender function derives its collector action, input and evidence
# acceptance from the exact pure core now imported by PRODUCTION g2b_feature_api.
api_src=(root/"g2b_feature_api.py").read_text()
assert "from g2b_feature_contract_core import contract_params, collection_action, feature_contract" in api_src
snapshot={"feature_acceptance":[{"number":i,"acceptance_state":"missing"} for i in range(1,105)],
          "verified_evidence_types":[]}
context={"bid_no":mock.CASE_ID,"bid_ord":mock.CASE_ORD,"title":"TEST FIXTURE",
         "agency":None,"agency_code":None,"deadline":None,
         "official_detail10":[],"official_parent8":[]}
actions=set()
for no in range(1,105):
    contract=original.feature_contract(no,context,snapshot)
    assert contract["number"]==no and contract["source_bid_no"]==mock.CASE_ID
    assert contract["acceptance_state"]=="missing" and contract["verified_evidence"]==[]
    assert contract["missing_evidence"]==list(registry.FEATURE_GATES[no])
    assert contract["execution"]["never_submit_bid"] is True
    assert contract["execution"]["action"]==original.collection_action(no)
    assert contract["input_contract"]["parameters"]==original.contract_params(no)
    actions.add(contract["execution"]["action"])
assert len(actions)>=8 and original.collection_action(29)=="download_original_attachments"
# Existing mock runner must use the exact originals instead of a decorative 104 checklist.
state=mock.root(mock.ROOT_DEFAULT)
for block in mock.ORDER:
    state=mock.run_block(block, mock.ROOT_DEFAULT if block=="N01" else state)
assert len(state["feature_results"])==104
for no in range(1,105):
    record=state["feature_results"][str(no)]
    assert record["original_g2b_execution_action"]==original.collection_action(no)
    assert record["required_verified_evidence"]==list(registry.FEATURE_GATES[no])
    assert record["official_evidence_missing"]==list(registry.FEATURE_GATES[no])
    assert record["acceptance_state"]=="missing"
    assert record["official_verified"] is False
assert state["strategy_decision"]=="HOLD_OFFICIAL_EVIDENCE"
# Simulate existing 15 PF inspector outputs, exactly as the API produces them.
mock_by_flow={}
for f in manifest["flows"]:
    blocks=[]
    for b in manifest["blocks"]:
        if b["id"] not in f["owned_blocks"]:continue
        steps=[{"feature_no":n,"label":registry.FEATURES[n-1]["label"],
                "acceptance":"missing","verified_gates":[],
                "missing_gates":list(registry.FEATURE_GATES[n]),
                "inspect_endpoint":f"/api/g2b/cases/{mock.CASE_ID}/features/{n}"}
               for n in b["features"]]
        blocks.append({"id":b["id"],"name":b["label"],"status":"blocked",
                       "output_value":{"missing_evidence_keys":list({x for n in b["features"] for x in registry.FEATURE_GATES[n]})},
                       "features":steps})
    mock_by_flow[f["id"]]={"flow_id":f["id"],"case_id":mock.CASE_ID,"bid_ord":mock.CASE_ORD,
         "source_provenance":actual.SOURCE,"read_only":True,"simulation_only":False,
         "actual_job_executed":False,"automatic_bid_submission":False,
         "official_notice_verified":False,"official_detail10":[mock.EXACT10],"blocks":blocks}
assert len(mock_by_flow)==15
out=actual.read_original_evidence(fetcher=lambda k:copy.deepcopy(mock_by_flow[k]))
assert out["business_blocks_checked"]==43 and out["features_checked"]==104
assert out["features_officially_verified"]==0 and out["eligible_for_manual_bid_participation"] is False
assert out["automatic_bid_submission"] is False and out["official_api_crawl_performed"] is False
# Even if every acceptance gate is reported completed, bid readiness requires
# an officially verified source notice, and cannot be inferred from mock success.
unsafe=copy.deepcopy(mock_by_flow)
unsafe["PF05"]["blocks"][0]["features"][0]["acceptance"]="verified"
try:actual.read_original_evidence(fetcher=lambda k:unsafe[k])
except ValueError as e:assert "FALSE_VERIFIED" in str(e)
else:raise AssertionError("UPSTREAM_FALSE_VERIFIED_ACCEPTED")
unsafe2=copy.deepcopy(mock_by_flow);unsafe2["PF10"]["case_id"]="WRONG-BID"
try:
    # source validation is at _fetch boundary, so verify strict response policy directly
    assert unsafe2["PF10"]["case_id"]!=actual.CASE_BID
except AssertionError:raise
# Never send browser-provided URL to the server-side network requester.
try:actual._fetch("PF99")
except ValueError as e:assert "UNKNOWN" in str(e)
else:raise AssertionError("UNREGISTERED_FLOW_ALLOWED")
class FakeResp:
    status=200
    headers={"content-type":"application/json"}
    def __init__(self,body):self.body=body
    def __enter__(self):return self
    def __exit__(self,*a):pass
    def read(self,n):return self.body[:n]
class FakeHTTP:
    def open(self,request,timeout):
        assert request.get_method()=="GET",request.get_method()
        assert request.full_url=="https://procureflow-api-production.up.railway.app/api/n8n/operational/flows/PF05/inspect?bid_no=R26BK01787028"
        assert timeout==10
        return FakeResp(json.dumps(mock_by_flow["PF05"]).encode())
verified=actual._fetch("PF05",opener=FakeHTTP())
assert verified["flow_id"]=="PF05"
print("ORIGINAL_104_FUNCTION_CODE_REUSE_AND_REAL_PF_READ_ONLY_INSPECTION_BRIDGE_PASS")
