"""Portable ORIGINAL ProcureFlow 104 feature execution/acceptance contracts.

Used by both production G2B FastAPI and isolated public-tender Studio simulation.
This module has zero DB/network calls and never enqueues a collector or bid.
A function being addressable is not proof that its collector ran successfully.
"""
from __future__ import annotations
from g2b_feature_registry import FEATURES, FEATURE_GATES
CATALOG={item["number"]:item for item in FEATURES}
assert len(CATALOG)==104
SUPPORTED_NOTICE=set(range(1,17))
SUPPORTED_HISTORY=set(range(33,61))
SUPPORTED_ELIGIBILITY=set(range(61,77))
SUPPORTED_PRICING=set(range(77,95))
SUPPORTED_OPERATIONS=set(range(95,105))
HISTORY_PARAMS={
 "candidate_limit":{"type":"integer","minimum":1,"maximum":4,"default":4,
                    "description":"Number of original-detail candidates to inspect in this run"},
 "opening_limit":{"type":"integer","minimum":1,"maximum":2,"default":2,
                  "description":"Number of verified opening details to inspect"}
}
FILE_PARAMS={"file_id":{"type":"string","maxLength":150,
 "description":"Optional specific attachment ID; omitted means process listed originals"}}

def contract_params(number: int) -> dict:
    if number in SUPPORTED_HISTORY:
        return HISTORY_PARAMS
    if number == 29:
        return FILE_PARAMS
    return {}


def collection_action(number: int) -> str:
    if number in SUPPORTED_NOTICE or 17 <= number <= 23:
        return "refresh_selected_official_notice"
    if number in (28, 30):
        return "list_original_attachments"
    if number == 29:
        return "download_original_attachments"
    if number in (31, 32):
        return "extract_original_documents"
    if number in SUPPORTED_HISTORY:
        return "collect_exact_ten_digit_outcomes"
    if number in SUPPORTED_ELIGIBILITY:
        return "evaluate_company_eligibility"
    if number in SUPPORTED_PRICING:
        return "evaluate_cost_or_proposal"
    if number in SUPPORTED_OPERATIONS:
        return "evaluate_readiness"
    return "verify_stored_evidence"


def feature_contract(number: int, context: dict, snapshot: dict) -> dict:
    item = CATALOG[number]
    found = next(x for x in snapshot["feature_acceptance"] if x["number"] == number)
    accepted = set(snapshot.get("verified_evidence_types") or ())
    gate = list(FEATURE_GATES[number])
    done = [x for x in gate if x in accepted]
    not_done = [x for x in gate if x not in accepted]
    action = collection_action(number)
    return {
        "number": number, "name": item["label"], "group": item["group"],
        "source_bid_no": context["bid_no"], "source_bid_ord": context["bid_ord"],
        "endpoint": f"/api/g2b/cases/{context['bid_no']}/features/{number}",
        "execute_endpoint": f"/api/g2b/cases/{context['bid_no']}/features/{number}/run",
        "runs_endpoint": f"/api/g2b/cases/{context['bid_no']}/features/{number}/runs",
        "input_contract": {
            "method": "POST", "body": {"mode": "collect", "parameters": {}},
            "parameters": contract_params(number),
            "additional_properties_allowed": False,
            "auto_from_selected_notice": [
                {"name": "bid_no", "value": context["bid_no"], "source": "selected_notice"},
                {"name": "bid_ord", "value": context["bid_ord"], "source": "selected_notice"},
                {"name": "title", "value": context["title"], "source": "selected_notice"},
                {"name": "agency", "value": context["agency"], "source": "official_notice"},
                {"name": "agency_code", "value": context["agency_code"], "source": "official_notice"},
                {"name": "deadline", "value": context["deadline"], "source": "official_notice"},
                {"name": "detail10", "value": context["official_detail10"], "source": "official_classification"},
                {"name": "parent8", "value": context["official_parent8"], "source": "official_classification"},
            ],
            "required_verified_evidence": gate,
            "missing_verified_evidence": not_done,
            "manual_material_entry_endpoint": "/api/g2b/full/evidence",
            "company_or_cost_draft_entry_endpoint": "/api/g2b/full/decision",
            "manual_input_does_not_verify_original": True,
        },
        "execution": {
            "action": action,
            "execution_kind": ("evidence_check_only" if action == "verify_stored_evidence" else "shared_existing_collector_or_evaluator"),
            "business_acceptance_requires_independent_evidence": True,
            "explanation": "Only individually verified evidence gates determine acceptance. "
                           "Shared source collectors may refresh facts for several functions.",
            "never_submit_bid": True,
        },
        "output_contract": {
            "GET": ["number", "name", "input_contract", "execution", "observation",
                    "acceptance_state", "verified_evidence", "missing_evidence", "source_context"],
            "POST": ["job_id", "job_status", "feature_no", "source_bid_no", "status_url"],
            "job_result": ["feature_no", "source_bid_no", "action", "state",
                           "acceptance_state", "missing_evidence", "collector_result"],
        },
        "acceptance_state": found["acceptance_state"],
        "verified_evidence": done, "missing_evidence": not_done,
    }

