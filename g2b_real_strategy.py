"""Actual competition and tender-preparation decision from existing G2B records.

No synthetic competitor, award, recommended bid price, mandatory proposal, or
10-year "complete" signal. Aggregate ALL verified 10-digit source records in a
filtered time window, not merely the current UI page of 50.
"""
from __future__ import annotations

from datetime import datetime, date
from zoneinfo import ZoneInfo
from html import unescape
from g2b_search_first import filters, _where, _json_row, single_case_material, search_stored
from db import session

def _valid_deadline(raw):
    if not isinstance(raw,str) or len(raw)<10:return None
    try:
        from re import match
        m=match(r"^(\d{4}-\d\d-\d\d)(?:[ T](\d\d:\d\d))?",raw)
        if not m:return None
        return datetime.fromisoformat(m.group(1)+"T"+(m.group(2) or "00:00")).replace(
            tzinfo=ZoneInfo("Asia/Seoul"))
    except (ValueError,OverflowError):
        return None

def _company_clean(value):
    return " ".join(unescape(str(value or "")).split())[:180]


def _raw_stats(con,s):
    where,params=_where(s)
    query="""SELECT
        COUNT(*)::int AS opening_rows,
        COUNT(DISTINCT (r.bid_ntce_no,r.bid_ntce_ord))::int AS observed_notice_rounds,
        COUNT(DISTINCT NULLIF(trim(r.company),''))::int AS distinct_name_strings,
        COUNT(*) FILTER (WHERE r.rank='1')::int AS rank_one_openings_not_awards,
        COUNT(*) FILTER (WHERE CASE WHEN r.amount~'^[0-9]+(\.[0-9]{1,2})?$'
              THEN r.amount::numeric>0 ELSE FALSE END)::int AS rows_with_numeric_amounts,
        COUNT(*) FILTER (WHERE CASE WHEN r.rate~'^[0-9]+(\.[0-9]{1,6})?$'
              THEN r.rate::numeric>0 AND r.rate::numeric<=100
              ELSE FALSE END)::int AS rows_with_raw_rate
       """+where
    return _json_row(con.execute(query,tuple(params)).fetchone())

def _top_competitors(con,s):
    where,params=_where(s)
    query="""SELECT r.company,
        COUNT(*)::int AS opening_rows,
        COUNT(DISTINCT (r.bid_ntce_no,r.bid_ntce_ord))::int AS distinct_notice_rounds,
        COUNT(*) FILTER (WHERE r.rank='1')::int AS rank_one_openings_not_awards,
        COUNT(*) FILTER (WHERE CASE WHEN r.amount~'^[0-9]+(\.[0-9]{1,2})?$'
            THEN r.amount::numeric>0 ELSE FALSE END)::int AS rows_with_amount,
        MAX(h.published_on) AS latest_notice_date
       """+where+""" AND r.company IS NOT NULL AND trim(r.company)<>''
       GROUP BY r.company
       ORDER BY COUNT(DISTINCT (r.bid_ntce_no,r.bid_ntce_ord)) DESC,
          COUNT(*) DESC,MAX(h.published_on) DESC,r.company LIMIT 25"""
    records=con.execute(query,tuple(params)).fetchall()
    # Preserve original name and visible normalized name independently. A name
    # alone does not certify the same legal company/registration.
    return [{**_json_row(x),"display_company":_company_clean(x["company"])}
            for x in records]

def analyze_competition(start=None,end=None,agency="",*,connection=None,
                        now=None,case=None):
    s=filters(start=start,end=end,kind="opening",agency=agency,limit=1,offset=0)
    if connection is None:
        with session() as con:
            return analyze_competition(start,end,agency,connection=con,now=now,case=case)
    if case is None:
        case=single_case_material(connection=connection)
    if case.get("status")!="found":
        return {"status":"selected_notice_missing","real_data_only":True,
                "case_bid_no":s.bid_no,"bid_submitted":False}
    notice=case["notice"]
    all_stats=_raw_stats(connection,s)
    companies=_top_competitors(connection,s)
    awards=search_stored(filters(start=s.start,end=s.end,kind="award",
                         agency=s.agency,limit=1),connection=connection)
    agency_name=str(notice.get("agency") or "").strip()
    # Source data sometimes prefixes the same agency with "재단법인".
    agency_filter=("".join(agency_name.split()).removeprefix("재단법인")
                   if agency_name else "")
    agency_stats=None
    if agency_filter and len(agency_filter)>=3:
        same=filters(start=s.start,end=s.end,kind="opening",
                     agency=agency_filter,limit=1)
        agency_stats=_raw_stats(connection,same)
    cutoff=_valid_deadline(notice.get("deadline"))
    now=now or datetime.now(ZoneInfo("Asia/Seoul"))
    if now.tzinfo is None:
        raise ValueError("OFFSET_AWARE_LOCAL_TIME_REQUIRED")
    closed=bool(cutoff and cutoff<=now.astimezone(ZoneInfo("Asia/Seoul")))
    kind=str(notice.get("method") or "")
    document_note=("원본 표기: 소액수의견적. 전자견적 제출 중심이며 별도 제안서 필수 여부는 공고 원문에서 재검증."
                   if "소액수의" in kind else
                   "계약·평가 방식별 제출서류를 원본 공고와 첨부에서 확인해야 함.")
    if all_stats["opening_rows"]>0:
        decision="actual_opening_comparison_available"
        limitations=["확정 낙찰업체는 개찰 순위 1위와 동일하지 않음",
          "공고 게시일로 제한한 기간 검색은 개찰 발생일의 과거성 검증을 대신하지 못함",
          "사업규모·계약방식이 다른 금액과 비율로 낙찰가격을 바로 예측할 수 없음"]
    else:
        decision="no_verified_opening_sample_for_filter"
        limitations=["해당 필터에서 원본 10자리 확인 개찰표본이 없음",
                     "부재한 표본으로 예상 경쟁업체나 투찰가격 생성 금지"]
    return {
        "status":decision,"source":"existing_real_procureflow_g2b_openings",
        "case_bid_no":s.bid_no,
        "observed_at":now.astimezone(ZoneInfo("Asia/Seoul")).isoformat(),
        "filters":{"start":s.start.isoformat(),"end":s.end.isoformat(),
                   "detail10":s.detail10,"agency":s.agency},
        "target_notice":{"title":notice.get("title"),"agency":agency_name,
           "method":kind,"deadline":notice.get("deadline"),
           "deadline_passed":closed},
        "source_document_count":case["document_count"],
        "document_clause_count":len(case["source_clauses"]),
        "observed":all_stats,
        "confirmed_award_observed":{"award_rows":awards["summary"]["confirmed_award_rows"],
                                    "source_notice_rounds":awards["summary"]["source_notice_rounds"],
                                    "source":"original_verified_explicit_final_award_only"},
        "same_agency_filter":agency_filter if agency_stats is not None else None,
        "same_agency_observed":agency_stats,
        "competitors_from_all_filtered_records":companies,
        "strategy_inputs":{
          "price_evidence_required":True,
          "company_eligibility_verified":False,
          "recommended_bid_price":None,
          "award_count_not_inferred_from_rank_one":True,
          "competition_source_is_opening_not_winner":True,
          "document_type_guidance":document_note,
          "next_actions":[
             "공고 원본에서 참가자격 및 필수 제출양식 대조",
             "회사 등록증·실적·인력 원본과 자격조건 비교",
             "직접 개발 인건비·경비 또는 실제 외주 견적 근거 확인",
             "낙찰하한율·기초금액·가격규칙의 원본 검증",
             "기존 실개찰 자료를 동종 계약방법·규모로 추가 분류",
             "원본에 요구된 서류만 생성하고 사람 검토"]},
        "analysis_limitations":limitations,
        "full_decade_complete":False,
        "real_data_only":True,"manual_approval_required":True,
        "bid_submitted":False
    }


def classify_public_preparation(strategy, eligibility, price, package):
    """The nine real business outputs, instead of 104 unrelated HOLD flags.

    A strategic backfill warning (10-year coverage, scarce award outcomes) is
    NEVER a statutory submit blocker. Legally mandatory qualification, verified
    source notice, price evidence and submission forms remain separate hard
    gates. A human must approve any bid. No changes to the legacy feature API.
    """
    if strategy.get("status")=="selected_notice_missing":
        return {"status":"NO_SOURCE_NOTICE","real_data_only":True,
                "hard_blockers":["선택 공고 원본 없음"],
                "analysis_warnings":[],"bid_submitted":False}
    title=str(strategy["target_notice"].get("title") or "")
    closed=strategy["target_notice"].get("deadline_passed") is True
    # Signed/verified notices and final forms must be explicitly in source
    # evidence, not inferred from a row existing in a bid mirror.
    refs=package.get("evidence_references") or []
    verified={x.get("evidence_type") for x in refs
              if isinstance(x,dict) and x.get("verified_source") is True}
    hard=[]
    if "notice_official" not in verified:
        hard.append("선택 공고의 공식 상세 원본 검증 필요")
    if eligibility.get("status")=="ineligible":
        hard.append("실제 참가자격 불충족")
    elif eligibility.get("status")!="eligible":
        hard.append("회사 참가자격·업종·실적 증빙 검토 필요")
    if price.get("status") not in ("draft_computed_not_approved",):
        needed=price.get("missing") or []
        hard.append("원가·가격규칙 근거 부족"+(": "+", ".join(map(str,needed)) if needed else ""))
    if "required_forms" not in verified:
        hard.append("공고별 필수 제출서식·증빙 대조 필요")
    if "final_validation" not in verified:
        hard.append("최종 참가서류 원본·서명·버전 검수 필요")
    warnings=["10년 전수 수집은 분석 보강 목표이며 필수 제출서류 완료 조건이 아님",
              "기존 개찰·투찰 자료는 낙찰확정 자료와 다르므로 확률/투찰금액을 만들어내지 않음"]
    if strategy.get("confirmed_award_observed",{}).get("award_rows",0)==0:
        warnings.append("현재 필터에는 확인된 확정 낙찰 결과가 없음")
    if strategy["observed"].get("rows_with_numeric_amounts",0)==0:
        warnings.append("이 필터에 투찰금액이 확인된 행이 없어 가격비교가 제한됨")
    if closed:
        status="CLOSED_HISTORICAL_ANALYSIS_ONLY"
    elif eligibility.get("status")=="ineligible":
        status="NO_BID"
    elif hard:
        status="HOLD_REQUIREMENTS"
    else:
        status="MANUAL_FINAL_APPROVAL_REQUIRED"
    observed=strategy["observed"]
    steps=[
      {"id":1,"name":"공고 한 건 선택","status":"source_found","detail":title},
      {"id":2,"name":"공고·첨부 동시 분석","status":"documents_observed" if strategy.get("source_document_count",0) else "missing",
       "count":strategy.get("source_document_count",0),
       "extracted_conditions":strategy.get("document_clause_count",0)},
      {"id":3,"name":"참가자격 판단","status":eligibility.get("status","unknown")},
      {"id":4,"name":"과거 실개찰 검색","status":"real_rows_found" if observed["opening_rows"] else "no_rows",
       "actual_opening_rows":observed["opening_rows"]},
      {"id":5,"name":"경쟁업체·기관 분석","status":strategy["status"],
       "unique_source_notice_rounds":observed["observed_notice_rounds"]},
      {"id":6,"name":"수행 원가","status":"documented" if "cost_breakdown" not in (price.get("missing") or [])
          and price.get("status")=="draft_computed_not_approved" else "incomplete"},
      {"id":7,"name":"투찰전략·가격 대안","status":price.get("status","unknown"),
       "approved_bid_price":price.get("recommended_bid_price")},
      {"id":8,"name":"공고별 입찰서류 초안","status":package.get("stage","unknown"),
       "source_documents":len(package.get("document_index") or [])},
      {"id":9,"name":"사람의 최종 제출 승인","status":status}
    ]
    return {"status":status,"selected_case":strategy["case_bid_no"],
       "source":"actual_production_g2b_document_competition_price_package",
       "real_data_only":True,
       "hard_blockers":hard,
       "analysis_warnings":warnings,
       "steps":steps,"actual_openings_used":observed["opening_rows"],
       "confirmed_awards_used":strategy.get("confirmed_award_observed",{}).get("award_rows",0),
       "actual_document_count":strategy.get("source_document_count",0),
       "price_recommendation":None,
       "requires_human_final_approval":True,
       "bid_participation_clicked":False,"bid_submitted":False}


def actual_preparation(start=None,end=None,agency=""):
    from g2b_bid_package import evaluate_eligibility, documented_price_scenarios, proposal_contents
    strategy=analyze_competition(start,end,agency)
    # Only actual case-engine functions, never the offline fixture runner.
    eligibility=evaluate_eligibility()
    price=documented_price_scenarios()
    package=proposal_contents()
    return classify_public_preparation(strategy,eligibility,price,package)
