"""Data-backed bid readiness, company eligibility, quote costing, and proposal draft.

A draft is not a submitted bid; it cannot be a completed final bid without
verifiable notice conditions, company evidence, documented cost and approval.
"""
from __future__ import annotations
from decimal import Decimal,InvalidOperation,ROUND_HALF_UP
from io import BytesIO
from datetime import datetime,timezone
import json
from db import session
from g2b_case_engine import SINGLE_CASE,cost_summary,readiness_check

def _d(v):
    try:
        x=Decimal(str(v))
        if not x.is_finite() or x<0:raise InvalidOperation()
        return x
    except (ValueError,InvalidOperation,TypeError):
        return None

def evaluate_eligibility(bid_no=SINGLE_CASE):
    if bid_no!=SINGLE_CASE:raise ValueError("only selected tender")
    with session() as db:
        notice=db.execute("""SELECT raw FROM procureflow.tenders
                       WHERE source='g2b' AND external_id=%s""",(bid_no,)).fetchone()
        company=db.execute("""SELECT value FROM procureflow.g2b_case_decisions
                  WHERE bid_no=%s AND kind='company' AND key='registration'""",
                  (bid_no,)).fetchone()
        ev=db.execute("""SELECT evidence_type,verified_source,structured
                FROM procureflow.g2b_case_evidence WHERE bid_no=%s
                AND evidence_type IN ('company_registration','industry_codes',
                  'region_codes','requirements','qualification_evaluation')
                """,(bid_no,)).fetchall()
    raw=notice["raw"] if notice else None
    if not isinstance(raw,dict) or raw.get("bidNtceNo")!=bid_no:
        return {"status":"unknown","bid_no":bid_no,
                "reason":"official tender detail required","passed":False}
    if not company or not isinstance(company["value"],dict):
        return {"status":"unknown","bid_no":bid_no,
                "reason":"verified company registration and qualification evidence required",
                "passed":False}
    factual={r["evidence_type"] for r in ev if r["verified_source"]}
    if not {"company_registration","requirements","qualification_evaluation"}<=factual:
        return {"status":"unknown","bid_no":bid_no,
                "reason":"missing independently verified requirement or company evidence",
                "missing":sorted({"company_registration","requirements",
                                  "qualification_evaluation"}-factual),
                "passed":False}
    qualifications=next((r["structured"] for r in ev
          if r["evidence_type"]=="qualification_evaluation" and r["verified_source"]),{})
    result=qualifications.get("result")
    if result not in ("eligible","ineligible"):
        return {"status":"unknown","bid_no":bid_no,
                "reason":"qualification evaluation must give source-backed eligible/ineligible",
                "passed":False}
    return {"status":result,"passed":result=="eligible",
            "requirements_evidence_present":True,"bid_no":bid_no}

def required_price_evidence(verified):
    """Decide whether supplier quotations are actually relevant to this tender.

    An independently sourced self-performed SW cost breakdown may replace
    external supplier quotes, but it must contain real positive labor cost.
    Never infer in-house execution from a title or absent supplier records.
    """
    core={"verified_base_amount","price_rules","cost_breakdown"}
    breakdown=verified.get("cost_breakdown",{})
    in_house=(isinstance(breakdown,dict)
       and breakdown.get("execution_model") in ("self_performed","in_house")
       and (_d(breakdown.get("labor_krw")) or 0)>0)
    return core if in_house else core|{"supplier_quotes"}


def documented_price_scenarios(bid_no=SINGLE_CASE):
    basic=cost_summary(bid_no)
    elig=evaluate_eligibility(bid_no)
    with session() as c:
        values=c.execute("""SELECT evidence_type,structured,verified_source
               FROM procureflow.g2b_case_evidence WHERE bid_no=%s
               AND evidence_type IN ('verified_base_amount','price_rules',
                    'cost_breakdown','supplier_quotes')""",(bid_no,)).fetchall()
    verified={v["evidence_type"]:v["structured"] for v in values
              if v["verified_source"] and isinstance(v["structured"],dict)}
    required=required_price_evidence(verified)
    missing=sorted(required-set(verified))
    if missing or not elig["passed"]:
        return {"status":"blocked","missing":missing,
                "eligibility":elig["status"],"current_documented_cost":basic,
                "scenarios":[],"recommended_bid_price":None}
    budget=_d(verified["verified_base_amount"].get("amount_krw"))
    floor=_d(verified["price_rules"].get("minimum_bid_ratio"))
    max_bid=_d(verified["price_rules"].get("maximum_bid_ratio"))
    costs=_d(verified["cost_breakdown"].get("total_krw"))
    vat=_d(verified["price_rules"].get("vat_ratio"))
    if None in (budget,floor,max_bid,costs,vat) or budget==0 or floor>max_bid or max_bid>1 or vat>1:
        return {"status":"blocked","missing":["price_formula_is_invalid"],
                "scenarios":[],"recommended_bid_price":None}
    scenario=[]
    for rate in (floor,(floor+max_bid)/2,max_bid):
        price=(budget*rate).quantize(Decimal("1"),rounding=ROUND_HALF_UP)
        cost_gross=(costs*(1+vat)).quantize(Decimal("1"),rounding=ROUND_HALF_UP)
        net=price-cost_gross
        scenario.append({"rate":str(rate),"bid_amount_krw":int(price),
                        "documented_cost_including_vat_krw":int(cost_gross),
                        "margin_krw":int(net),"economically_viable":net>=0})
    return {"status":"draft_computed_not_approved","scenarios":scenario,
            "recommended_bid_price":None,
            "requires_human_approval":True,"actual_submission":False}

def proposal_contents(bid_no=SINGLE_CASE):
    readiness=readiness_check(bid_no)
    with session() as db:
        details=db.execute("""SELECT title,agency,notice_date,deadline,method,
               raw FROM procureflow.tenders WHERE source='g2b' AND external_id=%s""",
               (bid_no,)).fetchone()
        docs=db.execute("""SELECT filename,sha256,extraction_state,url
                  FROM procureflow.g2b_case_documents WHERE bid_no=%s
                  ORDER BY filename LIMIT 80""",(bid_no,)).fetchall()
        ev=db.execute("""SELECT evidence_type,reference,summary,source_url,
                  verified_source FROM procureflow.g2b_case_evidence
                  WHERE bid_no=%s ORDER BY evidence_type,reference LIMIT 200""",
                  (bid_no,)).fetchall()
    return {"bid_no":bid_no,"title":details["title"] if details else "",
            "agency":details["agency"] if details else "",
            "date":details["notice_date"] if details else "",
            "deadline":details["deadline"] if details else "",
            "method":details["method"] if details else "",
            "stage":"draft_only_not_a_g2b_submission",
            "readiness":readiness,"eligibility":evaluate_eligibility(bid_no),
            "price":documented_price_scenarios(bid_no),
            "document_index":docs,"evidence_references":ev,
            "warnings":["Never assert company qualifications without evidence",
                        "Final bid forms must match original tender attachments",
                        "Manual review and bid participation remain separate"]}

def draft_docx(bid_no=SINGLE_CASE, *, contents=None, strategy=None, source_clauses=None):
    """Actual source-backed procurement review draft, never a submitted bid.

    When a Worker has already retrieved proposal/context/competition, those
    objects are reused without repeating the same upstream document requests.
    """
    from docx import Document
    from html import unescape
    data=contents if isinstance(contents,dict) else proposal_contents(bid_no)
    doc=Document()
    sec=doc.sections[0]
    doc.add_heading("입찰 사전검토 및 제출서류 준비서",0)
    doc.add_paragraph("본 문서는 제출된 입찰서가 아니라 내부 검토용 초안입니다.")
    table=doc.add_table(rows=0,cols=2);table.style="Table Grid"
    for name,key in [("공고번호","bid_no"),("공고명","title"),
                     ("발주기관","agency"),("공고일","date"),
                     ("마감일","deadline"),("계약방법","method")]:
        row=table.add_row().cells;row[0].text=name;row[1].text=str(data.get(key) or "미확보")
    for name,obj in [("입찰 참가자격 판정",data["eligibility"]),
                     ("원가 및 가격안",data["price"])]:
        doc.add_heading(name,level=1)
        doc.add_paragraph(json.dumps(obj,ensure_ascii=False,default=str,indent=2)[:7000])
    if isinstance(strategy,dict) and strategy.get("real_data_only") is True:
        observed=strategy.get("observed") or {}
        awards=strategy.get("confirmed_award_observed") or {}
        doc.add_heading("원본 검증 과거 개찰·경쟁 분석",level=1)
        doc.add_paragraph(
            "본 데이터는 선택 공고의 정확한 10자리 세부종목 원본이 확인된 과거 개찰 기록입니다. "
            "분석 범위의 모든 기록이 최종 낙찰 결과를 의미하지 않습니다.")
        for label,key in [
            ("실제 개찰기록 행","opening_rows"),
            ("원본 검증 공고차수","observed_notice_rounds"),
            ("확인된 업체명 문자열","distinct_name_strings"),
            ("투찰금액이 있는 실제 기록","rows_with_numeric_amounts"),
            ("개찰 1순위 기록(낙찰 확정 아님)","rank_one_openings_not_awards")
        ]:
            doc.add_paragraph(label+": "+str(observed.get(key,"미확인")))
        doc.add_paragraph("공식 확정 낙찰 기록: "+str(awards.get("award_rows","미확인")))
        doc.add_paragraph(
           "검색기간: "+str(strategy.get("filters",{}).get("start",""))+
           " ~ "+str(strategy.get("filters",{}).get("end","")))
        doc.add_heading("과거 경쟁업체 개찰 참가 현황",level=2)
        for row in (strategy.get("competitors_from_all_filtered_records") or [])[:12]:
            company=unescape(str(row.get("company") or ""))[:150]
            doc.add_paragraph(
               company+" · 서로 다른 공고차수 "+str(row.get("distinct_notice_rounds",0))+
               " · 개찰 행 "+str(row.get("opening_rows",0))+
               " · 개찰 1순위 "+str(row.get("rank_one_openings_not_awards",0)),
               style="List Bullet")
        doc.add_paragraph(
            "과거 수주확률 또는 추천 투찰가격은 생성하지 않았습니다. "
            "동종 계약방법·원가·가격규칙·회사 자격과 입찰 마감 여부를 별도로 검증하십시오.")
    if source_clauses:
        doc.add_heading("저장된 원본 공고·과업지시서에서 추출한 확인 문장",level=1)
        doc.add_paragraph("다음 문장은 원본 문서의 그대로 추출한 참고 항목이며, 법적 적격성 판정이 아닙니다.")
        for clause in source_clauses[:25]:
            if not clause.get("original_sha256"):continue
            doc.add_paragraph(
                str(clause.get("category") or "")+" · "+
                str(clause.get("original_filename") or "")+" · "+
                str(clause.get("text") or "")[:350]+"\n"+
                "원본 SHA256: "+str(clause["original_sha256"]),
                style="List Bullet")
    doc.add_heading("수집한 첨부 원본",level=1)
    if not data["document_index"]:doc.add_paragraph("다운로드한 첨부원본 없음.")
    for row in data["document_index"]:
        doc.add_paragraph(str(row["filename"])+
                          " / sha256="+str(row["sha256"])+
                          " / 상태="+str(row["extraction_state"]),style="List Bullet")
    doc.add_heading("확인해야 하는 미완료 요건",level=1)
    for group in data["readiness"]["phases"]:
        if not group["ready"]:
            doc.add_paragraph(group["key"]+": "+", ".join(group["missing_evidence"]),
                              style="List Bullet")
    doc.add_paragraph("투찰금액 및 참가자격 검증 완료 전에는 입찰참가·제출을 진행하지 않습니다.")
    stream=BytesIO();doc.save(stream)
    return stream.getvalue(),data
