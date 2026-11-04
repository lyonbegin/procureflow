#!/usr/bin/env python3
"""Public original 43/104 test plus regression-only B/C prototype checks.
NO official G2B calls, official n8n runs or submissions.
"""
import importlib.util,json,sys
from pathlib import Path
root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root))
sys.path.insert(0,str(root/"n8n/strategy-runtime"))
spec=importlib.util.spec_from_file_location("procurement_node_adapter",root/"n8n/strategy-runtime/procurement_node_adapter.py")
mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
public=mod.public_case
w=json.loads((root/"n8n/strategy-workflows/A01-public-win-strategy.json").read_text())
assert not w["active"] and w["meta"]["simulation_only"] and w["meta"]["never_calls_official_api"]
assert sum(n["id"].startswith("public-") and n["id"] not in ("public-H07-native-merge","public-H07-input-gate") for n in w["nodes"])==43
assert len(w["nodes"])==45 and sum(len(a) for c in w["connections"].values() for a in c["main"])==54
assert len(public.ORDER)==43 and len(public.CATALOG)==104
assert w["meta"]["studioDefaultInput"]==public.ROOT_DEFAULT
business_nodes=[node for node in w["nodes"] if node["id"] not in ("public-H07-native-merge","public-H07-input-gate")]
for i,node in enumerate(business_nodes):
    assert node["id"]=="public-"+public.ORDER[i]
    assert mod.node_binding(public.PATH,node["id"])==node["parameters"]["studioPython"]
    assert mod.node_type(public.PATH,node["id"])==node["type"]
state=mod.execute_node(public.PATH,business_nodes[0]["id"],w["meta"]["studioDefaultInput"])
for node in business_nodes[1:]:
    state=mod.execute_node(public.PATH,node["id"],state)
assert state["business_status"]=="MOCK_COMPLETED_OFFICIAL_HOLD"
assert state["strategy_decision"]=="HOLD_OFFICIAL_EVIDENCE"
assert len(state["completed_blocks"])==43
assert set(map(int,state["feature_results"]))==set(range(1,105))
assert all(x["test_status"]=="MOCK_EXECUTED" and x["official_verified"] is False for x in state["feature_results"].values())
assert state["results"]["H07"]["mock_windows_processed"]==121
assert state["results"]["H07"]["official_windows_verified"]==0
assert state["results"]["H07"]["official_10_year_coverage_complete"] is False
assert state["results"]["P07"]["selected"]["name"]=="balanced"
assert len(state["results"]["R01"]["sections"])==6
assert state["results"]["Q05"]["eligible"] is False
assert state["results"]["O04"]["official_verified_features"]==0
assert not state["bid_submitted"] and not state["actual_job_executed"] and not state["n8n_live_execution"]
for mutate in [
 {"bid_no":"R26BK01787029"},
 {"detail10":"81111599"},
 {"fixture_id":"LIVE_G2B"},
 {"live_api":True},
]:
    inp=dict(public.ROOT_DEFAULT);inp.update(mutate)
    try:public.run_block("N01",inp)
    except ValueError:pass
    else:raise AssertionError("Unapproved input was accepted: "+str(mutate))
try: public.run_block("H01",state)
except ValueError:pass
else:raise AssertionError("Unordered replay must be denied")
print("PUBLIC_SELECTED_CASE_ORIGINAL_43_BLOCK_104_FEATURE_MOCK_E2E_PASS")
# Existing B/C remain strictly regression-tested as they were.
for market,file,decision in [
 ("private_dev","B01-private-software-proposal.json","REVIEW_FOR_CLIENT_PROPOSAL"),
 ("staffing","C01-staffing-service-proposal.json","HOLD_LEGAL_AND_REAL_STAFF_CHECK")
]:
    path="operations/"+file
    wf=json.loads((root/"n8n/strategy-workflows"/file).read_text())
    assert len(wf["nodes"])==7 and wf["meta"]["studioDefaultInput"]==mod.ROOT_DEFAULTS[market]
    out=mod.execute_node(path,wf["nodes"][0]["id"],wf["meta"]["studioDefaultInput"])
    for node in wf["nodes"][1:]:
        assert mod.node_binding(path,node["id"])==node["parameters"]["studioPython"]
        out=mod.execute_node(path,node["id"],out)
    assert out["decision"]==decision and out["bid_submitted"] is False
    print("UNCHANGED_BC_PROTOTYPE_REGRESSION_PASS",market)
assert mod.node_binding("operations/PF05.json","pf05-1") is None
print("PUBLIC_ONLY_CHANGE_43_PLUS_UNCHANGED_7_7_PASS")
