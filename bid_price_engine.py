"""Evidence-gated cost model for one publicly documented K-apt security tender.

All rates/line items originate from the public OCR transcription of the attached
2026-10-20 notice; it is NOT the official HWP binary. Nothing here is a
submission price or a vendor quote. The caller must validate actual attached
spreadsheets, company eligibility and tax/insurance treatment.
"""
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
from typing import Any

NOTICE_ID = "20261020165014951"
TENDER_TITLE = "경비용역 사업자 선정 입찰 재공고"
ORIGIN = "https://www.k-apt.go.kr/bid/bidDetail.do?bidNum=" + NOTICE_ID
SECONDARY_OCR = "https://aptbid24.kr/text/4329445"
MONTHLY_HOURS = Decimal("258.55")
NIGHT_HOURS = Decimal("60.84")
DAY_HOURS = Decimal("8.5")
WAGE = Decimal("10320")
YEARS_MONTHS = 12
HEADCOUNT = 2
APARTMENTS = 199
SHOPS = 42
DEFAULT_ADMIN = Decimal("3")
DEFAULT_PROFIT = Decimal("3")


def _ceil(n: Decimal) -> int:
    return int(n.to_integral_value(rounding=ROUND_CEILING))


def _floor(n: Decimal) -> int:
    return int(n.to_integral_value(rounding=ROUND_FLOOR))


def _nonnegative_int(value: Any, name: str, ceiling: int) -> int:
    if isinstance(value, bool):
        raise ValueError(name + " must be an integer")
    if isinstance(value, int):
        result = value
    elif isinstance(value, str) and value.isdigit():
        result = int(value)
    else:
        raise ValueError(name + " must be a non-negative integer")
    if not 0 <= result <= ceiling:
        raise ValueError(name + " is out of allowed simulation range")
    return result


def _percent(value: Any, name: str) -> Decimal:
    try:
        d = Decimal(str(value))
    except Exception as exc:
        raise ValueError(name + " is not a number") from exc
    if not d.is_finite() or d < 3 or d > 25:
        raise ValueError(name + " must be within 3% and 25%")
    return d


def build_price_model(
    *,
    role_allowance_krw: int = 0,
    relief_staff_monthly_krw: int = 0,
    admin_pct: str = "3",
    profit_pct: str = "3",
    common_cost_scope: str = "site",
) -> dict:
    """Make OCR-based editable simulation; never mark vendor-ready."""
    role = _nonnegative_int(role_allowance_krw, "role_allowance_krw", 1000000)
    relief = _nonnegative_int(relief_staff_monthly_krw, "relief_staff_monthly_krw", 3000000)
    admin_rate = _percent(admin_pct, "admin_pct") / 100
    profit_rate = _percent(profit_pct, "profit_pct") / 100
    if common_cost_scope not in ("site", "each_worker"):
        raise ValueError("common_cost_scope must be site or each_worker")

    base = _ceil(MONTHLY_HOURS * WAGE)
    bonus_base = Decimal(base + role) / MONTHLY_HOURS
    night = _ceil(bonus_base * NIGHT_HOURS * Decimal("0.50"))
    labor_day = _ceil(bonus_base * DAY_HOURS / 12)
    annual_leave = _ceil(bonus_base * DAY_HOURS * 15 / 12)
    salary_subtotal = base + role + night
    retirement = _ceil(Decimal(salary_subtotal + labor_day + annual_leave) / 12)
    direct = salary_subtotal + labor_day + annual_leave + retirement
    premium_basis = direct - retirement

    insurance = {
        "건강보험": _ceil(Decimal(premium_basis) * Decimal("0.03595")),
        "장기요양보험": None,
        "산재보험": _ceil(Decimal(premium_basis) * Decimal("0.00956")),
        "국민연금": _ceil(Decimal(premium_basis) * Decimal("0.0475")),
        "고용보험": _ceil(Decimal(premium_basis) * Decimal("0.0135")),
    }
    insurance["장기요양보험"] = _ceil(
        Decimal(insurance["건강보험"]) * Decimal("0.1314")
    )
    indirect = sum(insurance.values())
    worker_expenses = {
        "피복비": 25000,
        "교육훈련비": 10000,
        "특수건강검진비": 10000,
        "복리후생비": 20000,
    }
    common_expenses = {"방재실 보안알람": 80000, "무인주차관제": 90000}
    per_worker_exp = sum(worker_expenses.values())
    common_total = sum(common_expenses.values())
    if common_cost_scope == "site":
        common_monthly = common_total
        common_per_worker = Decimal(common_total) / HEADCOUNT
    else:
        common_monthly = HEADCOUNT * common_total
        common_per_worker = Decimal(common_total)
    per_worker_admin = _ceil(Decimal(direct + indirect) * admin_rate)
    per_worker_profit = _ceil(
        (Decimal(direct + indirect + per_worker_exp) + common_per_worker)
        * profit_rate
    )
    labor_and_per_worker = HEADCOUNT * (
        direct + indirect + per_worker_exp + per_worker_admin + per_worker_profit
    )
    system_monthly = APARTMENTS * 10000
    monthly = labor_and_per_worker + common_monthly + system_monthly + relief
    annual = monthly * YEARS_MONTHS

    rows = [
        {"name":"기본급","unit":"원/인·월","amount":base,"basis":"258.55시간 × 10,320원"},
        {"name":"직책수당","unit":"원/인·월","amount":role,"basis":"실제 직책수당 입력, 기본값 0은 미확정"},
        {"name":"야간수당","unit":"원/인·월","amount":night,"basis":"(기본급+직책수당)/258.55 × 60.84시간 × 50%"},
        {"name":"근로자의날 수당","unit":"원/인·월","amount":labor_day,"basis":"(기본급+직책수당)/258.55 × 8.5시간 /12"},
        {"name":"연차수당","unit":"원/인·월","amount":annual_leave,"basis":"(기본급+직책수당)/258.55 × 8.5 × 15일/12"},
        {"name":"퇴직적립금","unit":"원/인·월","amount":retirement,"basis":"(급여소계+근로자의날+연차)/12"},
        {"name":"직접노무비 A","unit":"원/인·월","amount":direct,"basis":"항목별 원 미만 절상 합계"},
    ]
    rows += [
        {"name":name, "unit":"원/인·월","amount":v,
         "basis":{
          "건강보험":"(A-퇴직적립금)×3.595%",
          "장기요양보험":"건강보험×13.14%",
          "산재보험":"(A-퇴직적립금)×0.956%",
          "국민연금":"(A-퇴직적립금)×4.75%",
          "고용보험":"(A-퇴직적립금)×1.35%",
         }[name]}
        for name,v in insurance.items()
    ]
    rows.append({"name":"간접노무비 B","unit":"원/인·월","amount":indirect,
                 "basis":"공고 OCR 보험요율, 사업장 실제요율 미대조"})
    rows += [{"name":k,"unit":"원/인·월","amount":v,"basis":"공고 최저액"}
             for k,v in worker_expenses.items()]
    rows += [{"name":k,"unit":("원/현장·월" if common_cost_scope=="site"
                              else "원/인·월"),"amount":v,"basis":"적용 단위 원본 표 확인 전"}
             for k,v in common_expenses.items()]
    rows += [
       {"name":"일반관리비 D","unit":"원/인·월","amount":per_worker_admin,
        "basis":f"(A+B)×{admin_rate*100}% 이상"},
       {"name":"기업이윤 E","unit":"원/인·월","amount":per_worker_profit,
        "basis":f"(A+B+C)×{profit_rate*100}% 이상, 공통 제경비 배분 가정"},
       {"name":"보안시스템 운영비","unit":"원/현장·월","amount":system_monthly,
        "basis":"아파트 199세대 × 10,000원; 상가 42호실 적용 미확정"},
       {"name":"대체인력/비상교대 추가비용","unit":"원/현장·월","amount":relief,
        "basis":"실제 인력 계획 및 견적 반영 전"},
    ]
    hard_blocks = [
        "K-apt 원본 HWP 및 지정 산출내역서 파일 바이트·해시 미확보",
        "원본 산출표의 보안알람·주차관제 금액 적용 단위 미검증",
        "직책수당, 대체인력, 연차/퇴직 적립 및 보험 실비정산 방식 미확정",
        "경비업 허가, 경비지도사 재직, 세금증명, 장비, 실적, 신용평가 등 사업자 증빙 미확인",
        "기존 경비·주차·알람 연동 파트너의 실제 원가 견적 미확보",
        "견적가에 대한 VAT 처리 및 원본 양식 항목 일치 미확정",
    ]
    checks = {
        "persons":HEADCOUNT,
        "per_person_direct_krw":direct,
        "per_person_indirect_krw":indirect,
        "per_person_worker_expenses_krw":per_worker_exp,
        "common_expenses_monthly_krw":common_monthly,
        "common_scope":common_cost_scope,
        "per_person_admin_krw":per_worker_admin,
        "per_person_profit_krw":per_worker_profit,
        "labor_and_worker_monthly_krw":labor_and_per_worker,
        "system_monthly_krw":system_monthly,
        "relief_monthly_krw":relief,
        "monthly_total_krw":monthly,
        "annual_total_krw":annual,
        "tender_bond_5pct_krw":_ceil(Decimal(annual)*Decimal("0.05")),
        "performance_bond_10pct_krw":_ceil(Decimal(annual)*Decimal("0.10")),
        "reconciles": monthly == labor_and_per_worker+common_monthly+system_monthly+relief,
    }
    assert checks["reconciles"]
    return {
      "source":"public_notice_OCR_secondary_unverified_binary",
      "notice_id":NOTICE_ID,
      "official_url":ORIGIN,
      "ocr_text_url":SECONDARY_OCR,
      "validity":"DRAFT_SCENARIO_NOT_FINAL_BID",
      "bid_ready":False,
      "can_submit":False,
      "vat_status":"NOT_DETERMINED",
      "value_classification":"preliminary_cost_model_based_on_public_notice_mandated_minimums",
      "inputs":{
          "role_allowance_krw":role,
          "relief_staff_monthly_krw":relief,
          "admin_pct":str(admin_rate*100),
          "profit_pct":str(profit_rate*100),
          "common_cost_scope":common_cost_scope,
          "employees":HEADCOUNT,
          "apartments":APARTMENTS,
          "shops_excluded_pending_contract":SHOPS,
      },
      "rows":rows,
      "totals":checks,
      "hard_blocks":hard_blocks,
      "scoring_note":"적격심사 100점 중 가격 30점; 최저가 30점, "
                     "가격점수=30-[30×(입찰가-최저가)/최저가]; 다른 70점 미확정",
      "rounding":"노무비·보험·관리·이윤은 항목별 원 미만 절상, 제경비 절사",
    }


def proposal_draft() -> dict:
    """Evidence-linked bidder-neutral service method statement, not tender packet."""
    sections = [
      {"title":"1. 대상 단지 및 목적",
       "body":"보문센트럴아이파크아파트 199세대와 상가 42호실, 2개 동을 "
              "대상으로 공동주택·상가 공용부의 출입, 순찰, 비상대응 및 "
              "주차관제 업무를 통합 운영한다. 실제 도면과 상가 운영 경계는 계약 전 확인한다.",
       "evidence":"공고문 제2~3항"},
      {"title":"2. 인력 운영 및 교대",
       "body":"경비인력 2명, 24시간 격일제 2교대, 주간 휴게 3시간과 "
              "야간 휴게 4시간을 기준으로 교대표를 편성한다. "
              "연차·질병·교육·법정휴게 중 업무 공백에 대비한 "
              "대체인력 확보 인원과 실제 비용은 별도 증빙 후 기입한다.",
       "evidence":"공고문 제3항, 2026 산출내역서"},
      {"title":"3. 보안·안전 운영",
       "body":"출입 통제, 경비초소 비상신호, 영상감시, 취약구역 순찰, "
              "입주민 긴급요청 시 현장 확인·상황 전파·관계기관 신고 절차를 "
              "업무별 점검표와 인계일지로 운영한다. 기존 시스템의 "
              "연동 가능 여부는 현장 장비와 제조사 규격 확인 후 확정한다.",
       "evidence":"공고문 업무범위 가~바"},
      {"title":"4. 주차·출입 및 주민 지원",
       "body":"방문차량 등록, 외부차량 진입 통제, 무인주차관제 예외 처리, "
              "택배·우편 관리 지원, 폭설 및 분리수거 지원을 관리주체가 "
              "승인한 업무기준에 따라 수행하고 인계기록을 남긴다.",
       "evidence":"공고문 업무범위 나~마"},
      {"title":"5. 시스템 운영계획",
       "body":"경비초소 알람과 주차관제를 현장 통합표에 구분해 기록하고 "
              "경보 발생·오작동·장애 복구 시간을 관리한다. "
              "세대별 보안시스템 운영비는 공고상 세대당 1만원을 원가표에 "
              "반영하되 설비 소유권, 유지보수 범위, 연동 비용, 상가 "
              "적용 범위는 업체 견적과 계약조건을 대조한 후 확정한다.",
       "evidence":"공고문 업무범위, 2026 산출내역서"},
      {"title":"6. 교육·품질관리 및 보고",
       "body":"입사 시 현장 특성교육, 순찰·비상대응 교육, 일일 인계일지, "
              "주간 장애/출동/민원 현황, 월간 운영실적 보고를 제안한다. "
              "정량 KPI는 발주처와 계약 전 합의한다.",
       "evidence":"사업제안서 사업계획 적합성 평가항목"},
      {"title":"7. 협력업체 상생",
       "body":"경비알람, 영상감시, 주차관제, 대체인력 협력사와 장애 "
              "접수·책임범위·긴급출동·비용정산 기준을 문서화한다. "
              "현재 특정 협력업체의 계약·견적·기술역량은 검증되지 않았다.",
       "evidence":"사업제안서 상생협력 평가항목"},
      {"title":"8. 인허가·이행 증빙",
       "body":"입찰서와 지정 산출내역서, 입찰보증, 경비업 허가증·사업자등록증, "
              "법인등기부, 국세·지방세 완납증명, 장비 보유증빙, "
              "최근 1개월 이상 근무한 경비지도사 및 4대보험, "
              "공정거래·행정처분 확인서, 완료실적 및 신용등급을 순서대로 편철한다. "
              "모든 실제 회사 증빙은 수집 전이므로 제출 상태는 미완성이다.",
       "evidence":"공고문 제출서류 제6항"},
    ]
    return {
        "notice_id":NOTICE_ID,
        "document_title":"보문센트럴아이파크아파트 경비용역 사업제안서 (검토 초안)",
        "status":"DRAFT_NOT_COMPANY_VERIFIED",
        "not_final_bid":True,
        "source_urls":[ORIGIN,SECONDARY_OCR],
        "sections":sections,
        "submission_documents_ready":False,
        "application_company_confirmed":False,
        "attachment_binary_validated":False,
        "registration_or_submission_actions":0,
    }


def price_scenarios():
    """Comparable sensitivities, not a bidding recommendation."""
    variants = [
        ("공고 최저비율·공통비 현장 1회",dict()),
        ("공고 최저비율·공통비 1인당",dict(common_cost_scope="each_worker")),
        ("관리비/이윤 각 5%·공통비 현장 1회",
         dict(admin_pct="5",profit_pct="5")),
    ]
    return [
        {"scenario":name,
         "annual_krw":out["totals"]["annual_total_krw"],
         "monthly_krw":out["totals"]["monthly_total_krw"],
         "bid_ready":False,
         "inputs":out["inputs"],
         "hard_block_count":len(out["hard_blocks"])}
        for name,opts in variants
        for out in [build_price_model(**opts)]
    ]
