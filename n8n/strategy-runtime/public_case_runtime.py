"""Public tender ONE CASE offline execution on ORIGINAL 43-block/104-feature contracts.

This is not another production DAG executor. The only graph runner in production
remains official n8n. This is a selected-case, per-node test adapter for the same
shared Studio, running deterministic, fictional evidence through original manifest
block and acceptance definitions. Never access G2B, databases, web or credentials.
"""
from __future__ import annotations
from collections import Counter, defaultdict
from datetime import date
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
import copy
import json
import re
import statistics

from g2b_feature_registry import FEATURES, FEATURE_GATES, GROUP_BOUNDS, REQUIREMENTS

MANIFEST_PATH=Path(__file__).with_name("operational_manifest.json")
if not MANIFEST_PATH.is_file():
    MANIFEST_PATH=Path(__file__).resolve().parents[1]/"operational_manifest.json"
MANIFEST=json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
BLOCKS={x["id"]:x for x in MANIFEST["blocks"]}
CATALOG={int(f["number"]):f for f in FEATURES}
CASE_ID="R26BK01787028"
CASE_ORD="000"
EXACT10="8111159901"
FIXTURE_ID="PUBLIC_CASE_R26BK01787028"
PATH="operations/A01-public-win-strategy.json"
CHOICES=("balanced","quality","cost")
ROOT_DEFAULT={
 "bid_no":CASE_ID,"bid_ord":CASE_ORD,
 "detail10":EXACT10,"fixture_id":FIXTURE_ID,"strategy_preference":"balanced"
}
assert MANIFEST["engine"]=="n8n_only" and len(BLOCKS)==43
assert set(CATALOG)==set(range(1,105))
assert {v for b in BLOCKS.values() for v in b["features"]}==set(CATALOG)
assert len([v for b in BLOCKS.values() for v in b["features"]])==104

def order():
    """Deterministic test topological order, preserving the original manifest edges."""
    ids=list(BLOCKS)
    edges={(a,b) for a in ids for b in BLOCKS[a].get("to",[]) if b in BLOCKS}
    indegree={key:0 for key in ids}
    for _,dest in edges: indegree[dest]+=1
    result=[];queue=[x for x in ids if indegree[x]==0]
    while queue:
        item=queue.pop(0);result.append(item)
        for _,dst in sorted((e for e in edges if e[0]==item),key=lambda v:ids.index(v[1])):
            indegree[dst]-=1
            if indegree[dst]==0:queue.append(dst)
    if len(result)!=len(ids):raise ValueError("MANIFEST_CYCLE")
    if result[0]!="N01" or result[-1]!="O04":raise ValueError("INVALID_CASE_START_END")
    return result
ORDER=order()

def root(value):
    if not isinstance(value,dict) or set(value)!=set(ROOT_DEFAULT):
        raise ValueError("ONLY_SELECTED_PUBLIC_FIXTURE_FIELDS_ALLOWED")
    if any(value[k]!=ROOT_DEFAULT[k] for k in ("bid_no","bid_ord","detail10","fixture_id")):
        raise ValueError("UNREGISTERED_OR_NON_FIXTURE_TENDER")
    if value["strategy_preference"] not in CHOICES:
        raise ValueError("INVALID_TEST_STRATEGY")
    return {"bid_no":CASE_ID,"bid_ord":CASE_ORD,"detail10":EXACT10,
      "fixture_id":FIXTURE_ID,"strategy_preference":value["strategy_preference"],
      "source_provenance":"fictional_test_fixture","official_evidence_verified":False,
      "actual_job_executed":False,"simulation_only":True,"bid_submitted":False,
      "bid_participation_clicked":False,"n8n_live_execution":False,
      "case":{"bid_no":CASE_ID,"bid_ord":CASE_ORD,"detail10":EXACT10,
        "title":"가상 테스트용 선택 공고: 스마트 설비 모니터링 SW 개발",
        "agency":"가상 발주기관(실제 기관 정보 아님)",
        "evaluation":{"technical_weight":80,"price_weight":20},
        "budget_krw":220_000_000,"contract_type":"negotiation",
        "original_notice_verified":False,"attachment_original_verified":False},
      "results":{},"feature_results":{},"completed_blocks":[],"business_status":"MOCK_RUNNING"}

def _safe(value):
    if not isinstance(value,dict) or value.get("source_provenance")!="fictional_test_fixture":
        raise ValueError("ONLY_MOCK_UPSTREAM_PROVENANCE")
    if value.get("bid_no")!=CASE_ID or value.get("bid_ord")!=CASE_ORD or value.get("detail10")!=EXACT10:
        raise ValueError("SELECTED_CASE_CHANGED")
    if value.get("official_evidence_verified") is not False or value.get("bid_submitted") is not False:
        raise ValueError("UNSAFE_EVIDENCE_OR_BID_SUBMITTED")
    if value.get("simulation_only") is not True or value.get("actual_job_executed") is not False:
        raise ValueError("LIVE_EXECUTION_FORBIDDEN")

def _fixture_awards():
    # Deliberately fictional. Ten year time-window replay is not actual 10-year proof.
    vendors=["가상업체-가","가상업체-나","가상업체-다","가상업체-라"]
    rows=[]
    for i,year in enumerate(range(2017,2027)):
        base=160_000_000 + i*4_100_000
        bids=[{"vendor":vendors[j],"bid_krw":base+j*2_700_000+i*110_000,
          "rank":j+1} for j in range(3+(i%2))]
        winner=vendors[i%3]
        rows.append({"notice_id":f"FICTIONAL-{year}-SW-{i+1:03d}",
          "year":year,"detail10":EXACT10,"agency":"가상 발주기관(실제 기관 정보 아님)" if i%2==0 else "가상 타기관",
          "base_amount_krw":base+17_000_000,
          "bids":bids,"winner":winner,"award_amount_krw":next(x["bid_krw"] for x in bids if x["vendor"]==winner),
          "fictional":True})
    return rows

def _month_windows():
    out=[]
    for year in range(2016,2027):
        for month in range(1,13):
            if (year,month)<(2016,10) or (year,month)>(2026,10):continue
            out.append(f"{year:04d}-{month:02d}")
    assert len(out)==121
    return out

def _money(n):return int(Decimal(str(n)).quantize(Decimal("1")))

def _stage(block,state):
    case=state["case"];results=state["results"];key=block["id"]
    # Outputs are computed from the current selected case and upstream fixture;
    # original external collectors are intentionally never invoked.
    if key=="N01":return {"selected":[CASE_ID],"source":"one selected fixture","new_official_notices_collected":0}
    if key=="N02":return {"bid_no":CASE_ID,"bid_ord":CASE_ORD,"selected_cases":1,"duplicate_removed":True}
    if key=="N03":return {"case":copy.deepcopy(case),"metadata_normalized":True}
    if key=="N04":return {"revision":"000","new_amendment":False,"official_revision_verified":False}
    if key=="N05":return {"notice":copy.deepcopy(case),"source":"fictional_test_fixture","official_source_verified":False}
    if key=="N06":return {"detail10":EXACT10,"parent8":EXACT10[:8],"digits":len(EXACT10),"official_verified":False}
    if key=="N07":return {"method":case["contract_type"],"budget_krw":case["budget_krw"],
      "evaluation":case["evaluation"],"deadline":"fictional_unverified"}
    if key=="N08":return {"attachments":[{"file":"가상-RFP.txt","kind":"test_only","verified":False}]}
    if key=="N09":
        content="가상 요구: SW 개발, 2명 필수, 보안계획, 3개월 안정화"
        return {"attachments":[{"file":"가상-RFP.txt","sha256":sha256(content.encode()).hexdigest(),
          "content":content,"official_verified":False}]}
    if key=="N10":return {"requirements":["시스템 구축","보안계획","핵심인력 2명","3개월 안정화"],
      "evaluation_items":["기술 80점(가상)","가격 20점(가상)"],"original_docs_verified":False}
    if key=="H01":
        if not re.fullmatch(r"\d{10}",EXACT10):raise ValueError("DETAIL10_INVALID")
        return {"detail10":EXACT10,"matched_to_selected_fixture":True,"official_verified":False}
    if key=="H02":return {"start":"2016-10","end":"2026-10","windows":_month_windows(),
      "window_count":121,"official_scanned_windows":0}
    if key=="H03":return {"candidate_notices":_fixture_awards(),
      "candidate_count":10,"actual_notices_collected":0}
    if key=="H04":
        rows=results["H03"]["candidate_notices"]
        return {"exact_detail10_candidates":[x["notice_id"] for x in rows if x["detail10"]==EXACT10],
          "actual_original_verified":False}
    if key=="H05":
        rows=results["H03"]["candidate_notices"]
        return {"bidder_records":[{"notice_id":x["notice_id"],**bid}
            for x in rows for bid in x["bids"]],"official_openings_verified":0}
    if key=="H06":
        rows=results["H03"]["candidate_notices"]
        return {"awards":[{k:x[k] for k in ("notice_id","year","winner","award_amount_krw","base_amount_krw","agency")}
          for x in rows],"official_awards_verified":0}
    if key=="H07":
        months=results["H02"]["windows"]
        return {"mock_windows_processed":len(months),"mock_replay_complete":len(months)==121,
          "official_windows_verified":0,"official_10_year_coverage_complete":False,
          "mock_bidder_rows":len(results["H05"]["bidder_records"]),
          "mock_award_rows":len(results["H06"]["awards"])}
    if key=="H08":return {"selected_bid_no":CASE_ID,"linked_mock_notices":len(results["H06"]["awards"]),
      "linked_actual_opening_awards":0,"correct_detail10":EXACT10}
    if key=="H09":
        award=results["H06"]["awards"]
        agency=[x for x in award if x["agency"]==case["agency"]]
        if not agency:raise ValueError("NO_MATCHING_AUTHORITY_MOCK_RECORDS")
        return {"agency":case["agency"],"mock_award_count":len(agency),
          "mock_avg_award_ratio":round(statistics.mean(x["award_amount_krw"]/x["base_amount_krw"] for x in agency),4),
          "real_authority_evidence":False}
    if key=="H10":
        bids=results["H05"]["bidder_records"];awards=results["H06"]["awards"]
        return {"mock_bidder_frequency":dict(Counter(x["vendor"] for x in bids)),
          "mock_winner_frequency":dict(Counter(x["winner"] for x in awards)),
          "real_competitor_identified":False}
    if key=="H11":return {"detail10":EXACT10,
        "summary":"가상 10건의 개찰·낙찰 표본과 121개 월간 테스트 구간",
        "agency":results["H09"],"competitors":results["H10"],
        "coverage":results["H07"],"verified_actual_ten_year_data":False}
    if key=="Q01":return {"mandatory":["해당 업종·면허 확인","사업자 증빙","핵심인력 2명","보안계획"],
      "official_requirements_verified":False}
    if key=="Q02":return {"company_registry":"not_supplied","licenses_verified":False,
      "certifications_verified":False,"company_eligibility_approved":False}
    if key=="Q03":return {"joint_bidding":"official_terms_missing","bond":"unknown"}
    if key=="Q04":return {"missing":["실제 업종등록","실제 면허·인증","인력 근로·수행 증빙"],
      "all_eligibility_evidence_verified":False}
    if key=="Q05":return {"eligible":False,"status":"HOLD_ELIGIBILITY_EVIDENCE",
      "missing":results["Q04"]["missing"]}
    if key=="S01":return {"supplier_candidates":["가상 공급업체-1","가상 공급업체-2"],
      "real_supplier_references":0}
    if key=="S02":return {"draft_requests":2,"sent":0,"external_contacted":False}
    if key=="S03":return {"synthetic_quote_amounts_krw":[138_000_000,145_000_000],
      "actual_supplier_quotes_verified":0}
    if key=="S04":return {"synthetic_quote_count":2,"real_verified_quote_count":0,
      "real_quote_quorum":False,"mock_quote_min_krw":138_000_000}
    if key=="P01":return {"base_amount_krw":case["budget_krw"],
      "budget_krw":case["budget_krw"],"source":"fictional_budget","quantity_lines_verified":False}
    if key=="P02":return {"synthetic_development_krw":118_000_000,
      "synthetic_staffing_krw":27_000_000,"synthetic_external_krw":12_000_000,
      "synthetic_direct_cost_krw":157_000_000,"actual_cost_verified":False}
    if key=="P03":
        direct=results["P02"]["synthetic_direct_cost_krw"]
        overhead=_money(direct*Decimal("0.08"))
        subtotal=direct+overhead
        contingency=_money(subtotal*Decimal("0.05"))
        return {"direct_krw":direct,"overhead_krw":overhead,"contingency_krw":contingency,
          "total_cost_krw":subtotal+contingency,"official_tax_rules_verified":False}
    if key=="P04":
        rec=results["H06"]["awards"]
        ratios=[r["award_amount_krw"]/r["base_amount_krw"] for r in rec]
        return {"fictional_sample_count":len(ratios),
          "synthetic_mean_award_ratio":round(statistics.mean(ratios),5),
          "sample_min":round(min(ratios),5),"sample_max":round(max(ratios),5),
          "real_history_verified":False}
    if key=="P05":return {"method":case["contract_type"],"technical_weight":80,
      "price_weight":20,"official_price_formula_verified":False,
      "official_award_threshold_verified":False}
    if key=="P06":
        cost=results["P03"]["total_cost_krw"]
        targets=[("quality",211_000_000),("balanced",203_000_000),("cost",190_000_000)]
        options=[{"name":name,"price_krw":price,"cost_krw":cost,
          "margin_krw":price-cost,"margin_pct":round(100*(price-cost)/price,2),
          "within_synthetic_budget":price<=case["budget_krw"],"synthetic_only":True}
          for name,price in targets]
        return {"options":options,"derived_from":"fictional cost and RFP inputs",
          "is_predicted_winning_bid":False,"official_pricing_formula_verified":False}
    if key=="P07":
        scenarios=results["P06"]["options"]
        feasible=[x for x in scenarios if x["within_synthetic_budget"] and x["margin_pct"]>=10]
        selected=next((x for x in feasible if x["name"]==state["strategy_preference"]),None)
        if selected is None:
            return {"selected":None,"status":"HOLD_NO_VALID_MOCK_PRICE"}
        technical=case["evaluation"]["technical_weight"]
        return {"selected":selected,
          "strategy_reason":"가상 기술평가 "+str(technical)+"점 및 손익·수행 가능성 비교",
          "alternatives":scenarios,"human_approval":False,"official_bid_price_approved":False,
          "public_history_inference_limit":"과거 결과만으로 과거 기술제안서·평가점수 추정 불가"}
    if key=="R01":
        selected=results["P07"]["selected"]
        if not selected:raise ValueError("MISSING_SELECTED_STRATEGY")
        focus={"quality":"실적·아키텍처·핵심인력","balanced":"기술 수행·납기·가격 균형",
            "cost":"표준 개발·원가 절감"}[selected["name"]]
        sections=["수요기관 요구 대응표","기술 아키텍처와 보안","유사실적 및 수행 인력",
                  "일정·안정화 및 위험관리","품질·검수·유지보수","가격 산출 및 증빙"]
        return {"strategy":selected["name"],"emphasis":focus,"sections":sections,
          "estimated_price_krw":selected["price_krw"],
          "documents":["가상 기술제안서 목차","가상 가격 산출근거","필수 서류 점검표"],
          "document_status":"MOCK_DRAFT_ONLY","official_rfp_forms_verified":False}
    if key=="R02":return {"package":"synthetic_prebid_draft",
      "proposal_sections":len(results["R01"]["sections"]),
      "qualification_verified":False,"actual_quotes_verified":False,
      "real_rfp_forms_verified":False,"final_package_valid":False}
    if key=="O01":return {"case_owner":CASE_ID,"task_key":"MOCK_"+CASE_ID,
      "source":"selected_fixture","queue_created":False}
    if key=="O02":return {"worker_jobs":0,"mock_job_queue":["PF01","PF05","PF07","PF09","PF10"],
      "worker_recovery_mock":True,"real_worker_dispatched":False}
    if key=="O03":
        return {"fixture_provenance":"fictional_test_fixture",
          "completed_blocks_so_far":len(state["completed_blocks"]),
          "real_original_verifications":0,
          "gaps":["official 10-year data","official RFP and attachments",
            "company eligibility","supplier quotes","pricing formula","human approval"]}
    if key=="O04":
        done=set(state["completed_blocks"])|{"O04"}
        feature_numbers={no for bid in done for no in BLOCKS[bid]["features"]}
        missing=results["O03"]["gaps"]
        return {"decision":"HOLD_OFFICIAL_EVIDENCE","mock_execution_completed":len(done)==43,
          "mock_contract_coverage":len(feature_numbers),
          "official_verified_features":0,"missing_verification":missing,
          "strategy":results["P07"]["selected"],"proposal":results["R01"],
          "human_bid_participation_required":True,"bid_participation_clicked":False,
          "bid_submitted":False}
    raise ValueError("UNIMPLEMENTED_OR_UNKNOWN_BUSINESS_BLOCK")

def run_block(block_id,value):
    if block_id not in BLOCKS:raise ValueError("BLOCK_NOT_IN_ORIGINAL_MANIFEST")
    index=ORDER.index(block_id)
    if index==0:state=root(value)
    else:
        _safe(value)
        state=copy.deepcopy(value)
        if state.get("completed_blocks")!=ORDER[:index]:
            raise ValueError("DEPENDENCY_ORDER_OR_PREVIOUS_STAGE_INVALID")
    # Strictly require actual predecessor block results for each original manifest edge.
    dependencies=[b["id"] for b in BLOCKS.values() if block_id in b.get("to",[])]
    if index and any(x not in state["results"] for x in dependencies):
        raise ValueError("MISSING_ORIGINAL_MANIFEST_DEPENDENCY")
    block=BLOCKS[block_id]
    output=_stage(block,state)
    state["results"][block_id]=output
    checks=[]
    for no in block["features"]:
        item=CATALOG[no]
        rec={"number":no,"label":item["label"],"group":item["group"],
            "required_verified_evidence":list(FEATURE_GATES[no]),
            "test_status":"MOCK_EXECUTED","official_verified":False,
            "official_evidence_missing":list(FEATURE_GATES[no]),
            "source_block":block_id}
        state["feature_results"][str(no)]=rec
        checks.append(no)
    state["completed_blocks"].append(block_id)
    state["last_block"]={"id":block_id,"label":block["label"],
      "flow_ids":[f["id"] for f in MANIFEST["flows"] if block_id in f.get("owned_blocks",[])],
      "features":checks,"input_contract":block["input"],"output_contract":block["output"],
      "output":output,"official_evidence_verified":False}
    if block_id=="O04":
        if set(map(int,state["feature_results"]))!=set(range(1,105)):
            raise ValueError("MISSING_104_FUNCTION_COVERAGE")
        state["business_status"]="MOCK_COMPLETED_OFFICIAL_HOLD"
        state["strategy_decision"]=output["decision"]
    return state

def node_binding(workflow_path,node_id):
    if workflow_path!=PATH or not isinstance(node_id,str) or not node_id.startswith("public-"):
        return None
    block_id=node_id.removeprefix("public-")
    if block_id not in BLOCKS:return None
    return {"python_module":"procurement_node_adapter",
        "python_function":"execute_public_block",
        "code_version":"procure-original-104-"+block_id+"-v1",
        "node_character":"manual_collection_start" if block_id=="N01" else "business_operation"}

def summary_fixture():
    return {"bid_no":CASE_ID,"bid_ord":CASE_ORD,"detail10":EXACT10,
      "title":"가상 테스트용 선택 공고: 스마트 설비 모니터링 SW 개발",
      "fixture_id":FIXTURE_ID,"source":"fictional_test_fixture",
      "actual_notice_verified":False,"official_10yr_verified":False,
      "number_of_blocks":len(BLOCKS),"number_of_features":len(FEATURES),
      "bid_submitted":False}
