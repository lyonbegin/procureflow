#!/usr/bin/env python3
"""No-network acceptance tests for the 3 new strategy markets and shared Studio bindings."""
import importlib.util
import json
from pathlib import Path

root=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location("procurement_node_adapter",root/"n8n/strategy-runtime/procurement_node_adapter.py")
mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
paths={
 "public":"A01-public-win-strategy.json",
 "private_dev":"B01-private-software-proposal.json",
 "staffing":"C01-staffing-service-proposal.json"}
decisions={
 "public":"HOLD_OFFICIAL_EVIDENCE",
 "private_dev":"REVIEW_FOR_CLIENT_PROPOSAL",
 "staffing":"HOLD_LEGAL_AND_REAL_STAFF_CHECK"}
for market,file in paths.items():
    path="operations/"+file
    wf=json.loads((root/"n8n/strategy-workflows"/file).read_text())
    assert wf["active"] is False
    assert wf["meta"]["simulation_only"] and wf["meta"]["never_calls_official_api"]
    assert wf["meta"]["studioDefaultInput"]==mod.ROOT_DEFAULTS[market]
    assert len(wf["nodes"])==len(mod.STEP_NAMES[market])
    assert len(wf["connections"])==len(wf["nodes"])-1
    for node in wf["nodes"]:
        bind=mod.node_binding(path,node["id"])
        assert bind==node["parameters"]["studioPython"]
        assert mod.node_type(path,node["id"])==node["type"]
        assert bind["python_module"]=="procurement_node_adapter"
    value=mod.execute_node(path,wf["nodes"][0]["id"],wf["meta"]["studioDefaultInput"])
    assert value["source_provenance"]=="fictional_test_fixture"
    assert not value["actual_job_executed"] and not value["bid_submitted"] and not value["client_contacted"]
    for i,node in enumerate(wf["nodes"][1:],2):
        value=mod.execute_node(path,node["id"],value)
        assert value["trace"][-1]["stage"]==i
        assert len(value["trace"])==i
    assert value["decision"]==decisions[market],(market,value.get("decision"))
    assert value["simulation_only"] and value["source_provenance"]=="fictional_test_fixture"
    if market=="public":
        assert value["award_history"]["ten_year_coverage_verified"] is False
        assert value["win_strategy"]["selected"]["name"]=="balanced"
        assert len(value["proposal"]["sections"])>=5
        assert not value["win_strategy"]["public_evidence_verified"]
    if market=="private_dev":
        assert value["effort"]["development_person_days"]>0
        assert value["proposal"]["quote"]["margin_pct"]>=12
    if market=="staffing":
        assert value["demand"]["job_posting_is_not_procurement"] is True
        assert value["audit"]["legal_review_missing"] is True
    print("PASS",market,"nodes",len(wf["nodes"]),"decision",value["decision"])
assert mod.node_binding("operations/PF05.json","pf05-1") is None
assert mod.node_binding("operations/A01-public-win-strategy.json","a01-99") is None
for bad in [
    {"fixture_kind":"public","scenario":"R26BK01787028","strategy_preference":"balanced"},
    {"fixture_kind":"public","scenario":"DEMO_PUBLIC_001","strategy_preference":"balanced","live_api":True}
]:
    try:mod.execute_node01(bad,workflow_kind="public")
    except ValueError:pass
    else:raise AssertionError("External/unregistered input not rejected")
try:mod.execute_node02({"source_provenance":"official","simulation_only":False},workflow_kind="public")
except ValueError:pass
else:raise AssertionError("Unsafe provenance accepted")
print("THREE_MARKET_22_APPROVED_PYTHON_NODES_MOCK_ONLY_PASS")
