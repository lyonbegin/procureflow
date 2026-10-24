"""Read-only, per-function observed outputs for a single selected G2B tender.

Each of the 104 IDs has its own data source and projected output. These
observations NEVER set acceptance flags: independent evidence gates in
g2b_case_engine still decide verified/missing. Missing rows mean 'not found',
not 'zero bidders' or 'completed'. Company quotes are represented by draft
record identifiers, not private documents or prices, on public GET routes.
"""
from __future__ import annotations
from collections import Counter
from datetime import date, datetime
from typing import Any

from db import session
from g2b_case_10y import CASE_BID, CASE_ORD, CAT8, SUB10, BEGIN, END
from g2b_feature_registry import FEATURES


# Every ordinal has its own observable data contract (domain, measure).
SELECTORS = dict(enumerate((
    # 1-16: notice ingestion and changes
    ("sync", "actual_notice_count"), ("sync", "synchronization_windows"),
    ("notice", "bidNtceNo"), ("notice", "bidNtceOrd"),
    ("notice", "bidNtceDt"), ("notice", "bidClseDt"),
    ("notice", "bidNtceNm"), ("notice", "ntceInsttNm"),
    ("notice", "bidMethdNm"), ("classification", "official_codes"),
    ("notice", "bidNtceNo"), ("revisions", "notice_status"),
    ("revisions", "observed_changes"), ("revisions", "revision_history"),
    ("revisions", "duplicate_revisions"), ("jobs", "discovery_jobs"),
    # 17-32: original detail and attachments
    ("notice", "original_notice"), ("notice", "raw_document"),
    ("classification", "detail10"), ("notice", "ntceInsttCd"),
    ("notice", "cntrctCnclsMthdNm"), ("notice", "scsbidMthdNm"),
    ("notice", "budget_components"), ("notice", "region_restrictions"),
    ("notice", "industry_requirements"), ("notice", "company_restrictions"),
    ("notice", "delivery_terms"), ("documents", "index"),
    ("documents", "downloaded"), ("documents", "integrity"),
    ("documents", "extraction"), ("documents", "reconciliation"),
    # 33-48: historical official bid/opening/award evidence
    ("outcomes", "opening_rows"), ("outcomes", "bidder_companies"),
    ("outcomes", "bid_amounts"), ("outcomes", "bid_rates"),
    ("outcomes", "bid_ranks"), ("outcomes", "confirmed_awards"),
    ("outcomes", "final_award_amounts"), ("outcomes", "business_identifiers"),
    ("outcomes", "duplicate_keys"), ("outcomes", "reopen_rounds"),
    ("outcomes", "original_identifiers"), ("outcomes", "freshness"),
    ("outcomes", "backfill"), ("outcomes", "ten_year_coverage"),
    ("outcomes", "notice_linkage"), ("outcomes", "selected_notice_linkage"),
    # 49-60: exact 10-digit category and same-agency analysis
    ("classification", "detail10"), ("outcomes", "exact_opening_coverage"),
    ("outcomes", "exact_award_coverage"), ("outcomes", "legacy_and_new"),
    ("windows", "monthly_windows"), ("outcomes", "ten_year_coverage"),
    ("outcomes", "bidder_rank_summary"), ("outcomes", "award_reconciliation"),
    ("outcomes", "same_agency_openings"), ("outcomes", "same_agency_awards"),
    ("outcomes", "repeat_companies"), ("outcomes", "source_report"),
    # 61-76: qualification, supply and quotations
    ("qualification", "required_qualifications"), ("decisions", "company_registration"),
    ("qualification", "region_check"), ("qualification", "company_size"),
    ("qualification", "licenses"), ("qualification", "eligibility"),
    ("qualification", "joint_bidding"), ("qualification", "bid_guarantee"),
    ("qualification", "required_documents"), ("decisions", "qualification_documents"),
    ("suppliers", "supplier_directory"), ("suppliers", "product_capabilities"),
    ("suppliers", "delivery_feasibility"), ("decisions", "quote_requests"),
    ("decisions", "supplier_quotes"), ("decisions", "quote_comparison"),
    # 77-94: sourced prices and documents
    ("notice", "base_amount"), ("notice", "budget_components"),
    ("documents", "quantity_sheets"), ("decisions", "quotation_costs"),
    ("decisions", "labor_costs"), ("decisions", "material_costs"),
    ("decisions", "overhead_profit"), ("decisions", "tax"),
    ("decisions", "total_cost"), ("outcomes", "comparable_award_amounts"),
    ("outcomes", "historical_bid_rate_distribution"), ("notice", "bid_floor"),
    ("pricing", "price_scenarios"), ("pricing", "profitability"),
    ("pricing", "approved_price"), ("proposal", "proposal_draft"),
    ("proposal", "submission_forms"), ("proposal", "final_package"),
    # 95-104: state and operations
    ("operations", "selected_case"), ("operations", "phase_progress"),
    ("operations", "worker_jobs"), ("operations", "errors_and_logs"),
    ("operations", "case_ownership"), ("operations", "evidence_index"),
    ("operations", "pause_resume"), ("operations", "approvals_retries"),
    ("operations", "manual_ready"), ("operations", "final_validation"),
), 1))
assert len(SELECTORS) == len(FEATURES) == 104
assert set(SELECTORS) == set(range(1, 105))


_NOTICE_FIELDS = {
    "bidNtceNo": ("bidNtceNo",),
    "bidNtceOrd": ("bidNtceOrd",),
    "bidNtceDt": ("bidNtceDt",),
    "bidClseDt": ("bidClseDt", "bidClseTm"),
    "bidNtceNm": ("bidNtceNm",),
    "ntceInsttNm": ("ntceInsttNm", "dminsttNm", "ntceInsttCd"),
    "bidMethdNm": ("bidMethdNm", "bidMethd", "bidNtceSttusNm"),
    "ntceInsttCd": ("ntceInsttCd",),
    "cntrctCnclsMthdNm": ("cntrctCnclsMthdNm",),
    "scsbidMthdNm": ("scsbidMthdNm", "scsbidMthdCd"),
    "budget_components": ("asignBdgtAmt", "bdgtAmt", "presmptPrce", "bssamt", "prearngPrce",
                          "vatAmt"),
    "region_restrictions": ("rgnLmtYn", "prtcptPsblRgnNm", "prtcptPsblRgnCd"),
    "industry_requirements": ("indstrytyCd", "indstrytyNm", "bidQlfctRgstDt"),
    "company_restrictions": ("smlpzGrtyYn", "smlpzGrtyRgstYn", "cnstrtsiteRgnNm"),
    "delivery_terms": ("dlvrTmlmtDt", "dlvrTmlmt", "dlvrPlce", "fulflDmanNtn"),
    "base_amount": ("bssamt", "asignBdgtAmt", "bdgtAmt", "presmptPrce"),
    "bid_floor": ("scsbidLwltRate", "sucsfbidLwltRate"),
    "notice_status": ("bidNtceSttusNm", "ntceKindNm", "bidNtceOrd"),
}


def _official_notice(bid_no: str) -> dict:
    with session() as db:
        row = db.execute("""SELECT raw,source_url,title,agency,deadline,
                                notice_date,last_seen FROM procureflow.tenders
                         WHERE source='g2b' AND external_id=%s""",
                         (bid_no,)).fetchone()
    if not row or not isinstance(row["raw"], dict):
        return {}
    raw = row["raw"]
    if raw.get("bidNtceNo") != bid_no:
        return {}
    return raw


def _compact_dict(row: Any, allowed: tuple[str, ...]) -> dict:
    if row is None:
        return {}
    return {name: row[name] for name in allowed if name in row and row[name] not in (None, "")}


def _notice_data(bid_no: str, measure: str) -> dict:
    raw = _official_notice(bid_no)
    if not raw:
        return {"data": None, "source": "official_g2b_notice",
                "reason": "selected_official_notice_not_in_database"}
    if measure == "original_notice":
        return {"data": {"bidNtceNo": bid_no, "bidNtceOrd": raw.get("bidNtceOrd", CASE_ORD),
                         "source": "official_g2b"},
                "source": "procureflow.tenders.raw"}
    if measure == "raw_document":
        return {"data": {"bidNtceNo": bid_no, "field_count": len(raw),
                         "available_keys": sorted(k for k in raw.keys() if not k.lower().endswith("key"))[:60]},
                "source": "procureflow.tenders.raw",
                "note": "Raw original stored in DB; response excludes sensitive fields"}
    fields = _NOTICE_FIELDS.get(measure, ())
    data = _compact_dict(raw, fields)
    return {"data": data or None, "source": "procureflow.tenders.raw",
            "reason": None if data else "official_fields_not_supplied"}


def _sync_data(measure: str) -> dict:
    from g2b_official_notices import sync_status
    status = sync_status()
    if measure == "actual_notice_count":
        value = {"official_bid_notice_rows": status["actual_new_style_notice_rows"],
                 "not_equivalent_to_order_requests": True}
    else:
        value = {"windows": status["sync_by_state"],
                 "recent": status["recent_windows"], "configured_key": status["configured_key"]}
    return {"data": value, "source": "procureflow.g2b_notice_sync"}


def _classification_data(bid_no: str, measure: str) -> dict:
    with session() as db:
        rows = db.execute("""SELECT code_type,code,evidence_level,source_uri
              FROM procureflow.g2b_notice_categories
              WHERE bid_no=%s AND bid_ord=%s ORDER BY code_type,code""",
                          (bid_no, CASE_ORD)).fetchall()
    verified = [dict(row) for row in rows if row["evidence_level"] == "official_direct"]
    if measure == "detail10":
        verified = [r for r in verified if r["code_type"] == "detail10" and len(r["code"]) == 10]
    return {"data": verified if verified else None,
            "source": "procureflow.g2b_notice_categories",
            "source_verified": bool(verified),
            "configured_parent8_not_proof": CAT8,
            "configured_detail10_not_proof": SUB10}


def _revisions_data(bid_no: str, measure: str) -> dict:
    with session() as db:
        rows = db.execute("""SELECT bid_ord,content_sha,category,published_at,
                captured_at,source_uri,raw FROM procureflow.g2b_notice_revisions
                WHERE bid_no=%s ORDER BY captured_at DESC LIMIT 40""",
                          (bid_no,)).fetchall()
    projections = []
    for r in rows:
        projections.append({
            "round": r["bid_ord"], "content_sha": r["content_sha"],
            "category": r["category"], "published_at": r["published_at"],
            "captured_at": r["captured_at"], "source_uri": r["source_uri"],
            "official_status": _compact_dict(r["raw"] or {}, _NOTICE_FIELDS["notice_status"])
        })
    hashes = [r["content_sha"] for r in rows]
    if measure == "notice_status":
        value = projections[:5]
    elif measure == "observed_changes":
        value = {"distinct_originals": len(set(hashes)), "change_detected": len(set(hashes)) > 1}
    elif measure == "duplicate_revisions":
        value = {"stored_revisions": len(rows), "distinct_hashes": len(set(hashes))}
    else:
        value = projections
    return {"data": value if rows else None,
            "source": "procureflow.g2b_notice_revisions",
            "reason": None if rows else "no_official_revision_history"}


def _documents_data(bid_no: str, measure: str) -> dict:
    from g2b_documents import list_documents
    status = list_documents(bid_no, CASE_ORD)
    index = [dict(x) for x in status["original_index"]]
    docs = [dict(x) for x in status["downloaded"]]
    downloaded_ids = {x["file_id"] for x in docs}
    file_count = len(index)
    # A record with no bytes or sha is NOT an acquired, integrity-verified file.
    good = [x for x in docs if x.get("sha256") and (x.get("size_bytes") or 0) > 0
            and x.get("file_id") in {s["file_id"] for s in index}]
    parsed = [x for x in good if x.get("extraction_state") == "parsed" and
              (x.get("extracted_chars") or 0) > 0]
    if measure == "index":
        data = {"count": file_count, "files": [
            {"id": x["file_id"], "label": x["file_label"], "state": x["state"],
             "url": x["source_url"]} for x in index]}
    elif measure == "downloaded":
        data = {"indexed": file_count, "downloaded": len(good),
                "files": [{"id": x["file_id"], "name": x["filename"],
                           "sha256": x["sha256"], "size": x["size_bytes"]}
                          for x in good],
                "missing_file_ids": [x["file_id"] for x in index if x["file_id"] not in downloaded_ids]}
    elif measure == "integrity":
        data = {"indexed": file_count, "bytes_and_sha_present": len(good),
                "all_files_integrity_observed": file_count > 0 and file_count == len(good),
                "revision_archive_verified": False}
    elif measure == "extraction":
        data = {"indexed": file_count, "binary_verified": len(good),
                "parsed_with_nonempty_text": len(parsed),
                "all_parsed": file_count > 0 and file_count == len(parsed)}
    elif measure == "quantity_sheets":
        data = {"candidate_spreadsheets": [
            {"file_id": x["file_id"], "filename": x["filename"],
             "extracted_chars": x.get("extracted_chars", 0)}
            for x in docs if str(x["filename"]).lower().endswith((".xlsx", ".xls", ".csv"))],
            "bill_of_quantities_verified": False}
    else:
        data = {"listed": file_count, "downloaded_with_bytes_and_hash": len(good),
                "missing_originals": [x["file_id"] for x in index
                                      if x["file_id"] not in downloaded_ids],
                "full_original_and_attachment_reconciliation_verified": False}
    return {"data": data, "source": "procureflow.g2b_notice_source_files+g2b_case_documents",
            "zero_is_not_complete": True}


def _history_data(measure: str, context: dict) -> dict:
    from g2b_exact_outcome_history import actual_result_status
    from g2b_case_10y import status as history_status
    selected = context["bid_no"]
    if selected != CASE_BID:
        raise ValueError("only selected case")
    outcome = actual_result_status(100)
    summary = outcome["verified_exact_code_history_and_result_counts"]
    rows = [dict(x) for x in outcome["actual_opening_and_award_rows"]]
    opening = [r for r in rows if r["result_kind"] == "opening"]
    award = [r for r in rows if r["result_kind"] == "award"]
    compact = lambda r: {"notice_no": r["bid_ntce_no"], "round": r["bid_ntce_ord"],
       "company": r["company"], "amount": r["amount"], "rate": r["rate"],
       "rank": r["rank"], "status": r["result_status"], "kind": r["result_kind"],
       "date": r["historical_notice_date"], "source": r["detail_code_original_url"]}
    companies = [r["company"] for r in opening if r.get("company")]
    common = {"exact_product_code": SUB10,
              "period": [BEGIN.isoformat(), END.isoformat()],
              "coverage_complete": False,
              "verified_rounds": summary["verified_notice_rounds"],
              "sample_size_limit": 100,
              "notice_candidates_are_not_actual_outcomes": True}
    if measure in ("opening_rows", "notice_linkage", "selected_notice_linkage"):
        value = {"rows": [compact(r) for r in opening], "row_count_in_database": summary["opening_bidder_rows"]}
    elif measure in ("bidder_companies", "bidder_rank_summary", "repeat_companies"):
        value = {"company_occurrences_in_sample": Counter(companies).most_common(25),
                 "opening_rows_in_database": summary["opening_bidder_rows"]}
    elif measure == "bid_amounts":
        value = {"amount_rows": [compact(r) for r in opening if r.get("amount")],
                 "total_amount_rows": summary["opening_amount_rows"]}
    elif measure == "bid_rates" or measure == "historical_bid_rate_distribution":
        value = {"rates_observed_in_sample": [
                    {"company": r["company"], "rate": r["rate"], "notice_no": r["bid_ntce_no"]}
                    for r in opening if r.get("rate")],
                 "sample_covers_10y": False}
    elif measure == "bid_ranks":
        value = {"ranks": [compact(r) for r in opening if r.get("rank")]}
    elif measure in ("confirmed_awards", "final_award_amounts", "comparable_award_amounts",
                     "award_reconciliation"):
        value = {"rows": [compact(r) for r in award],
                 "confirmed_award_rows": summary["confirmed_award_rows"],
                 "not_a_complete_ten_year_award_universe": True}
    elif measure == "business_identifiers":
        value = {"identifiers_exposed": False, "reason": "company labels are not authoritative business IDs",
                 "verified_company_registry": False}
    elif measure == "duplicate_keys":
        ids = [f"{r['bid_ntce_no']}:{r['bid_ntce_ord']}:{r['record_key']}" for r in rows]
        value = {"duplicate_record_keys_in_sample": len(ids) - len(set(ids)),
                 "all_source_duplicates_verified": False}
    elif measure in ("reopen_rounds", "legacy_and_new"):
        ids = {(r["bid_ntce_no"], r["bid_ntce_ord"]) for r in rows}
        value = {"rounds_in_sample": len(ids),
                 "legacy_notices_in_sample": sum(not x[0].startswith("R") for x in ids),
                 "modern_notices_in_sample": sum(x[0].startswith("R") for x in ids),
                 "full_legacy_history_verified": False}
    elif measure == "original_identifiers":
        value = {"originals": [{"bid_no": r["bid_ntce_no"],
                  "round": r["bid_ntce_ord"], "sha256": r["detail_code_original_sha256"]}
                 for r in rows[:50]]}
    elif measure == "freshness":
        value = {"recent_attempts": outcome["recent_collection_attempts"],
                 "scheduled_recheck_proven": False}
    elif measure in ("backfill", "ten_year_coverage",
                     "exact_opening_coverage", "exact_award_coverage"):
        value = {"10_years_complete": False, "known_opening_rows": summary["opening_bidder_rows"],
                 "known_award_rows": summary["confirmed_award_rows"],
                 "historical_coverage": history_status(1)["monthly_window_states"]}
    elif measure in ("same_agency_openings", "same_agency_awards"):
        if not context.get("original_notice_verified") or not context.get("agency"):
            value = {"agency": None, "reason": "official_selected_agency_required"}
        else:
            source = opening if measure == "same_agency_openings" else award
            value = {"agency": context["agency"], "matching_rows": [
                     compact(r) for r in source if r.get("agency") == context["agency"]],
                     "not_complete": True}
    elif measure == "source_report":
        value = {"verified_rounds": summary["verified_notice_rounds"],
                 "opening_rows": summary["opening_bidder_rows"],
                 "award_rows": summary["confirmed_award_rows"],
                 "complete_ten_year_report": False}
    else:
        value = {"verified_result_counts": summary,
                 "missing_full_history": True}
    return {"data": {**common, **value}, "source": "official-original-verified exact detail10 G2B outcomes",
            "note": "First 100 historical actual-result rows only; 10-year exhaustive coverage NOT confirmed"}


_DECISION_TYPES = {
    "company_registration": ("company",), "qualification_documents": ("eligibility", "company"),
    "quote_requests": ("supplier", "quote"), "supplier_quotes": ("quote",),
    "quote_comparison": ("quote", "cost"), "quotation_costs": ("quote", "cost"),
    "labor_costs": ("staffing", "cost"), "material_costs": ("supplier", "cost"),
    "overhead_profit": ("cost",), "tax": ("cost",), "total_cost": ("cost",),
    "approved_price": ("bid_price", "approval"),
}


def _decision_data(bid_no: str, measure: str) -> dict:
    kinds = _DECISION_TYPES.get(measure, ("company", "eligibility", "supplier", "quote"))
    with session() as db:
        rows = db.execute("""SELECT kind,key,state,origin,updated_at
             FROM procureflow.g2b_case_decisions WHERE bid_no=%s AND kind=ANY(%s)
             ORDER BY kind,key LIMIT 100""", (bid_no, list(kinds))).fetchall()
    return {"data": {"draft_count": len(rows), "draft_records": [dict(x) for x in rows],
                     "source_verified": False,
                     "draft_is_not_eligibility_or_approved_price": True},
            "source": "procureflow.g2b_case_decisions"}


def _qualification_data(bid_no: str, measure: str, context: dict) -> dict:
    from g2b_bid_package import evaluate_eligibility
    from g2b_case_engine import MATERIAL_TYPES
    with session() as db:
        rows = db.execute("""SELECT evidence_type,reference,source_url,verified_source,
                         summary,recorded_at FROM procureflow.g2b_case_evidence
                         WHERE bid_no=%s ORDER BY recorded_at DESC LIMIT 150""",
                          (bid_no,)).fetchall()
    evidence = [{"type": r["evidence_type"], "ref": r["reference"],
                 "source_url": r["source_url"], "verified_source": r["verified_source"]}
                for r in rows if r["verified_source"] and r["evidence_type"] in MATERIAL_TYPES]
    if measure == "eligibility":
        value = evaluate_eligibility(bid_no)
    else:
        value = {"related_verified_evidence": evidence[:45],
                 "specific_requirement_evidence_missing": not bool(evidence),
                 "qualification_not_assumed": True}
    return {"data": value, "source": "procureflow.g2b_case_evidence",
            "observed_evidence_count": len(evidence)}


def _suppliers_data(measure: str) -> dict:
    with session() as db:
        rows = db.execute("""SELECT s.id,s.name,COUNT(c.id) AS certifications
               FROM procureflow.suppliers s LEFT JOIN procureflow.certifications c
               ON c.supplier_id=s.id GROUP BY s.id,s.name ORDER BY s.id DESC LIMIT 40""").fetchall()
    return {"data": {"suppliers": [{"id": r["id"], "name": r["name"],
                   "certification_count": r["certifications"]} for r in rows],
                   "bid_specific_capability_confirmed": False,
                   "bid_specific_quotation_confirmed": False},
            "source": "procureflow.suppliers+certifications"}


def _pricing_data(bid_no: str, measure: str) -> dict:
    from g2b_bid_package import documented_price_scenarios
    result = documented_price_scenarios(bid_no)
    if measure == "approved_price":
        data = {"approved_bid_price": None, "needs_final_approval": True,
                "evidence_pricing_status": result["status"]}
    elif measure == "profitability":
        data = {"status": result["status"],
                "sourced_scenario_count": len(result.get("scenarios") or []),
                "profitability_verified": False}
    else:
        data = {"status": result["status"], "scenarios": result.get("scenarios", []),
                "recommended_bid_price": None,
                "actual_submission": False}
    return {"data": data, "source": "g2b_bid_package.documented_price_scenarios"}


def _proposal_data(bid_no: str, measure: str) -> dict:
    from g2b_bid_package import proposal_contents
    result = proposal_contents(bid_no)
    data = {"title": result["title"], "draft_status": result["stage"],
            "original_attachments": [
                {"name": x["filename"], "sha256": x["sha256"],
                 "extraction_state": x["extraction_state"]}
                for x in result["document_index"][:20]],
            "warnings": result["warnings"],
            "ready": result["readiness"]["status"] == "ready",
            "actual_submission": False}
    if measure == "final_package":
        data["final_package_verified"] = False
    if measure == "submission_forms":
        data["submitted_forms_validated"] = False
    return {"data": data, "source": "g2b_bid_package.proposal_contents"}


def _ops_data(bid_no: str, measure: str) -> dict:
    with session() as db:
        control = db.execute("""SELECT bid_no,bid_ord,category8,state,selected_at,updated_at
                  FROM procureflow.g2b_case_control WHERE bid_no=%s""",
                             (bid_no,)).fetchone()
        jobs = db.execute("""SELECT id,source,state,checked,added,last_error,created_at,
                         finished_at FROM procureflow.jobs
                         WHERE config->>'bid_no'=%s
                         ORDER BY id DESC LIMIT 50""", (bid_no,)).fetchall()
        runs = db.execute("""SELECT id,phase,state,error,created_at,finished_at
                 FROM procureflow.g2b_case_runs WHERE bid_no=%s
                 ORDER BY id DESC LIMIT 50""", (bid_no,)).fetchall()
        ev = db.execute("""SELECT evidence_type,reference,source_url,verified_source
                FROM procureflow.g2b_case_evidence
                WHERE bid_no=%s ORDER BY evidence_type LIMIT 100""",
                        (bid_no,)).fetchall()
    ctl = dict(control) if control else {}
    if measure == "selected_case":
        value = ctl
    elif measure == "phase_progress":
        value = {"runs": [dict(r) for r in runs[:20]]}
    elif measure == "worker_jobs":
        value = {"jobs": [dict(j) for j in jobs[:20]], "worker_execution_not_assumed": True}
    elif measure == "errors_and_logs":
        value = {"errors": [dict(j) for j in jobs if j["last_error"]][:20],
                 "run_errors": [dict(r) for r in runs if r["error"]][:20]}
    elif measure == "case_ownership":
        value = {"selected_case": bid_no, "is_single_case": bid_no == CASE_BID,
                 "worker_owner_lease_confirmed": False}
    elif measure == "evidence_index":
        value = {"original_evidence_index": [dict(e) for e in ev],
                 "verified_evidence_count": sum(bool(e["verified_source"]) for e in ev)}
    elif measure == "pause_resume":
        value = {"state": ctl.get("state"), "state_controls_verified": False}
    elif measure == "approvals_retries":
        value = {"recent_failed_jobs": sum(x["state"] == "failed" for x in jobs),
                 "manual_approval_verified": False}
    elif measure == "manual_ready":
        value = {"ready_for_manual_participation": ctl.get("state") == "ready_for_manual_participation",
                 "not_an_electronic_submission": True}
    else:
        value = {"final_validations": [dict(r) for r in runs if r["phase"] == "readiness"][:10],
                 "validated_104_individually": False}
    return {"data": value, "source": "procureflow.g2b_case_control/jobs/runs/evidence"}


def _jobs_data(bid_no: str, measure: str) -> dict:
    with session() as db:
        rows = db.execute("""SELECT id,source,state,checked,added,created_at,finished_at
                 FROM procureflow.jobs WHERE config->>'bid_no'=%s
                 ORDER BY id DESC LIMIT 30""", (bid_no,)).fetchall()
    value = [dict(r) for r in rows]
    if measure == "discovery_jobs":
        value = [x for x in value if x["source"] in ("g2b_full_case", "g2b_feature")]
    return {"data": value or None, "source": "procureflow.jobs"}


def _windows_data(bid_no: str) -> dict:
    with session() as db:
        rows = db.execute("""SELECT first_day,last_day,status,matched,checked,page_cursor,
                         last_error,updated_at FROM procureflow.g2b_case_10yr_windows
                         WHERE case_bid_no=%s ORDER BY first_day""",(bid_no,)).fetchall()
    complete = sum(x["status"] == "completed" for x in rows)
    return {"data": {"months_registered": len(rows), "months_completed": complete,
                     "windows": [dict(r) for r in rows[:121]],
                     "official_10_year_outcome_coverage_verified": False},
            "source": "procureflow.g2b_case_10yr_windows",
            "notice_month_completion_is_not_outcome_completion": True}


def feature_observation(number: int, context: dict) -> dict:
    """Return actual measured output for an individual feature, or a truthful blocker."""
    bid_no = context["bid_no"]
    if bid_no != CASE_BID or number not in SELECTORS:
        raise ValueError("unsupported selected notice or feature")
    domain, measure = SELECTORS[number]
    try:
        if domain == "notice":
            result = _notice_data(bid_no, measure)
        elif domain == "sync":
            result = _sync_data(measure)
        elif domain == "classification":
            result = _classification_data(bid_no, measure)
        elif domain == "revisions":
            result = _revisions_data(bid_no, measure)
        elif domain == "documents":
            result = _documents_data(bid_no, measure)
        elif domain == "outcomes":
            result = _history_data(measure, context)
        elif domain == "windows":
            result = _windows_data(bid_no)
        elif domain == "decisions":
            result = _decision_data(bid_no, measure)
        elif domain == "qualification":
            result = _qualification_data(bid_no, measure, context)
        elif domain == "suppliers":
            result = _suppliers_data(measure)
        elif domain == "pricing":
            result = _pricing_data(bid_no, measure)
        elif domain == "proposal":
            result = _proposal_data(bid_no, measure)
        elif domain == "operations":
            result = _ops_data(bid_no, measure)
        elif domain == "jobs":
            result = _jobs_data(bid_no, measure)
        else:
            result = {"data": None, "reason": "unsupported_observation_source"}
    except Exception as exc:
        # Report a failure as a failure, never substitute fake zeroes.
        return {"feature_no": number, "measure": measure, "domain": domain,
                "status": "source_error", "error_type": type(exc).__name__,
                "message": str(exc)[:180], "data": None,
                "independent_acceptance": False}
    available = result.get("data") is not None
    return {
        "feature_no": number, "measure": measure, "domain": domain,
        "status": "observed" if available else "missing",
        "source": result.get("source", ""),
        "data": result.get("data"),
        "notes": {k: v for k, v in result.items() if k not in ("data", "source")},
        "independent_acceptance": False,
        "bid_submission_performed": False,
    }
