"""Local HTTP/SQLite integration using the authored house fixture.

These checks exercise the real ASGI service, not live Ambiguous or a second
computer. Commercial coverage does not resolve contractor clarification questions.
"""
from decimal import Decimal, ROUND_CEILING
from pathlib import Path

from fastapi.testclient import TestClient

from takeoff_suppliers.core import Market
from takeoff_suppliers.web import create_app


HOUSE = Path(__file__).parents[1] / "src/takeoff_suppliers/fixtures/house.json"
BUYER = {"Authorization": "Bearer integration-buyer-token"}
OPERATOR = {"Authorization": "Bearer integration-operator-token"}


def test_house_discovery_negotiation_approval_completion_and_reset(tmp_path):
    market = Market(tmp_path / "market.sqlite", HOUSE)
    client = TestClient(create_app(market, "integration-operator-token", "integration-buyer-token"))
    run_response = client.post("/v1/runs", json={"buyer_type": "development"}, headers=OPERATOR)
    assert run_response.status_code == 201
    run = run_response.json()
    run_id = run["id"]
    prefix = f"/v1/runs/{run_id}"
    requirements = {r["id"]: r for r in run["requirements"]}
    assert len(requirements) == 25
    assert all(r["source_ref"] for r in requirements.values())
    # These remain open contractor decisions even after all material is covered.
    assert any(r.get("unresolved_clarifications") for r in requirements.values())
    assert client.get(prefix + "/vendors/general/catalog").status_code == 401
    vendors = client.get(prefix + "/vendors", headers=BUYER).json()["vendors"]
    assert {v["channel"] for v in vendors} >= {"website", "email", "agent-to-agent"}

    catalogs = {v["id"]: client.get(prefix + f"/vendors/{v['id']}/catalog", headers=BUYER).json() for v in vendors}
    assert all(c["tax_treatment"] == "all_fixture_taxes_included" for c in catalogs.values())
    assert any(p["unit"] != p["requirement_unit"] for p in catalogs["general"]["products"])
    inquiry = client.post(prefix + "/vendors/overstock/inquiries", headers=BUYER,
                          json={"message": "What subfloor alternatives can you offer and on what delivery terms?"})
    assert inquiry.status_code == 200
    assert inquiry.json()["evidence_id"]
    substitution = next(p for p in catalogs["overstock"]["products"] if p.get("substitution_for"))
    replacement_req = substitution["substitution_for"]

    def offer(vendor, lines, request_id):
        response = client.post(prefix + f"/vendors/{vendor}/offers", headers=BUYER, json={
            "request_id": request_id, "delivery_slot": catalogs[vendor]["delivery_slots"][0]["id"], "lines": lines,
        })
        assert response.status_code == 201, response.text
        return response.json()

    alternative_lines = [{"product_id": substitution["id"], "unit": substitution["unit"],
                          "quantity": requirements[replacement_req]["quantity"]}]
    declined = offer("overstock", alternative_lines, "consider-alternative")
    rejection = client.post(prefix + f"/offers/{declined['id']}/reject", headers=BUYER)
    assert rejection.status_code == 200 and rejection.json()["status"] == "rejected"
    assert client.post(prefix + f"/offers/{declined['id']}/accept", headers=BUYER, json={}).status_code == 409

    alternative = offer("overstock", alternative_lines, "approved-alternative")
    assert client.post(prefix + f"/offers/{alternative['id']}/accept", headers=BUYER, json={}).status_code == 409
    partial = market.score_plan(run_id, "demo-buyer", [alternative["id"]])
    assert not partial["valid"] and "unapproved_substitution" in partial["failures"]
    approval = client.post(prefix + "/approvals", headers=BUYER, json={
        "requirement_id": replacement_req, "product_id": substitution["id"],
        "source_ref": "local-integration:explicit-contractor-decision",
    })
    assert approval.status_code == 201
    accepted_sub = client.post(prefix + f"/offers/{alternative['id']}/accept", headers=BUYER,
                               json={"approval_refs": [approval.json()["id"]]})
    assert accepted_sub.status_code == 200

    lines = []
    for product in catalogs["general"]["products"]:
        req = requirements[product["requirement_id"]]
        if req["id"] == replacement_req or product.get("substitution_for"):
            continue
        needed = req.get("required_variants", {}).get(product.get("variant"), req["quantity"])
        multiple = product["pack_size"]
        packs = (Decimal(needed) / Decimal(product["units_per_sale_unit"]) / multiple).to_integral_value(rounding=ROUND_CEILING)
        quantity = max(int(packs) * multiple, product["minimum_quantity"])
        lines.append({"product_id": product["id"], "unit": product["unit"], "quantity": quantity})
    general = offer("general", lines, "remaining-house-materials")
    assert general["tax_treatment"] == "all_fixture_taxes_included"
    assert all(Decimal(line["covered_quantity"]) == Decimal(line["quantity"]) * Decimal(line["units_per_sale_unit"])
               for line in general["lines"])
    assert Decimal(general["total"]) == sum(Decimal(line["line_total"]) for line in general["lines"]) + sum(Decimal(f["amount"]) for f in general["fees"])
    ids = [alternative["id"], general["id"]]
    full = market.score_plan(run_id, "demo-buyer", ids, max_delivery_days=6)
    assert full["valid"], full
    assert full["validation_scope"] == "commercial_terms_and_material_coverage"
    assert {c["key"] for c in full["contractor_clarifications"]} == {"facing", "fitting_system"}
    assert next(p for p in catalogs["general"]["products"] if p['requirement_id'] == 'house-10')['eligibility'] == 'needs_contractor_clarification'
    assert full["variant_quantities"]["house-16"] == {"red": "100", "blue": "100"}
    accepted = client.post(prefix + f"/offers/{general['id']}/accept", headers=BUYER, json={})
    assert accepted.status_code == 200
    assert accepted.json()["draft_order"]["tax_treatment"] == "all_fixture_taxes_included"
    assert market.score_plan(run_id, "demo-buyer", ids, max_delivery_days=6)["valid"]

    reset_response = client.post(prefix + "/reset", headers=OPERATOR)
    assert reset_response.status_code == 201
    reset = reset_response.json()
    assert reset["scenario_version"] == run["scenario_version"] and reset["id"] != run_id
    for vendor_id, original in catalogs.items():
        assert client.get(f"/v1/runs/{reset['id']}/vendors/{vendor_id}/catalog", headers=BUYER).json() == original
    history = client.get(prefix + "/export", headers=OPERATOR).json()
    assert len([q for q in history["offers"] if q["status"] == "accepted"]) == 2
    assert len([q for q in history["offers"] if q["status"] == "rejected"]) == 1
    assert history["live_transport_verified"] is False
