"""Three market-specific, offline-only, allowlisted Python node handlers.

This is the ProcureFlow project adapter for the EXACT shared investment Studio UI.
It does not fetch G2B, work24, jobs, submit bids, contact clients, or use secrets.
All values are conspicuously fictional test fixtures, NOT an empirical prediction.
"""
from __future__ import annotations
import copy
import statistics

WF01_MODES = {
    "operations/A01-public-win-strategy.json": "public",
    "operations/B01-private-software-proposal.json": "private_dev",
    "operations/C01-staffing-service-proposal.json": "staffing",
}
STEP_NAMES = {
    "public": ["선택 입찰 시작", "평가기준·정확한 10자리 세부품명", "가상 과거 낙찰데이터 분석",
               "경쟁·발주기관 전략", "가격·원가 대안 계산", "수주전략 선택",
               "전략 기반 기술제안서 목차", "독립 감사·사람 판단"],
    "private_dev": ["개발 의뢰 시작", "요구사항·납품범위 분석", "기술 아키텍처",
                    "기능별 개발공수", "견적·마진 시나리오", "맞춤형 제안 전략", "계약·수익성 심사"],
    "staffing": ["인력·용역 수요 시작", "채용공고와 용역계약 분류", "인력 확보·수급",
                  "인건비·용역 단가", "노무·계약 준수 점검", "인력·운영 제안", "독립 검증"],
}
PREFIX = {"public":"a01", "private_dev":"b01", "staffing":"c01"}
ROOT_DEFAULTS = {
    "public":{"fixture_kind":"public","scenario":"DEMO_PUBLIC_001","strategy_preference":"balanced"},
    "private_dev":{"fixture_kind":"private_dev","scenario":"DEMO_PRIVATE_001","strategy_preference":"balanced"},
    "staffing":{"fixture_kind":"staffing","scenario":"DEMO_STAFFING_001","strategy_preference":"balanced"},
}
TYPE = "n8n-nodes-base.code"

def node_binding(workflow_path, node_id):
    kind = WF01_MODES.get(workflow_path)
    if not kind: return None
    prefix=PREFIX[kind]
    if not isinstance(node_id,str) or not node_id.startswith(prefix+"-"): return None
    try: num=int(node_id.split("-")[-1])
    except ValueError: return None
    if not 1<=num<=len(STEP_NAMES[kind]) or node_id!=f"{prefix}-{num:02d}":return None
    return {"python_module":"procurement_node_adapter",
            "python_function":f"execute_node{num:02d}",
            "code_version":f"procure-three-markets-{kind}-{num:02d}-v1",
            "node_character":"manual_collection_start" if num==1 else "business_operation"}

def node_type(workflow_path,node_id):
    binding=node_binding(workflow_path,node_id)
    if not binding:return None
    return "n8n-nodes-base.manualTrigger" if node_id.endswith("-01") else TYPE

def root_input_limit(workflow_path,node_id):return 2048

def _assert_fixture(input_json,kind):
    if not isinstance(input_json,dict):raise ValueError("INPUT_JSON_OBJECT_REQUIRED")
    if input_json.get("fixture_kind")!=kind or input_json.get("scenario")!=ROOT_DEFAULTS[kind]["scenario"]:
        raise ValueError("ONLY_REGISTERED_FICTIONAL_FIXTURE_ALLOWED")
    if input_json.get("source_provenance")!="fictional_test_fixture" or input_json.get("simulation_only") is not True:
        raise ValueError("UNVERIFIED_OR_LIVE_INPUT_FORBIDDEN")
    if input_json.get("bid_submitted") is not False or input_json.get("client_contacted") is not False:
        raise ValueError("EXTERNAL_ACTION_FORBIDDEN")

def execute_node01(input_json, *, workflow_kind=None):
    if workflow_kind not in ROOT_DEFAULTS:raise ValueError("UNKNOWN_MARKET")
    if not isinstance(input_json,dict) or set(input_json)!=set(ROOT_DEFAULTS[workflow_kind]):
        raise ValueError("ROOT_INPUT_FIELDS_MISMATCH")
    if input_json["fixture_kind"]!=workflow_kind or input_json["scenario"]!=ROOT_DEFAULTS[workflow_kind]["scenario"]:
        raise ValueError("INVALID_FIXTURE_SELECTION")
    if input_json["strategy_preference"] not in ("balanced","quality","cost"):
        raise ValueError("UNSUPPORTED_STRATEGY_PREFERENCE")
    return {**input_json,"source_provenance":"fictional_test_fixture","simulation_only":True,
        "actual_job_executed":False,"bid_submitted":False,"client_contacted":False,
        "business_status":"TEST_ONLY","trace":[{"stage":1,"result":"fictional_fixture_loaded"}]}

def _money(x):return round(float(x),2)
def _stage(input_json,stage,kind):
    _assert_fixture(input_json,kind)
    expected=len(input_json.get("trace",[]))+1
    if expected!=stage:raise ValueError(f"STAGE_ORDER_MISMATCH expected {expected}, got {stage}")
    out=copy.deepcopy(input_json)
    name=STEP_NAMES[kind][stage-1]
    if kind=="public":
        if stage==2:
            # ALL data here is invented for QA; the public bid has no official 10-year coverage.
            out["rfp"]={"detail10":"8111159901","authority":"가상 발주기관",
                "evaluation":"technical_price_weighted","technical_weight":80,
                "price_weight":20,"budget_krw":220_000_000,
                "mandatory":['정보보안 계획','3개월 안정화','핵심인력 2명']}
            if len(out["rfp"]["detail10"])!=10 or out["rfp"]["technical_weight"]+out["rfp"]["price_weight"]!=100:
                raise ValueError("RFP_EVALUATION_INVALID")
        elif stage==3:
            history=[{"year":2022,"awarded_ratio":0.88,"participants":4},
                     {"year":2023,"awarded_ratio":0.91,"participants":6},
                     {"year":2024,"awarded_ratio":0.89,"participants":5},
                     {"year":2025,"awarded_ratio":0.90,"participants":7},
                     {"year":2026,"awarded_ratio":0.92,"participants":5}]
            out["award_history"]={"source":"synthetic_five_sample_records_NOT_official_10y",
                "records":history,"mean_ratio":round(statistics.mean(x["awarded_ratio"] for x in history),4),
                "mean_participants":round(statistics.mean(x["participants"] for x in history),2),
                "ten_year_coverage_verified":False}
        elif stage==4:
            history=out.get("award_history")
            if not history:raise ValueError("MISSING_HISTORY_STAGE")
            out["competition"]={"observation":"가상 참여업체 수만 예시",
                "mean_participants":history["mean_participants"],
                "real_competitors_identified":False,"strategy_implication":"기술 차별화 검토"}
        elif stage==5:
            if not out.get("rfp") or not out.get("competition"):raise ValueError("MISSING_INPUT")
            budget=out["rfp"]["budget_krw"]
            cost=170_000_000
            scenarios=[{"name":n,"bid_price_krw":p,"estimated_cost_krw":cost,
                        "margin_krw":p-cost,"margin_pct":round((p-cost)/p*100,2)}
              for n,p in [("quality",210_000_000),("balanced",199_000_000),("cost",185_000_000)]]
            out["price_options"]=[{**x,"budget_compatible":x["bid_price_krw"]<=budget,
                                   "cost_covered":x["margin_krw"]>0} for x in scenarios]
            out["pricing_method"]="synthetic cost-plus only; not a winning price prediction"
        elif stage==6:
            choices=out.get("price_options")
            if not choices:raise ValueError("MISSING_PRICING")
            eligible=[x for x in choices if x["budget_compatible"] and x["margin_pct"]>=10]
            preferred=out["strategy_preference"]
            selected=next((x for x in eligible if x["name"]==preferred),eligible[0] if eligible else None)
            out["win_strategy"]={"selected":selected,"reason":"가상 기술배점 80점 및 원가 여유를 함께 평가",
                "observed_award_ratio_is_not_proposed_bid_price":True,
                "public_evidence_verified":False}
        elif stage==7:
            strategy=out.get("win_strategy",{}).get("selected")
            if not strategy:raise ValueError("NO_VIABLE_STRATEGY")
            focus={"quality":"아키텍처·실적·핵심인력","balanced":"안정성·일정·합리적 가격",
                    "cost":"표준화·원가 효율"}[strategy["name"]]
            out["proposal"]={"title":"가상 정보시스템 구축 제안 전략서",
                "strategy":strategy["name"],"emphasis":focus,
                "sections":['요구사항 대응표','수행방법론','품질·보안','핵심인력 및 실적','일정·위험','가격 산출근거'],
                "deliverable":"draft_outline_only"}
        elif stage==8:
            checks={"fixture_only":True,"history_not_verified":not out.get("award_history",{}).get("ten_year_coverage_verified",False),
                    "proposal_exists":bool(out.get("proposal")),
                    "human_approval_required":True}
            out["audit"]=checks
            out["decision"]="HOLD_OFFICIAL_EVIDENCE" if checks["history_not_verified"] else "REVIEW_FOR_HUMAN"
    elif kind=="private_dev":
        if stage==2:
            out["requirements"]={"client":"가상 스타트업","budget_krw":110_000_000,
                "features":[{"name":"고객관리","person_days":22},{"name":"예약·결제","person_days":36},
                            {"name":"관리 콘솔","person_days":28},{"name":"외부 API","person_days":19}],
                "acceptance":["테스트 시나리오","보안·개인정보 점검","운영 인수"]}
        elif stage==3:
            if not out.get("requirements"):raise ValueError("REQUIREMENTS_MISSING")
            out["architecture"]={"api":"Python FastAPI","frontend":"Vue 3",
              "database":"PostgreSQL","deployment":"container","assumption":"가상 요구에 대한 예시 아키텍처"}
        elif stage==4:
            items=out.get("requirements",{}).get("features")
            if not items:raise ValueError("FEATURES_MISSING")
            baseline=sum(x["person_days"] for x in items)
            out["effort"]={"development_person_days":baseline,
              "qa_and_pm_person_days":round(baseline*0.25),
              "total_person_days":round(baseline*1.25),
              "schedule_weeks":round((baseline*1.25)/10+0.5)}
        elif stage==5:
            days=out.get("effort",{}).get("total_person_days")
            if not days:raise ValueError("EFFORT_MISSING")
            cost=days*610_000+7_000_000
            opts=[{"name":n,"price_krw":p,"cost_krw":cost,
                   "margin_pct":round((p-cost)/p*100,2),
                   "under_client_budget":p<=out["requirements"]["budget_krw"]}
                for n,p in [("quality",105_000_000),("balanced",95_000_000),("cost",85_000_000)]]
            out["quotes"]=opts
        elif stage==6:
            viable=[x for x in out.get("quotes",[]) if x["margin_pct"]>=12 and x["under_client_budget"]]
            pref=out["strategy_preference"]
            chosen=next((x for x in viable if x["name"]==pref),viable[0] if viable else None)
            if not chosen:raise ValueError("QUOTE_UNPROFITABLE")
            out["proposal"]={"strategy":chosen["name"],"quote":chosen,
              "sections":["고객 문제와 해결안","화면·기능 범위","아키텍처","WBS·일정","검수·변경관리","가격·유지보수"],
              "contract_exclusions":["제3자 API 사용료 별도","범위 추가 시 별도 합의"]}
        elif stage==7:
            checks={"quote_has_margin":out["proposal"]["quote"]["margin_pct"]>=12,
                    "scope_documented":bool(out["requirements"]["features"]),
                    "client_approval_required":True}
            out["audit"]=checks;out["decision"]="REVIEW_FOR_CLIENT_PROPOSAL" if all(checks.values()) else "HOLD"
    elif kind=="staffing":
        if stage==2:
            out["demand"]={"source_type":"SERVICE_RFP_FIXTURE","client":"가상 민간기업",
              "role":"헬프데스크 운영","headcount":3,"months":6,"location":"서울",
              "job_posting_is_not_procurement":True,
              "no_unrequested_contact":True}
        elif stage==3:
            if out.get("demand",{}).get("source_type")!="SERVICE_RFP_FIXTURE":
                raise ValueError("EMPLOYMENT_POSTING_NOT_SERVICE_CONTRACT")
            out["supply"]={"available_staff":3,"required_staff":out["demand"]["headcount"],
                "backups":1,"verified_real_candidates":False,
                "supply_feasible_in_fixture":True}
        elif stage==4:
            if not out.get("supply"):raise ValueError("SUPPLY_MISSING")
            people=out["demand"]["headcount"];months=out["demand"]["months"]
            salary=3_300_000; overhead_rate=0.24
            total=round(people*months*salary*(1+overhead_rate))
            out["staffing_cost"]={"direct_monthly_salary_krw":salary,
              "synthetic_overhead_ratio":overhead_rate,"total_krw":total,
              "quote_krw":round(total*1.20),"margin_pct":round(100*(total*.20)/(total*1.2),2)}
        elif stage==5:
            out["compliance"]={"employment_vs_outsourcing_checked":True,
              "dispatch_and_labor_law_review_required":True,"legal_review_completed":False,
              "real_staff_qualification_verified":False}
        elif stage==6:
            if not out.get("staffing_cost") or not out.get("compliance"):raise ValueError("REVIEW_REQUIRED")
            out["proposal"]={"title":"가상 헬프데스크 인력운영 용역",
              "headcount":out["demand"]["headcount"],"months":out["demand"]["months"],
              "price_krw":out["staffing_cost"]["quote_krw"],
              "sections":["직무별 인력 배치","인수인계·교대표","결원·대체인력","노무·계약 확인","월 단가·관리비"]}
        elif stage==7:
            out["audit"]={"legal_review_missing":not out["compliance"]["legal_review_completed"],
                "real_staff_not_verified":not out["supply"]["verified_real_candidates"],
                "human_contract_approval_required":True}
            out["decision"]="HOLD_LEGAL_AND_REAL_STAFF_CHECK"
    else:raise ValueError("UNREGISTERED_MARKET")
    out["trace"].append({"stage":stage,"operation":name,"status":"MOCK_CALCULATED"})
    out["actual_job_executed"]=False
    return out

def execute_node02(value, *,workflow_kind=None):return _stage(value,2,workflow_kind)
def execute_node03(value, *,workflow_kind=None):return _stage(value,3,workflow_kind)
def execute_node04(value, *,workflow_kind=None):return _stage(value,4,workflow_kind)
def execute_node05(value, *,workflow_kind=None):return _stage(value,5,workflow_kind)
def execute_node06(value, *,workflow_kind=None):return _stage(value,6,workflow_kind)
def execute_node07(value, *,workflow_kind=None):return _stage(value,7,workflow_kind)
def execute_node08(value, *,workflow_kind=None):return _stage(value,8,workflow_kind)

def execute_node(workflow_path,node_id,input_json):
    kind=WF01_MODES.get(workflow_path)
    if not kind or not node_binding(workflow_path,node_id):
        raise ValueError("UNREGISTERED_PROCUREMENT_NODE")
    number=int(node_id.split("-")[-1])
    function=globals()[f"execute_node{number:02d}"]
    return function(input_json,workflow_kind=kind)
