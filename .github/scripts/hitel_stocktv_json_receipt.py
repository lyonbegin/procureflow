"""Validate the ONE received stock-tv JSON, without using browser UI-completion signals.

Only the expected source IDs/order and the actual JSON content determine whether
the response is ready. Other HITEL workloads keep their existing detector.
No network request, ChatGPT send, or DOM control is performed here.
"""
from __future__ import annotations

import json
import re

SCHEMA = "TV-TRADE-EVIDENCE-10-v2"
CASE_TYPES = {"EXECUTED_TRADE", "MARKET_TRANSACTION_EVENT", "HISTORICAL_DATA_BACKTEST"}
ACCESS = {"FULL_TEXT", "ABSTRACT_ONLY", "PUBLIC_SUMMARY"}
STATUSES = {"SEARCHED", "PARTIAL", "NO_WEB_ACCESS"}
CASE_FIELDS = (
    "title", "publisher", "document_url", "instrument", "trade_period",
    "transaction_evidence", "entry_exit", "reported_numbers",
    "economic_mechanism", "evidence_location", "relationship_to_source", "limitations",
)


def _expected_from_sent_prompt(sent_prompt):
    """Get immutable batch identity from the actual request payload, not the UI."""
    if not isinstance(sent_prompt, str) or "원본:" not in sent_prompt or SCHEMA not in sent_prompt:
        return None
    try:
        payload = sent_prompt.split("원본:", 1)[1].lstrip()
        originals, _ = json.JSONDecoder().raw_decode(payload)
    except (ValueError, TypeError):
        return None
    match = re.search(r'"schema":"TV-TRADE-EVIDENCE-10-v2","batch_number":(\d+),"research_only":true', sent_prompt)
    if not match or not isinstance(originals, list) or not 1 <= len(originals) <= 10:
        return None
    expected = []
    for item in originals:
        if not isinstance(item, dict) or not all(key in item for key in ("source_order", "script_id", "title")):
            return None
        if not isinstance(item["source_order"], int) or not isinstance(item["script_id"], str):
            return None
        if not isinstance(item["title"], str):
            return None
        expected.append((item["source_order"], item["script_id"], item["title"]))
    batch = int(match.group(1))
    if not 1 <= batch <= 443:
        return None
    first = (batch - 1) * 10 + 1
    if expected != [(first + i, pair[1], pair[2]) for i, pair in enumerate(expected)]:
        return None
    if batch != 443 and len(expected) != 10:
        return None
    if batch == 443 and len(expected) != 8:
        return None
    return batch, expected


def _parse_received_json(answer):
    if not isinstance(answer, str) or not answer.strip():
        return None
    data = answer.strip()
    if data.startswith("```"):
        lines = data.splitlines()
        if len(lines) < 3 or not lines[-1].strip() == "```":
            return None
        if lines[0].strip().lower() not in ("```", "```json"):
            return None
        data = "\n".join(lines[1:-1]).strip()
    try:
        return json.loads(data)
    except (ValueError, TypeError):
        return None


def matches_stocktv_research_json(received_answer, sent_prompt):
    """True iff the complete JSON structurally matches this single ten-source task.

    JSON may be observed while ChatGPT is still rendering. Its COMPLETE parse,
    exact source identities and case fields are the acceptance conditions.
    We do not require a stop button, copy/action row, UI text stability,
    thinking-indicator absence or a visible copy of the user's question.
    """
    scope = _expected_from_sent_prompt(sent_prompt)
    reply = _parse_received_json(received_answer)
    if scope is None or not isinstance(reply, dict):
        return False
    batch, expected = scope
    if reply.get("schema") != SCHEMA or reply.get("batch_number") != batch or reply.get("research_only") is not True:
        return False
    records = reply.get("source_results")
    if not isinstance(records, list) or len(records) != len(expected):
        return False
    for (order, script_id, title), record in zip(expected, records):
        if not isinstance(record, dict):
            return False
        if (record.get("source_order"), record.get("script_id"), record.get("title")) != (order, script_id, title):
            return False
        if record.get("research_status") not in STATUSES:
            return False
        if not isinstance(record.get("search_queries"), list) or not isinstance(record.get("exclusions"), list):
            return False
        cases = record.get("cases")
        if not isinstance(cases, list) or (record["research_status"] == "NO_WEB_ACCESS" and cases):
            return False
        for case in cases:
            if not isinstance(case, dict) or case.get("case_type") not in CASE_TYPES or case.get("access_level") not in ACCESS:
                return False
            if any(not isinstance(case.get(field), str) or not case[field].strip() for field in CASE_FIELDS):
                return False
            if not case["document_url"].startswith("https://"):
                return False
    return True
