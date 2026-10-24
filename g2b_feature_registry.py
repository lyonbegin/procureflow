"""ProcureFlow 104-function acceptance catalog.

One selected tender advances only when recorded primary-source evidence meets
a concrete acceptance criterion. A registered step is NOT an implemented step.
"""
from __future__ import annotations

GROUPS=[
("notice",[
"실제 G2B 신규 입찰공고 자동 검색","신규 공고 정기 자동 업데이트","신규 공고번호 추출","공고차수 구분","공고게시일 확보",
"투찰마감일 확보","공고명 확보","공고기관·수요기관 확보","물품·용역 업무 구분",
"공식 세부 품목분류 확보","발주요청과 정식 공고 구분","취소·정정·재공고 식별",
"공고조건 변경 감지","공고 변경 이력 보존","공고 중복 저장 방지","신규 공고 작업 큐 등록"
]),
("detail",[
"공고 원본 상세조회","공고 상세 JSON 증빙 저장","세부품명·분류번호 추출","기관 코드 추출",
"계약방법 추출","낙찰자 결정방법 추출","기초금액·추정가격·예산 구분","지역제한 추출",
"업종·면허·등록자격 추출","중소기업 등 제한 추출","납품·수행기간 및 장소",
"첨부문서 목록 전체 확보","첨부파일 원본 다운로드","첨부 파일 무결성 및 버전",
"첨부문서 텍스트·표 구조 추출","공고 본문과 첨부 증빙 대조"
]),
("history",[
"과거 개찰 목록 수집","참가업체 기록 수집","업체별 투찰금액 저장","업체별 투찰률 저장",
"업체별 개찰순위","확정 낙찰업체 확인","최종 낙찰금액","사업자번호 업체 식별",
"과거 개찰 중복 제거","공고차수·재입찰 집행 구분","과거 원본 JSON 저장",
"최근 개찰 주기 갱신","과거 개찰 백필","과거 10년 개찰·낙찰 전수",
"공고번호별 과거 개찰조회","신규 공고와 과거 결과 연결"
]),
("matching",[
"선택 공고 10자리 세부품명번호 원본 확인","해당 세부품명 10년 개찰결과 전체 확보","해당 세부품명 10년 확정 낙찰결과 전체 확보",
"구형·신형 과거 개찰 공고번호 통합","선택 세부품명 10년 개찰기간 구간 관리","모든 구간의 실제 개찰·낙찰 결과 순회",
"과거 참가업체·투찰금액·순위 저장","과거 확정 낙찰업체·낙찰금액 대조","동일 발주기관의 실제 개찰·낙찰 분석",
"발주기관 코드별 확정 결과 집계","정확 일치 세부종목의 반복 참가업체 분석","10년 투찰·낙찰 실적 근거 보고서 저장"
]),
("eligibility",[
"필수 입찰참가 자격 추출","자사 업종등록 대조","지역제한 적격성 검증",
"중소기업 요건 검증","필수 인증·면허 검증","가능·불가 판정 근거",
"공동수급·분담이행 조건","입찰보증금 조건","필수 참가서류 목록",
"보유 증빙과 요구 증빙 대조","공급업체 DB 관리","품목별 공급 가능 업체",
"공급·수행 가능성 검증","견적요청 생성","견적회신 원본 수집","업체별 원가·납기 비교"
]),
("pricing",[
"기초금액 정확 확인","추정가격·예산 정규화","규격·수량 내역서 분석",
"공급업체 견적원가","실제 인건비·노무비","실제 재료비·경비·외주비",
"일반관리비·이윤","세액 산출","총 원가 계산","동일 분류 낙찰가격 비교",
"투찰률 분포 추정","공고의 낙찰하한율 적용","가격 시나리오 비교",
"목표이익·수익성 검증","최종 투찰금액 제안","제안서·참가서류 생성",
"제출양식 반영","최종 입찰 패키지 검증"
]),
("operations",[
"입찰 건별 작업관리","단계별 진행 상태 추적","작업큐·Worker 실행",
"수집 로그와 오류 증빙","선택 건 독립 작업 소유","원본·분석결과 통합",
"일시정지·재개","실패 재시도·수동 승인","입찰참가 직전 상태 검증",
"최종 제안서·가격·서류·근거 검증"
])]
GROUP_BOUNDS={"notice":(1,16),"detail":(17,32),"history":(33,48),
              "matching":(49,60),"eligibility":(61,76),"pricing":(77,94),
              "operations":(95,104)}
FEATURES=[]
for key,names in GROUPS:
    a,b=GROUP_BOUNDS[key]
    assert len(names)==b-a+1,(key,len(names))
    for no,label in enumerate(names,a):
        FEATURES.append({"number":no,"group":key,"label":label})
assert len(FEATURES)==104

# Hard dependencies are evidenced data, not status labels or button-clicks.
REQUIREMENTS={
"notice":("notice_official","classification_verified","agency","deadline"),
"detail":("detail_original","attachment_index","attachments_complete",
          "attachment_text","requirements"),
"history":("history_10years_complete","opening_evidence","award_evidence"),
"matching":("classification_verified","history_10years_complete",
            "historical_bidders_linked"),
"eligibility":("company_registration","qualification_evaluation",
               "eligibility_documents","supplier_quotes"),
"pricing":("requirements","verified_base_amount","supplier_quotes",
           "cost_breakdown","price_rules","proposal_draft"),
"operations":("final_package","final_validation")}
def features_by_group():
    return {key:[x for x in FEATURES if x["group"]==key] for key,_ in GROUPS}


# Each of 104 functions has its OWN acceptance evidence; fulfilling one phase
# cannot accidentally mark every function in that phase as completed.
_FEATURE_GATES_BY_GROUP={
"notice":[
"notice_official","notice_sync_completed","notice_official","notice_official",
"notice_official","deadline","notice_official","agency","notice_official",
"classification_verified","notice_official","notice_change","notice_change",
"notice_revision","notice_dedup","notice_job_created"],
"detail":[
"detail_original","detail_original","classification_verified","agency_code",
"contract_terms","award_method","verified_base_amount","region_codes",
"industry_codes","company_restrictions","contract_terms",
"attachment_index","attachments_complete","attachments_complete",
"attachment_text","detail_attachment_reconciliation"],
"history":[
"opening_evidence","historical_bidders_linked","opening_evidence","bid_rates",
"bid_rank","award_evidence","award_evidence","supplier_registry",
"opening_dedup","opening_execution","opening_raw","opening_refresh",
"opening_backfill","history_10years_complete","opening_evidence",
"historical_bidders_linked"],
"matching":[
"classification_verified","history_10years_complete",
"classification_verified","history_legacy_mapped",
"history_window_register","history_10years_complete",
"history_10years_complete","historical_bidders_linked",
"agency_history","agency_code","competitor_analysis","analysis_report"],
"eligibility":[
"requirements","company_registration","region_codes","company_size",
"company_registration","qualification_evaluation","joint_bid_rules",
"bid_bond_rules","required_forms","eligibility_documents",
"supplier_evidence","supplier_evidence","supplier_evidence",
"supplier_quotes","supplier_quotes","supplier_quotes"],
"pricing":[
"verified_base_amount","verified_base_amount","attachment_text",
"supplier_quotes","labor_cost","materials_cost","general_overhead",
"tax_rules","cost_breakdown","award_evidence","bid_rates",
"price_rules","price_scenarios","price_scenarios","approved_bid_price",
"proposal_draft","required_forms","final_validation"],
"operations":[
"case_dashboard","phase_tracking","worker_executed","run_log",
"assigned_agent","evidence_aggregation","workflow_controls",
"retry_and_approval","manual_participation_ready","final_validation"]
}
FEATURE_GATES={}
for group,labels in GROUPS:
    a,b=GROUP_BOUNDS[group]
    required=_FEATURE_GATES_BY_GROUP[group]
    assert len(required)==len(labels)
    FEATURE_GATES.update({a+i:(required[i],) for i in range(len(labels))})
assert len(FEATURE_GATES)==104

# Precise independent acceptance: mere presence of an original notice field
# does not prove bidder eligibility or complete cost sheets.
FEATURE_GATES[21]=("contract_method",)
FEATURE_GATES[23]=("verified_base_amount","estimated_amount","vat_amount")
FEATURE_GATES[61]=("requirements","industry_codes","region_codes","company_restrictions")
FEATURE_GATES[63]=("region_codes","company_registration","qualification_evaluation")
FEATURE_GATES[78]=("verified_base_amount","estimated_amount","vat_amount")
FEATURE_GATES[79]=("bill_of_quantities",)

# Strict acceptance: an original PDF is not an original notice JSON; a single
# matched bidder is not a final award; a current notice's 10-digit code is not
# evidence of historical 10-digit matching; a hash is not a revision archive.
FEATURE_GATES[18]=("notice_official","notice_raw_json")
FEATURE_GATES[30]=("attachments_complete","attachment_revision_history")
FEATURE_GATES[51]=("classification_verified","historical_detail10_match")
FEATURE_GATES[56]=("historical_bidders_linked","award_evidence")

# History acceptance is about ACTUAL opening and confirmed-award evidence,
# not historical public tender headings or a broad eight-digit code.
REQUIREMENTS["history"]=("outcome_10years_complete","opening_evidence","award_evidence")
REQUIREMENTS["matching"]=("classification_verified","outcome_10years_complete",
                          "historical_bidders_linked","award_evidence")
FEATURE_GATES[46]=("outcome_10years_complete",)
FEATURE_GATES[49]=("classification_verified",)
FEATURE_GATES[50]=("outcome_10years_complete","opening_evidence")
FEATURE_GATES[51]=("outcome_10years_complete","award_evidence")
FEATURE_GATES[52]=("historic_old_and_new_opening_verified",)
FEATURE_GATES[53]=("outcome_window_register",)
FEATURE_GATES[54]=("outcome_10years_complete",)
FEATURE_GATES[55]=("opening_evidence","historical_bidders_linked")
FEATURE_GATES[56]=("award_evidence",)
FEATURE_GATES[57]=("verified_agency_opening_history",)
FEATURE_GATES[58]=("verified_agency_code_results",)
FEATURE_GATES[59]=("verified_detail10_company_stats",)
FEATURE_GATES[60]=("verified_detail10_outcome_report",)
