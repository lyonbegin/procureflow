"""Safe next-step planner for the one user-selected G2B procurement case.

The planner inspects only primary-source evidence already available for the
selected notice. A recommendation is never an acceptance decision; execution
queues AT MOST one existing worker action. It never signs or submits a bid.
"""
from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel
from g2b_feature_registry import GROUPS, GROUP_BOUNDS
from g2b_case_10y import CASE_BID, SUB10
from g2b_feature_api import (
    _case, _snapshot, notice_context, feature_contract, queue_one,
    FeatureRunRequest,
)
from db import session

router = APIRouter(prefix="/api/g2b/cases", tags=["G2B visual workflow"])

GROUP_DESCRIPTIONS = {
    "notice": "선택 공고의 공식 원본 확인",
    "detail": "원본 첨부파일 수집과 텍스트 분석",
    "history": "해당 세부품명 과거 실제 개찰·낙찰 조회",
    "matching": "10자리 세부품명 일치 검증과 경쟁업체 분석",
    "eligibility": "자격조건과 자사 보유 증빙 검증",
    "pricing": "원가·견적·가격 시나리오 검토",
    "operations": "입찰참가 직전 최종 증빙 검증",
}

# No action is automatically executed when the frontend opens.
# Steps may refresh shared collectors; they do NOT independently prove all
# 104 acceptance gates in a group.
def next_step(context: dict, evidence: set[str], documents: dict, has_official_key: bool) -> dict:
    official = bool(context.get("original_notice_verified"))
    exact_code = SUB10 in (context.get("official_detail10") or [])
    indexed = int(documents.get("files_listed") or 0)
    downloaded = bool(documents.get("all_listed_files_obtained"))
    parsed = bool(documents.get("all_documents_text_extracted"))
    if not official:
        if not has_official_key:
            return {"status": "blocked", "group": "notice",
                    "reason": "official_api_key_missing", "feature_no": None,
                    "required": ["G2B_API_KEY / DATA_GO_KR_SERVICE_KEY"]}
        return {"status": "actionable", "group": "notice",
                "feature_no": 1, "reason": "refresh_selected_official_notice",
                "expected_result": "official_original_or_verified_blocker"}
    if not exact_code:
        return {"status": "blocked", "group": "detail", "feature_no": None,
                "reason": "selected_original_10_digit_product_code_missing",
                "required": ["official_detail10"],
                "configured_code_is_not_proof": SUB10}
    if not indexed:
        return {"status": "blocked", "group": "detail", "feature_no": None,
                "reason": "official_attachment_index_missing",
                "required": ["attachment_index"],
                "guidance": "Check official notice source file URLs; do not invent a file index."}
    if not downloaded:
        return {"status": "actionable", "group": "detail", "feature_no": 29,
                "reason": "download_missing_official_attachments",
                "expected_result": "actual_stored_source_bytes_and_hashes"}
    if not parsed:
        return {"status": "actionable", "group": "detail", "feature_no": 31,
                "reason": "extract_original_document_text",
                "expected_result": "nonempty_extracted_text_or_document_blocker"}
    # Historical reference data is necessary before predictions. Do not
    # infer full 10-year coverage from partial opening/bidder rows.
    if "outcome_10years_complete" not in evidence:
        return {"status": "actionable", "group": "history", "feature_no": 50,
                "reason": "resume_exact_10_digit_10_year_outcomes",
                "expected_result": "partial_batch_with_official_provenance",
                "full_ten_year_complete_not_assumed": True}
    if not {"requirements", "company_registration", "qualification_evaluation"} <= evidence:
        return {"status": "manual_input_required", "group": "eligibility",
                "feature_no": 66, "reason": "verified_company_documents_or_qualification_missing",
                "required": sorted({"requirements", "company_registration",
                                     "qualification_evaluation"} - evidence)}
    if not {"verified_base_amount", "price_rules", "supplier_quotes", "cost_breakdown"} <= evidence:
        return {"status": "manual_input_required", "group": "pricing",
                "feature_no": 89, "reason": "original_price_or_supplier_quote_evidence_missing",
                "required": sorted({"verified_base_amount", "price_rules",
                                     "supplier_quotes", "cost_breakdown"} - evidence)}
    if "final_validation" not in evidence:
        return {"status": "manual_review_required", "group": "operations",
                "feature_no": 103, "reason": "final_manual_readiness_and_document_review"}
    return {"status": "manual_review_required", "group": "operations",
            "feature_no": 104, "reason": "final_authorized_human_approval_not_submission"}


def workflow_plan(bid_no: str) -> dict:
    _case(bid_no)
    context = notice_context(bid_no)
    snapshot = _snapshot(bid_no)
    confirmed = set(snapshot.get("verified_evidence_types") or [])
    from g2b_documents import list_documents
    from g2b_official_notices import api_key
    documents = list_documents(bid_no, context["bid_ord"])
    selected = next_step(context, confirmed, documents, bool(api_key()))
    feature_states = {x["number"]: x["acceptance_state"]
                      for x in snapshot["feature_acceptance"]}
    groups = []
    for group_id, names in GROUPS:
        start, end = GROUP_BOUNDS[group_id]
        values = [feature_states.get(number, "missing")
                  for number in range(start, end+1)]
        groups.append({
            "key": group_id, "title": GROUP_DESCRIPTIONS[group_id],
            "start": start, "end": end, "total": end-start+1,
            "verified": sum(value == "verified" for value in values),
            "partial": sum(value == "partial" for value in values),
            "missing_or_blocked": sum(value not in ("verified", "partial") for value in values),
            "complete": all(value == "verified" for value in values),
            "recommended": selected.get("group") == group_id,
        })
    with session() as con:
        jobs = con.execute("""SELECT id,config->>'feature_no' AS feature_no,
                  state,created_at,started_at
                  FROM procureflow.jobs
                  WHERE source='g2b_feature' AND config->>'bid_no'=%s
                    AND state IN ('queued','running')
                  ORDER BY id LIMIT 5""", (bid_no,)).fetchall()
    return {
        "bid_no": bid_no, "context": context,
        "groups": groups, "total_functions": 104,
        "recommended_next": selected,
        "active_jobs": [dict(row) for row in jobs],
        "allowed_to_enqueue": selected.get("status") == "actionable" and not jobs,
        "verified_evidence_types": sorted(confirmed),
        "document_summary": {
            "files_listed": documents.get("files_listed", 0),
            "files_downloaded": documents.get("files_downloaded", 0),
            "all_listed_files_obtained": documents.get("all_listed_files_obtained", False),
            "all_documents_text_extracted": documents.get("all_documents_text_extracted", False),
        },
        "automatic_bid_submission": False, "human_final_review_required": True,
        "no_new_invented_evidence": True,
    }


class AdvanceRequest(BaseModel):
    """Opt-in explicit execution, never background auto-run."""
    confirm_feature_no: int


@router.get("/{bid_no}/workflow/plan",
            summary="Actual next actionable step and its official input blockers")
def get_workflow_plan(bid_no: str):
    return workflow_plan(bid_no)


@router.post("/{bid_no}/workflow/advance",
             summary="Queue only the single recommended source-backed step")
def advance_workflow(bid_no: str, request: AdvanceRequest,
                     authorization: str | None = Header(None)):
    from main import guard
    guard(authorization)
    plan = workflow_plan(bid_no)
    step = plan["recommended_next"]
    if step["status"] != "actionable":
        raise HTTPException(409, {
            "reason": "next_step_not_automatically_executable",
            "recommended_next": step,
        })
    if plan["active_jobs"]:
        raise HTTPException(409, {
            "reason": "an_existing_selected_case_job_is_active",
            "jobs": plan["active_jobs"],
        })
    if request.confirm_feature_no != step["feature_no"]:
        raise HTTPException(409, {
            "reason": "workflow_changed_reconfirm_selected_function",
            "recommended_next": step,
        })
    queued = queue_one(bid_no, step["feature_no"],
                       FeatureRunRequest(mode="collect", parameters={}))
    return {
        **queued, "planned_group": step["group"],
        "source_bid_no": bid_no, "auto_execute_following_steps": False,
        "submitted": False, "signed": False,
        "human_approval_required": True,
    }
