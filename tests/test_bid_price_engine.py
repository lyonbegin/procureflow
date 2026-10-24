"""Test no-submission K-apt OCR cost-model reconciliation."""
from decimal import Decimal, ROUND_CEILING
import pytest

from bid_price_engine import (
  NOTICE_ID, build_price_model, price_scenarios, proposal_draft,
)


def test_ocr_minimum_is_reconciled_but_not_a_bid():
    m=build_price_model()
    t=m["totals"]
    assert m["notice_id"]==NOTICE_ID
    assert t["per_person_direct_krw"]==3357392
    assert t["per_person_indirect_krw"]==344730
    assert t["monthly_total_krw"]==10147500
    assert t["annual_total_krw"]==121770000
    assert t["tender_bond_5pct_krw"]==6088500
    assert t["performance_bond_10pct_krw"]==12177000
    assert t["reconciles"]
    assert not m["bid_ready"] and not m["can_submit"]
    assert len(m["hard_blocks"])>=5


def test_hourly_and_percentage_ceilings():
    m=build_price_model()
    r={x["name"]:x["amount"] for x in m["rows"]}
    assert r["기본급"]==2668236
    assert r["야간수당"]==313935
    assert r["퇴직적립금"]==258261
    assert r["장기요양보험"]==14640
    assert r["보안시스템 운영비"]==1990000


def test_scenarios_are_not_final_and_differ():
    rows=price_scenarios()
    assert len(rows)==3
    assert rows[1]["annual_krw"]>rows[0]["annual_krw"]
    assert rows[2]["annual_krw"]>rows[0]["annual_krw"]
    assert all(not s["bid_ready"] for s in rows)


def test_role_allowance_and_relief_raise_price():
    baseline=build_price_model()["totals"]["annual_total_krw"]
    modified=build_price_model(role_allowance_krw=60000,
                               relief_staff_monthly_krw=100000)["totals"]
    assert modified["annual_total_krw"]>baseline+1200000


@pytest.mark.parametrize("options",[
    {"role_allowance_krw":-1},
    {"role_allowance_krw":10000000},
    {"relief_staff_monthly_krw":-1},
    {"admin_pct":"2.99"},
    {"profit_pct":"NaN"},
    {"common_cost_scope":"undefined"},
])
def test_invalid_values_rejected(options):
    with pytest.raises(ValueError):
        build_price_model(**options)


def test_proposal_does_not_claim_licenses_or_bidding():
    draft=proposal_draft()
    assert len(draft["sections"])>=8
    assert draft["registration_or_submission_actions"]==0
    assert draft["not_final_bid"] and not draft["submission_documents_ready"]
