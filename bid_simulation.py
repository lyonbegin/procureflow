"""Evidence-gated, read-only procurement case simulation.

No browsing, vendor contact, external AI call, bidding, submission or site mutation.
All evidence comes from the existing ProcureFlow PostgreSQL records.
"""
import os
import re
from datetime import datetime
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")
TOPICS = (
    "경비", "청소", "소독", "승강기", "소방", "미화", "시설관리",
    "폐기물", "운송", "배송", "유지보수", "스토리지", "서버",
    "개발", "전산", "통신", "안전", "전기", "용역"
)
CATEGORY_MAP = {"물품": "goods", "일반용역": "service"}


def topic_for(title):
    text = str(title or "")
    return next((word for word in TOPICS if word in text), "")


def money_number(value):
    text = str(value or "").strip().replace(",", "").replace("원", "")
    return int(text) if re.fullmatch(r"\d+", text) else None


def deadline_state(value, now=None):
    now = now or datetime.now(KST)
    text = str(value or "").strip()
    try:
        if re.fullmatch(r"\d{12}", text):
            when = datetime.strptime(text, "%Y%m%d%H%M")
        elif re.fullmatch(r"\d{14}", text):
            when = datetime.strptime(text, "%Y%m%d%H%M%S")
        else:
            when = datetime.fromisoformat(text)
            if not (len(text) >= 16 and ":" in text):
                return "unverified"
        if when.tzinfo is None:
            when = when.replace(tzinfo=KST)
        return "open_by_recorded_deadline" if when > now else "past_recorded_deadline"
    except (ValueError, TypeError, OverflowError):
        return "unverified"


def stage(stage_id, state, observation, next_action):
    return {
        "id": stage_id, "state": state,
        "observation": observation, "required_next": next_action,
    }


def preview(session, source, external_id):
    if source not in ("g2b", "kapt") or not external_id or len(external_id) > 120:
        raise ValueError("Unsupported source or identifier")
    with session() as db:
        tender = db.execute("""
            SELECT source,external_id,title,agency,category,notice_date,
                   deadline,status,method,source_url,first_seen,last_seen
            FROM procureflow.tenders
            WHERE source=%s AND external_id=%s
        """, (source, external_id)).fetchone()
        if not tender:
            raise LookupError("Tender not found in the operating database")
        topic = topic_for(tender["title"])
        category = CATEGORY_MAP.get(tender["category"], "unspecified")
        # Exact agency or a named service/product topic only. Never use
        # the token '입찰' or generic tender wording as a competitive match.
        topic_expr = "%" + topic + "%" if topic else ""
        awards = db.execute("""
            SELECT bid_ntce_no,bid_ntce_ord,title,agency,company,
                   amount,participation_count,last_seen
            FROM procureflow.bid_results
            WHERE source='g2b' AND result_kind='award'
              AND category=%s
              AND (agency=%s OR (%s <> '' AND title ILIKE %s))
            ORDER BY last_seen DESC LIMIT 80
        """, (category, tender["agency"], topic, topic_expr)).fetchall()
        bid_numbers = list(dict.fromkeys(
            x["bid_ntce_no"] for x in awards if x.get("bid_ntce_no")
        ))[:80]
        participation = []
        if bid_numbers:
            participation = db.execute("""
                SELECT company,count(DISTINCT bid_ntce_no) AS appearances
                FROM procureflow.bid_results
                WHERE source='g2b' AND result_kind='opening'
                  AND bid_ntce_no = ANY(%s)
                  AND company <> ''
                GROUP BY company ORDER BY appearances DESC,company LIMIT 25
            """, (bid_numbers,)).fetchall()

    observed_prices = [money_number(x["amount"]) for x in awards]
    observed_prices = [x for x in observed_prices if x is not None]
    deadline = deadline_state(tender["deadline"])
    matched_companies = [
        {"name": x["company"], "historical_appearances": x["appearances"]}
        for x in participation
    ]
    winners = [
        {
            "bid_number": row["bid_ntce_no"], "title": row["title"],
            "agency": row["agency"], "company": row["company"],
            "amount_krw": money_number(row["amount"]),
            "recorded_participants": row["participation_count"],
            "match_reason": (
                "exact_agency" if row["agency"] == tender["agency"]
                else "shared_topic"
            ),
        }
        for row in awards[:25]
    ]
    steps = [
        stage("new_notice", "complete",
              "Stored tender record, original identity and first/last seen timestamps",
              "Refresh notices and reconcile current official detail"),
        stage("competition", "partial" if winners else "blocked",
              f"{len(awards)} confirmed G2B awards on matching agency or topic; "
              f"{len(matched_companies)} historically observed competing companies",
              "Resolve company identifiers, service size and platform differences"),
        stage("notice_and_attachments", "blocked",
              "Only headline notice data exists in the tenders table; "
              "no downloaded and parsed attachment set is registered for this case",
              "Open official tender detail; download every attachment and checksum originals"),
        stage("qualification", "blocked",
              "Full tender clauses and verified applicant licenses/certifications are absent",
              "Compare original clauses with actual company registration and certificates"),
        stage("delivery_and_suppliers", "blocked",
              "No verified work breakdown, staffing plan, supplier quotations or stock checks",
              "Assemble scope, performance plan, real partner quotations and delivery schedule"),
        stage("cost_and_price", "blocked",
              "Historical winning bid values are contextual evidence, not this tender's "
              "budget, estimated price or permissible bid amount",
              "Calculate itemized direct costs, indirect costs, VAT, margin, and bid constraints"),
        stage("gpt_analysis", "blocked",
              "Evidence package is incomplete; AI output was not generated",
              "Configure OpenAI API in Railway and run grounded analysis only "
              "after primary documents and applicant evidence are stored"),
        stage("final_documents", "blocked",
              "No completed, evidence-linked participation forms or final bid file",
              "Produce and validate all mandatory files with checklist and document hashes"),
        stage("pre_participation_gate", "blocked",
              "Stopped before visiting or clicking the real participation action",
              "Human review after all critical controls are verified"),
    ]
    return {
        "mode": "READ_ONLY_NO_SUBMISSION",
        "case": dict(tender),
        "topic": topic,
        "deadline_verification": deadline,
        "historical_competition": {
            "source": "g2b_confirmed_awards_and_opening_rows",
            "platform_cross_reference_only": source == "kapt",
            "match_rule": "exact_agency_or_shared_named_topic",
            "matched_award_count": len(awards),
            "confirmed_winners": winners,
            "historical_participants": matched_companies,
            "observed_award_amount_range_krw":
                [min(observed_prices), max(observed_prices)]
                if observed_prices else None,
            "pricing_caveat": "NOT a predicted bid price; different contracts and scope",
        },
        "ai_configuration": {
            "openai_key_present_on_api_service": bool(os.getenv("OPENAI_API_KEY")),
            "ai_invoked": False,
        },
        "stages": steps,
        "completion": {"evidence_complete": False, "bid_ready": False,
                       "button_clicked": False, "submitted": False,
                       "external_bid_actions": 0},
    }
