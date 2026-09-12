"""Commercial invariants and frozen-trial evidence against the real SQLite ledger."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from decimal import Decimal
import json

import pytest

from takeoff_suppliers.core import Market, MarketError


@pytest.fixture
def setup(tmp_path):
    market = Market(tmp_path / "market.db")
    run = market.create_run("buyer")
    return market, run


def proposal(market, run, vendor="general", quantities=None):
    catalog = market.catalog(run["id"], vendor)
    quantities = quantities or {r["id"]: r["quantity"] for r in run["requirements"]}
    return {"request_id": "request-1", "delivery_slot": catalog["delivery_slots"][0]["id"],
            "lines": [{"product_id": p["id"], "quantity": quantities[p["requirement_id"]], "unit": p["unit"]}
                      for p in catalog["products"] if p["requirement_id"] in quantities and not p.get("substitution_for")]}


def test_package_discount_and_fee_arithmetic(setup):
    market, run = setup
    data = proposal(market, run, "overstock", {"sheathing": 10, "drywall": 10})
    data["discount_code"] = "clearance-pair"
    offer = market.issue_offer(run["id"], "overstock", "buyer", data)
    assert offer["subtotal"] == "351.50"
    assert offer["discounts"][0]["amount"] == "28.12"
    assert offer["fees"] == [{"name": "delivery", "amount": "35.00"}]
    assert offer["total"] == "358.38"
    data["lines"] = data["lines"][:1]
    with pytest.raises(MarketError, match="discount conditions"):
        market.issue_offer(run["id"], "overstock", "buyer", data)


@pytest.mark.parametrize("quantity", [0, -1, True, 1.5, "NaN", "Infinity", [], {}])
def test_invalid_quantities(setup, quantity):
    market, run = setup
    data = proposal(market, run)
    data["lines"][0]["quantity"] = quantity
    with pytest.raises(MarketError):
        market.issue_offer(run["id"], "general", "buyer", data)


@pytest.mark.parametrize("change", [
    {"requested_total": "NaN"}, {"previous_quote_id": {}},
    {"previous_quote_id": ["id"]}, {"request_id": {"id": "x"}},
    {"discount_code": ["clearance-pair"]},
])
def test_invalid_optional_fields(setup, change):
    market, run = setup
    data = proposal(market, run)
    data.update(change)
    with pytest.raises(MarketError):
        market.issue_offer(run["id"], "general", "buyer", data)


def test_duplicate_products_and_wrong_units(setup):
    market, run = setup
    data = proposal(market, run)
    data["lines"].append(deepcopy(data["lines"][0]))
    with pytest.raises(MarketError, match="repeated products"):
        market.issue_offer(run["id"], "general", "buyer", data)
    data["lines"].pop()
    data["lines"][0]["unit"] = "pallet"
    with pytest.raises(MarketError, match="sold by"):
        market.issue_offer(run["id"], "general", "buyer", data)


def test_counter_supersedes_exact_revision(setup):
    market, run = setup
    data = proposal(market, run, "overstock")
    old = market.issue_offer(run["id"], "overstock", "buyer", data)
    data.update(previous_quote_id=old["id"], requested_total=str(Decimal(old["total"]) - 1))
    new = market.issue_offer(run["id"], "overstock", "buyer", data)
    assert new["revision"] == 2 and new["previous_quote_id"] == old["id"]
    assert market.get_offer(run["id"], old["id"], "buyer")["status"] == "countered"
    with pytest.raises(MarketError):
        market.accept_offer(run["id"], old["id"], "buyer")
    assert market.accept_offer(run["id"], new["id"], "buyer")["total"] == new["total"]


def test_concurrent_accepts_cannot_oversell_and_retry_is_idempotent(setup):
    market, run = setup
    data = proposal(market, run, quantities={"stud": 240})
    offers = [market.issue_offer(run["id"], "general", "buyer", data) for _ in range(2)]
    def accept(offer):
        try:
            return market.accept_offer(run["id"], offer["id"], "buyer")
        except MarketError as error:
            return error
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(accept, offers))
    accepted = [result for result in results if isinstance(result, dict)]
    assert len(accepted) == 1
    before = market.catalog(run["id"], "general")
    assert next(p for p in before["products"] if p["id"] == "general-stud")["stock"] == 0
    assert market.accept_offer(run["id"], accepted[0]["id"], "buyer") == accepted[0]
    assert market.catalog(run["id"], "general") == before


def test_failure_on_later_line_rolls_back_earlier_reservation(setup):
    market, run = setup
    package = proposal(market, run, quantities={"stud": 1, "sheathing": 1})
    offer = market.issue_offer(run["id"], "general", "buyer", package)
    drain = market.issue_offer(run["id"], "general", "buyer", proposal(market, run, quantities={"sheathing": 80}))
    market.accept_offer(run["id"], drain["id"], "buyer")
    before = market.catalog(run["id"], "general")
    with pytest.raises(MarketError):
        market.accept_offer(run["id"], offer["id"], "buyer")
    assert market.catalog(run["id"], "general") == before


def test_substitution_requires_matching_run_approval(setup):
    market, run = setup
    p = next(p for p in market.catalog(run["id"], "local")["products"] if p.get("substitution_for"))
    data = {"request_id": "sub", "delivery_slot": "express", "lines": [{"product_id": p["id"], "unit": p["unit"], "quantity": 1}]}
    offer = market.issue_offer(run["id"], "local", "buyer", data)
    other = market.create_run("buyer")
    foreign = market.record_approval(other["id"], "buyer", p["substitution_for"], p["id"], "human-decision")
    for refs in ([], ["forged"], [foreign["id"]]):
        with pytest.raises(MarketError, match="approval"):
            market.accept_offer(run["id"], offer["id"], "buyer", refs)
    approval = market.record_approval(run["id"], "buyer", p["substitution_for"], p["id"], "human-decision")
    assert market.accept_offer(run["id"], offer["id"], "buyer", [approval["id"]])["status"] == "accepted"


def test_reset_freezes_original_version_prices_and_stock(setup):
    market, run = setup
    initial = market.catalog(run["id"], "general")
    offer = market.issue_offer(run["id"], "general", "buyer", proposal(market, run))
    market.accept_offer(run["id"], offer["id"], "buyer")
    market.scenario["vendors"][0]["products"][0]["list_price"] = "999.00"
    reset = market.reset_run(run["id"])
    assert reset["scenario_version"] == run["scenario_version"]
    assert reset["id"] != run["id"] and reset["parent_run_id"] == run["id"]
    assert market.catalog(reset["id"], "general") == initial
    assert market.export_run(run["id"])["offers"][0]["status"] == "accepted"


def test_scoring_aggregate_stock_capacity_and_reserved_acceptances(setup):
    market, run = setup
    offers = [market.issue_offer(run["id"], "general", "buyer", proposal(market, run)) for _ in range(5)]
    all_ids = [offer["id"] for offer in offers]
    invalid = market.score_plan(run["id"], "buyer", all_ids)
    assert not invalid["valid"]
    assert "unavailable_stock:general-stud" in invalid["failures"]
    assert "delivery_capacity:general:standard" in invalid["failures"]
    assert market.score_plan(run["id"], "buyer", all_ids[:1])["valid"]
    market.accept_offer(run["id"], offers[0]["id"], "buyer")
    assert market.score_plan(run["id"], "buyer", all_ids[:3])["valid"]
    assert not market.score_plan(run["id"], "buyer", all_ids[:4])["valid"]
    assert market.score_plan(run["id"], "buyer", all_ids[:1])["valid"]


def test_incomplete_late_and_duplicate_plans_remain_failed(setup):
    market, run = setup
    offer = market.issue_offer(run["id"], "general", "buyer", proposal(market, run, quantities={"stud": 60}))
    score = market.score_plan(run["id"], "buyer", [offer["id"], offer["id"]], max_delivery_days=1)
    assert not score["valid"]
    assert {"late_delivery", "duplicate_quote", "missing_quantity:sheathing"} <= set(score["failures"])
    assert any(e["kind"] == "plan_scored" for e in market.export_run(run["id"])["events"])


def test_public_projections_do_not_expose_private_economics(setup):
    market, run = setup
    market.issue_offer(run["id"], "general", "buyer", proposal(market, run))
    public = json.dumps([market.catalog(run["id"], "general"), market.export_run(run["id"]), market.get_run(run["id"])])
    for key in ('"private"', '"private_scenario"', '"unit_cost"', '"minimum_total"', '"max_discount_percent"'):
        assert key not in public
    private = market.export_run(run["id"], private=True)
    assert private["private_scenario"]["vendors"][0]["products"][0]["private"]["unit_cost"]


def test_changed_fact_and_pack_multiple_change_result(tmp_path):
    original = Market(tmp_path / "initial.db")
    scenario = deepcopy(original.scenario)
    product = scenario["vendors"][0]["products"][0]
    product.update(stock=4, pack_size=2)
    scenario_path = tmp_path / "changed.json"
    scenario_path.write_text(json.dumps(scenario))
    market = Market(tmp_path / "changed.db", scenario_path)
    run = market.create_run("buyer")
    for quantity in (1, 6):
        with pytest.raises(MarketError):
            market.issue_offer(run["id"], "general", "buyer", proposal(market, run, quantities={"stud": quantity}))
    good = market.issue_offer(run["id"], "general", "buyer", proposal(market, run, quantities={"stud": 4}))
    assert good["lines"][0]["quantity"] == 4


def test_rejection_preserves_evidence_and_prevents_acceptance(setup):
    market, run = setup
    offer = market.issue_offer(run["id"], "general", "buyer", proposal(market, run))
    before = market.catalog(run["id"], "general")
    rejected = market.reject_offer(run["id"], offer["id"], "buyer")
    assert rejected["status"] == "rejected"
    assert market.get_offer(run["id"], offer["id"], "buyer")["status"] == "rejected"
    assert market.catalog(run["id"], "general") == before
    with pytest.raises(MarketError):
        market.accept_offer(run["id"], offer["id"], "buyer")
    assert not market.score_plan(run["id"], "buyer", [offer["id"]])["valid"]


def converted_market(tmp_path, *, variants=False):
    base = Market(tmp_path / "base.db")
    scenario = deepcopy(base.scenario)
    scenario["tax_treatment"] = "all_fixture_taxes_included"
    requirement = scenario["requirements"][0]
    requirement.update(unit="linear_ft", quantity=200 if variants else 10)
    vendor = scenario["vendors"][0]
    product = vendor["products"][0]
    product.update(unit="coil", units_per_sale_unit="100" if variants else "2.5", requirement_unit="linear_ft", stock=4)
    vendor["products"] = [product]
    vendor["slots"][0]["capacity"] = 4
    scenario["requirements"] = [requirement]
    scenario["vendors"] = [vendor]
    if variants:
        requirement["required_variants"] = {"red": 100, "blue": 100}
        product["variant"] = "red"
        blue = deepcopy(product)
        blue.update(id="general-stud-blue", variant="blue")
        vendor["products"].append(blue)
    path = tmp_path / "converted.json"
    path.write_text(json.dumps(scenario))
    market = Market(tmp_path / "converted.db", path)
    return market, market.create_run("buyer"), path


def test_decimal_conversion_scores_coverage_but_reserves_sale_units(tmp_path):
    market, run, _ = converted_market(tmp_path)
    data = proposal(market, run, quantities={"stud": 4})
    data["lines"][0]["unit"] = "coil"
    offer = market.issue_offer(run["id"], "general", "buyer", data)
    assert offer["lines"][0]["covered_quantity"] == "10.0"
    assert offer["lines"][0]["requirement_unit"] == "linear_ft"
    assert offer["lines"][0]["quantity"] == 4
    assert offer["total"] == "69.00"  # Four sale units at6 +45 delivery.
    assert market.score_plan(run["id"], "buyer", [offer["id"]])["valid"]
    accepted = market.accept_offer(run["id"], offer["id"], "buyer")
    catalog = market.catalog(run["id"], "general")
    assert catalog["products"][0]["stock"] == 0
    assert catalog["delivery_slots"][0]["capacity"] == 0
    assert catalog["products"][0]["units_per_sale_unit"] == "2.5"
    assert accepted["draft_order"]["tax_treatment"] == "all_fixture_taxes_included"
    assert catalog["tax_treatment"] == offer["tax_treatment"] == "all_fixture_taxes_included"


def test_same_color_coverage_cannot_complete_mixed_variant_requirement(tmp_path):
    market, run, _ = converted_market(tmp_path, variants=True)
    red_only = {"request_id": "red", "delivery_slot": "standard", "lines": [
        {"product_id": "general-stud", "quantity": 2, "unit": "coil"}]}
    red_offer = market.issue_offer(run["id"], "general", "buyer", red_only)
    score = market.score_plan(run["id"], "buyer", [red_offer["id"]])
    assert score["quantities"]["stud"] == 200
    assert score["failures"] == ["missing_variant:stud:blue"]
    mixed = deepcopy(red_only)
    mixed["lines"][0]["quantity"] = 1
    mixed["lines"].append({"product_id": "general-stud-blue", "quantity": 1, "unit": "coil"})
    offer = market.issue_offer(run["id"], "general", "buyer", mixed)
    assert market.score_plan(run["id"], "buyer", [offer["id"]])["valid"]


@pytest.mark.parametrize("conversion", [None, "NaN", "0", "-1"])
def test_different_units_need_a_valid_explicit_conversion(tmp_path, conversion):
    _, _, path = converted_market(tmp_path)
    scenario = json.loads(path.read_text())
    product = scenario["vendors"][0]["products"][0]
    if conversion is None:
        product.pop("units_per_sale_unit")
    else:
        product["units_per_sale_unit"] = conversion
    path.write_text(json.dumps(scenario))
    with pytest.raises(ValueError):
        Market(tmp_path / "invalid.db", path)


def test_legacy_fixture_explicitly_reports_unmodeled_tax(setup):
    market, run = setup
    offer = market.issue_offer(run["id"], "general", "buyer", proposal(market, run))
    assert offer["tax_treatment"] == "unknown/not_modeled"
