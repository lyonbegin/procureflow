"""Validate actual cost evidence policy, never fabricate quotes."""
from g2b_bid_package import required_price_evidence
base={
 "verified_base_amount":{"amount_krw":"52000000"},
 "price_rules":{"minimum_bid_ratio":"0.88","maximum_bid_ratio":"1","vat_ratio":"0.1"},
 "cost_breakdown":{"execution_model":"self_performed","labor_krw":30000000,"total_krw":39000000}
}
assert required_price_evidence(base)=={"verified_base_amount","price_rules","cost_breakdown"}
external={**base,"cost_breakdown":{**base["cost_breakdown"],"execution_model":"subcontract"}}
assert "supplier_quotes" in required_price_evidence(external)
unknown={**base,"cost_breakdown":{**base["cost_breakdown"],"execution_model":"unknown"}}
assert "supplier_quotes" in required_price_evidence(unknown)
zero={**base,"cost_breakdown":{**base["cost_breakdown"],"labor_krw":0}}
assert "supplier_quotes" in required_price_evidence(zero)
print("PUBLIC_REAL_COST_POLICY_IN_HOUSE_VS_EXTERNAL_DOCUMENTED_QUOTE_PASS")
