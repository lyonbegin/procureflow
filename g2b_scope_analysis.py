"""Exact work packages from ACTUAL saved public G2B XLSX and HWP task instructions.

No artificial quote, AI inference, hypothetical costs, or bid submission.
Quantities must be present in the XLSX; budget allocations must be checked
against the original HWP budget and top-line price before evidence is accepted.
"""
from __future__ import annotations
import re
from db import session
from g2b_case_engine import SINGLE_CASE,_ev

def norm(text):
    return " ".join((text or "").split())

def _find_budget(text,label):
    m=re.search(label+r".{0,80}?\s+([\d,]{6,})\s*(?:\n|\s|$)",text)
    return int(m.group(1).replace(",","")) if m else None

def analyze():
    with session() as db:
        docs=db.execute("""SELECT file_id,filename,url,sha256,
           extracted_text,extraction_state,source_verified
           FROM procureflow.g2b_case_documents
           WHERE bid_no=%s AND file_id IN ('official_attached_2',
                                            'official_attached_3')
           ORDER BY file_id""",(SINGLE_CASE,)).fetchall()
    found={z["file_id"]:z for z in docs
           if z["extraction_state"]=="parsed" and z["source_verified"]}
    if not all(x in found for x in ("official_attached_2","official_attached_3")):
        return {"status":"blocked_missing_parsed_worksheets_or_spec",
                "available":list(found),"estimated_costs":None}
    spec=found["official_attached_2"]
    sheet=found["official_attached_3"]
    spec_text=norm(spec["extracted_text"])
    table=sheet["extracted_text"]
    items=[]
    rules=[
      ("plasma",r"플라즈마절단기\s*모니터링시스템용\s*소프트웨어\s*개발",
       r"플라즈마절단기\s*모니터링시스템용\s*소프트웨어\s*개발"),
      ("roll",r"롤[밴벤]딩기\s*모니터링시스템용\s*소프트웨어\s*개발",
       r"롤[밴벤]딩기\s*모니터링시스템용\s*소프트웨어\s*개발")
    ]
    for key,label,budget_label in rules:
        m=re.search(label+r"\s*\t?\s*([0-9]+)\s*\t?\s*(식|대|건)",table)
        if not m:
            return {"status":"blocked_invalid_original_bill_of_quantities",
                    "missing_item":key,"file_sha256":sheet["sha256"]}
        quantity=int(m.group(1))
        match=re.search(budget_label+r"\s+([\d,]{6,})",spec_text)
        if not match:
            return {"status":"blocked_budget_allocation_not_verified",
                    "item":key,"spec_sha256":spec["sha256"]}
        allocated=int(match.group(1).replace(",",""))
        items.append({"workstream":key,"label":m.group(0).split("\t")[0][:110],
                      "quantity":quantity,"unit":m.group(2),
                      "allocated_budget_krw":allocated,
                      "is_supplier_quote":False})
    mtotal=re.search(r"예산\s*:\s*일금\s*([\d,]+)\s*원",spec_text)
    stated=int(mtotal.group(1).replace(",","")) if mtotal else None
    total=sum(x["allocated_budget_krw"] for x in items)
    if stated!=total:
        return {"status":"blocked_original_budget_mismatch",
                "stated_total":stated,"item_budget_total":total,
                "items":items}
    period=re.search(r"계약\s*체결일로부터\s*(\d+)\s*일\s*이내",spec_text)
    required=["Modbus","MQTT","PLC","대시보드","엣지 컴퓨팅",
              "소스코드","시스템","인수인계","매뉴얼"]
    present=[term for term in required if term.lower() in spec_text.lower()]
    deliverables=["전체 소스코드","개발환경 구성정보","아키텍처 설계서",
                  "데이터베이스 구조도","Modbus 주소 및 TAG 목록",
                  "MQTT Topic","사용자·관리자 운영매뉴얼"]
    observed=[term for term in deliverables if term.lower() in spec_text.lower()]
    doc_evidence={"bid_no":SINGLE_CASE,"workstreams":items,
                  "total_allocated_budget_krw":total,
                  "development_period_days":int(period.group(1)) if period else None,
                  "technology_evidence":present,"deliverables":observed,
                  "sources":[{"filename":spec["filename"],
                              "sha256":spec["sha256"],"url":spec["url"]},
                             {"filename":sheet["filename"],
                              "sha256":sheet["sha256"],"url":sheet["url"]}],
                  "actual_supplier_costs_krw":None,"actual_bid_price_krw":None}
    with session() as db:
        _ev(db,SINGLE_CASE,"bill_of_quantities","original_boQ_2_workstreams",
            True,"원본 공내역서 2개 공종·수량 확인",sheet["url"],doc_evidence)
        _ev(db,SINGLE_CASE,"scope_requirements","hwp_real_scope",
            True,"원본 과업지시서 사업범위 및 산출물",spec["url"],doc_evidence)
        _ev(db,SINGLE_CASE,"detail_original","g2b_original_4_files",
            True,"정부 원본 공고 첨부 4개 및 과업지시서",spec["url"],
            {"hwp_sha256":spec["sha256"],"xlsx_sha256":sheet["sha256"]})
    return {"status":"verified_original_scope","workstreams":items,
            "period_days":doc_evidence["development_period_days"],
            "technologies":present,"deliverables":observed,
            "supplier_quotes_available":False,
            "total_budget_krw":total}
