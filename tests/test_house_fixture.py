"""The full-house proposal preserves source intent and explicit unknowns."""

from decimal import Decimal, ROUND_CEILING
import json
from pathlib import Path

from takeoff_suppliers.core import Market
from takeoff_suppliers.house_fixture import build_house_fixture


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "examples/procurement/contractor-house-request.txt"
FIXTURE = ROOT / "src/takeoff_suppliers/fixtures/house.json"


def test_proposal_preserves_all_source_lines_and_reproducible_generation():
    fixture = json.loads(FIXTURE.read_text())
    assert fixture == build_house_fixture(SOURCE)
    assert fixture["source_message"] == SOURCE.read_text()
    assert fixture["adoption_status"] == "proposal_pending_buyer_agreement"
    assert fixture["tax_treatment"] == "all_fixture_taxes_included"
    assert [r["id"] for r in fixture["requirements"]] == [f"house-{n:02}" for n in range(1, 26)]
    for number, req in enumerate(fixture["requirements"], 1):
        assert req["source_line"] == number
        assert req["source_text"] == SOURCE.read_text().splitlines()[req["source_file_line"] - 1]
        assert req["source_text"].startswith(f"{number}. ")


def test_first_slice_and_sale_unit_conversions(tmp_path):
    market = Market(tmp_path / "house.db", FIXTURE)
    run = market.create_run("buyer")
    products = {p["id"]: p for p in market.catalog(run["id"], "general")["products"]}
    assert [products[f"general-house-{n:02}"]["stock"] for n in (1, 2, 3)] == [200, 60, 40]
    shingles = products["general-house-05"]
    needed = int((Decimal(600) / Decimal(shingles["units_per_sale_unit"])).to_integral_value(rounding=ROUND_CEILING))
    assert needed == 19 and Decimal(needed) * Decimal(shingles["units_per_sale_unit"]) == Decimal("633.27")
    flooring = products["general-house-23"]
    assert flooring["unit"] == "carton" and flooring["requirement_unit"] == "sq_ft"
    assert Decimal(flooring["units_per_sale_unit"]) * 9 == Decimal("211.5")
    assert products["general-house-22"]["specifications"]["stock_length_ft"] >= 8


def test_unresolved_contractor_facts_are_not_inferred_from_catalog():
    fixture = json.loads(FIXTURE.read_text())
    reqs = {r["id"]: r for r in fixture["requirements"]}
    insulation = reqs["house-10"]
    pex = reqs["house-16"]
    assert "facing" not in insulation["specifications"]
    assert "connection_system" not in pex["specifications"]
    assert pex["required_variants"] == {"red": 100, "blue": 100}
    for req in (insulation, pex):
        assert req["unresolved_clarifications"][0]["answer"] is None
        assert req["unresolved_clarifications"][0]["required_before_recommendation"]
    assert "stock_length_ft" not in reqs["house-22"]["specifications"]
    assert "maker" not in reqs["house-07"]["specifications"]
    assert "carton_coverage_sq_ft" not in reqs["house-23"]["specifications"]


def test_full_coverage_and_real_material_substitution_with_private_economics(tmp_path):
    fixture = json.loads(FIXTURE.read_text())
    general, overstock, local, trader = fixture["vendors"]
    assert {p["requirement_id"] for p in general["products"]} == {r["id"] for r in fixture["requirements"]}
    substitution = next(p for p in overstock["products"] if p["substitution_for"])
    original = next(p for p in general["products"] if p["requirement_id"] == "house-04")
    assert original["specifications"]["material"] == "plywood"
    assert substitution["specifications"]["material"] == "OSB"
    assert substitution["eligibility"] == "needs_contractor_approval"
    assert "equivalence" in substitution["substitution_difference"]
    assert len({v["objective"] for v in fixture["vendors"]}) == 4
    assert all(v["discounts"] == [] for v in fixture["vendors"])
    assert len(local["slots"]) == 2 and len(trader["slots"]) == 2
    market = Market(tmp_path / "market.db", FIXTURE)
    run = market.create_run("buyer")
    public = json.dumps(market.catalog(run["id"], "overstock"))
    assert "unit_cost" not in public and "min_margin_percent" not in public
