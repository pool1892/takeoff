"""Generate the proposed 25-line synthetic house catalog from its source text.

This fixture invents supplier businesses, products, prices, and product documents.
It is procurement-demo data, not manufacturer evidence or construction advice.
"""

import argparse
from copy import deepcopy
from decimal import Decimal, ROUND_CEILING
import json
from pathlib import Path
import re


# Requirement unit/quantity, sale unit/coverage, synthetic sale price, product facts.
PRODUCTS = [
    ("Full-length KD SPF studs", "each", 200, "each", "1", "4.80", {"nominal_size": "2x4", "length_ft": 8, "full_length": True, "species_group": "SPF", "grade": "No. 2", "drying": "KD"}),
    ("KD SPF long framing", "each", 60, "each", "1", "10.75", {"nominal_size": "2x6", "length_ft": 10, "species_group": "SPF", "grade": "No. 2", "drying": "KD"}),
    ("Rated OSB sheathing", "sheet", 40, "sheet", "1", "17.90", {"material": "OSB", "thickness_in": "7/16", "dimensions_ft": "4x8", "designation": "rated sheathing", "exposure": "Exposure 1"}),
    ("T&G plywood subfloor", "sheet", 20, "sheet", "1", "46.50", {"material": "plywood", "thickness_in": "23/32", "dimensions_ft": "4x8", "edge": "tongue-and-groove", "use": "subfloor", "exposure": "Exposure 1"}),
    ("Charcoal architectural shingles", "sq_ft", 600, "bundle", "33.33", "41.00", {"material": "asphalt", "type": "architectural shingles", "color": "charcoal", "bundle_coverage_sq_ft": "33.33", "sample_ref": "fixture:charcoal-sample"}),
    ("Synthetic roofing underlayment", "sq_ft", 600, "roll", "500", "78.00", {"material": "synthetic", "installed_coverage_sq_ft": "500", "use": "under architectural asphalt shingles", "use_evidence_ref": "fixture:roof-system-data", "installed_coverage_conditions": "Fixture coverage already accounts for the stated lap pattern; no extra waste factor."}),
    ("WRB housewrap 9x100", "roll", 2, "roll", "1", "112.00", {"purpose": "water-resistive barrier", "width_ft": 9, "length_ft": 100, "maker": "DemoWrap", "product_family": "DemoWrap WRB"}),
    ("Wrap-maker seam tape", "roll", 3, "roll", "1", "14.50", {"material": "housewrap seam tape", "width_in": 2, "length_yd": 55, "approved_wrap_family": "DemoWrap WRB", "approval_evidence_ref": "fixture:demowrap-seam-tape-data"}),
    ("Self-adhered flashing tape", "roll", 4, "roll", "1", "24.00", {"type": "self-adhered window flashing tape", "width_in": 4, "length_ft": 75, "compatible_wrap_family": "DemoWrap WRB", "window_frame_material": "vinyl", "compatibility_evidence_ref": "fixture:flashing-wrap-vinyl-data", "installation_conditions": "Synthetic product sheet: clean dry substrates; fixture temperature range 40–100 F. This is not actual manufacturer evidence."}),
    ("R13 fiberglass wall batts", "sq_ft", 600, "bag", "40", "32.00", {"material": "fiberglass", "r_value": "R-13", "width_in": 15, "facing": "unfaced", "coverage_sq_ft_per_bag": "40"}),
    ("Regular half-inch drywall", "sheet", 60, "sheet", "1", "14.75", {"type": "regular drywall", "thickness_in": "1/2", "dimensions_ft": "4x8"}),
    ("Interior wall cement backer", "board", 12, "board", "1", "16.90", {"material": "cement backer board", "thickness_in": "1/2", "dimensions_ft": "3x5", "manufacturer_stated_use": "interior wall tile backing", "use_evidence_ref": "fixture:cement-backer-data"}),
    ("Premixed all-purpose joint compound", "us_gal", 18, "pail", "4.5", "21.00", {"type": "premixed all-purpose drywall joint compound", "container_us_gal": "4.5"}),
    ("Paper drywall joint tape", "linear_ft", 1000, "roll", "500", "8.50", {"material": "paper", "use": "drywall joint tape", "roll_length_ft": 500}),
    ("Coarse-thread drywall screws", "lb", 10, "box", "5", "19.75", {"diameter": "#6", "length_in": "1-1/4", "thread": "coarse", "coating": "black phosphate", "net_box_weight_lb": 5}),
    ("Half-inch PEX water coil", "linear_ft", 200, "coil", "100", "49.00", {"nominal_size_in": "1/2", "material": "PEX", "use": "water lines", "coil_length_ft": 100, "connection_system": "DemoPEX expansion fittings", "compatibility_evidence_ref": "fixture:demopex-fitting-data"}),
    ("Plain-end PVC DWV pipe", "each", 8, "each", "1", "18.00", {"material": "PVC", "designation": "Schedule 40 DWV", "diameter_in": 2, "length_ft": 10, "ends": "plain"}),
    ("12/2 copper NM-B cable", "roll", 1, "roll", "1", "132.00", {"designation": "12/2 NM-B", "conductor_material": "copper", "with_ground": True, "roll_length_ft": 250}),
    ("22-cu-in nail-on electrical box", "each", 20, "each", "1", "2.10", {"gangs": 1, "material": "plastic", "work_type": "new-work", "mounting": "nail-on", "volume_cu_in": 22}),
    ("Unprepared primed interior door slab", "each", 3, "each", "1", "76.00", {"type": "slab", "core": "hollow", "surface": "smooth flush", "primed": True, "width_in": 30, "height_in": 80, "thickness_in": "1-3/8", "bores": False, "hinge_mortises": False}),
    ("Fixed white vinyl window", "each", 2, "each", "1", "185.00", {"operation": "fixed", "frame_material": "vinyl", "frame_color": "white", "actual_unit_width_in": 24, "actual_unit_height_in": 36, "nail_fin": True, "glazing": "double-pane clear insulated glass", "performance_sheet_ref": "fixture:fixed-window-performance"}),
    ("Square-edge primed MDF baseboard", "linear_ft", 160, "length", "12", "12.60", {"material": "MDF", "primed": True, "profile": "square edge", "height_in": "3-1/4", "thickness_in": "9/16", "stock_length_ft": 12}),
    ("Light-oak click-lock vinyl plank", "sq_ft", 200, "carton", "23.5", "61.10", {"material": "vinyl plank", "joint": "click-lock", "overall_thickness_mm": 6, "wear_layer_mil": 20, "finish": "light oak look", "carton_coverage_sq_ft": "23.5", "sample_ref": "fixture:light-oak-finish-sample"}),
    ("Factory-white eggshell wall paint", "us_gal", 15, "pail", "5", "112.00", {"use": "interior wall", "base": "water-based", "sheen": "eggshell", "color": "factory white", "container_us_gal": 5}),
    ("Factory-white semi-gloss trim enamel", "us_gal", 2, "can", "1", "31.00", {"use": "interior trim enamel", "base": "water-based", "sheen": "semi-gloss", "color": "factory white", "container_us_gal": 1}),
]


def build_house_fixture(source_path):
    source_path = Path(source_path)
    source = source_path.read_text()
    source_lines = {}
    for physical_line, text in enumerate(source.splitlines(), 1):
        match = re.match(r"^(\d+)\. (.+)$", text)
        if match:
            source_lines[int(match.group(1))] = (physical_line, text)
    if set(source_lines) != set(range(1, 26)):
        raise ValueError("Contractor source must preserve exactly the 25 numbered requirements")
    requirements = []
    for number, (name, unit, quantity, _, _, _, specs) in enumerate(PRODUCTS, 1):
        physical_line, text = source_lines[number]
        required_specs = deepcopy(specs)
        # Product packaging, brand choices, and evidence are not contractor specs.
        for key in ("bundle_coverage_sq_ft", "installed_coverage_sq_ft", "sample_ref",
                    "use_evidence_ref", "installed_coverage_conditions", "maker", "product_family",
                    "approved_wrap_family", "approval_evidence_ref", "compatible_wrap_family",
                    "compatibility_evidence_ref", "installation_conditions", "coverage_sq_ft_per_bag",
                    "container_us_gal", "net_box_weight_lb", "stock_length_ft", "carton_coverage_sq_ft",
                    "performance_sheet_ref"):
            required_specs.pop(key, None)
        # These are unresolved contractor facts, never inferred from product stock.
        if number == 10:
            required_specs.pop("facing")
        if number == 16:
            required_specs.pop("connection_system")
        req = {"id": f"house-{number:02}", "name": name, "unit": unit, "quantity": quantity,
               "source_line": number, "source_text": text, "source_file_line": physical_line,
               "source_ref": f"examples/procurement/contractor-house-request.txt#L{physical_line}",
               "specifications": required_specs}
        if number in (10, 16):
            req["unresolved_clarifications"] = [{
                "key": "facing" if number == 10 else "fitting_system",
                "owner": "contractor", "required_before_recommendation": True,
                "question": "Which insulation facing is required?" if number == 10 else "What fittings must the PEX connect to?",
                "status": "unresolved", "answer": None,
            }]
        if number == 16:
            req["required_variants"] = {"red": 100, "blue": 100}
        requirements.append(req)

    vendor_defs = [
        ("general", "General Building Supply", "website", range(1, 26), "0", "15", "38",
         "Offer fixed published packages, explain product fit and full sale packs."),
        ("overstock", "Second Shift Materials", "email", [1, 2, 3, 4, 5, 6, 10, 11, 12, 13, 14, 15, 22, 23], "18", "9", "26",
         "Move aging stock and consider bundles; choose concessions from the actual inquiry, not a scripted discount."),
        ("local", "Neighborhood Delivery Supply", "agent-to-agent", range(1, 26), "10", "12", "18",
         "Optimize delivery consolidation and practical package fit; negotiate actual tradeoffs."),
        ("trader", "Forward Materials Desk", "agent-to-agent", [1, 2, 3, 4, 5, 6, 17, 18], "12", "10", "30",
         "Research and explain market uncertainty; consider forward quotes but never place trades."),
    ]
    vendors = []
    for vendor_index, (vendor_id, name, channel, numbers, discount, margin, delivery_cost, objective) in enumerate(vendor_defs):
        products = []
        for number in numbers:
            product_name, req_unit, required_qty, sale_unit, coverage, price, specs = PRODUCTS[number - 1]
            # Varied fictional prices avoid a globally predetermined low-price supplier.
            factor = Decimal(["1.00", "0.96", "1.04", "1.01"][(number + vendor_index) % 4])
            selling_price = (Decimal(price) * factor).quantize(Decimal("0.01"))
            specs = deepcopy(specs)
            variants = ("red", "blue") if number == 16 else (None,)
            for variant in variants:
                suffix = f"-{variant}" if variant else ""
                needed = int((Decimal(required_qty) / Decimal(coverage)).to_integral_value(rounding=ROUND_CEILING))
                product = {"id": f"{vendor_id}-house-{number:02}{suffix}", "name": product_name + (f" — {variant}" if variant else ""),
                           "requirement_id": f"house-{number:02}", "requirement_unit": req_unit,
                           "unit": sale_unit, "units_per_sale_unit": coverage, "pack_size": 1,
                           "stock": required_qty if number <= 3 else max(needed * 3, 12),
                           "list_price": str(selling_price), "minimum_quantity": 1,
                           "specifications": deepcopy(specs), "substitution_for": None, "alternatives": [],
                           "tax_treatment": "all_fixture_taxes_included",
                           "product_info_ref": f"fixture:{vendor_id}-house-{number:02}-product-data",
                           "evidence_kind": "synthetic_product_data",
                           "private": {"unit_cost": str((selling_price * Decimal("0.63")).quantize(Decimal("0.01")))}}
                if variant:
                    product["variant"] = variant
                    product["specifications"]["color"] = variant
                if number in (10, 16):
                    product["unresolved_clarifications"] = deepcopy(requirements[number - 1]["unresolved_clarifications"])
                    product["eligibility"] = "needs_contractor_clarification"
                if number in (6, 8, 9):
                    product["related_requirements"] = {6: ["house-05"], 8: ["house-07"], 9: ["house-07", "house-21"]}[number]
                products.append(product)
        if vendor_id == "overstock":
            plywood = next(p for p in products if p["requirement_id"] == "house-04")
            alternative = deepcopy(plywood)
            alternative.update(id="overstock-house-04-osb", name="T&G OSB subfloor — proposed plywood substitution",
                               list_price="32.40", substitution_for="house-04", alternatives=[plywood["id"]],
                               eligibility="needs_contractor_approval",
                               product_info_ref="fixture:overstock-osb-subfloor-product-data")
            alternative["specifications"]["material"] = "OSB"
            alternative["private"]["unit_cost"] = "21.20"
            alternative["substitution_difference"] = "OSB replaces specified plywood; no engineering equivalence is asserted."
            plywood["alternatives"].append(alternative["id"])
            products.append(alternative)
        slots = [{"id": "standard", "label": "94103 zone estimate — delivered by Sept 18",
                  "days": 6, "delivery_date": "2026-09-18", "fee": "68.00", "capacity": 2500,
                  "delivery_zone": "94103", "quote_basis": "synthetic_zone_estimate"}]
        if vendor_id == "local":
            slots = [{"id": "express", "label": "94103 dedicated delivery Sept 15", "days": 3,
                      "delivery_date": "2026-09-15", "fee": "120.00", "capacity": 2500},
                     {"id": "shared", "label": "94103 shared route Sept 18", "days": 6,
                      "delivery_date": "2026-09-18", "fee": "35.00", "capacity": 2500}]
        if vendor_id == "trader":
            slots.append({"id": "forward", "label": "Forward delivery Sept 25 — needs deadline approval", "days": 13,
                          "delivery_date": "2026-09-25", "fee": "48.00", "capacity": 2500,
                          "needs_deadline_approval": True})
        vendors.append({"id": vendor_id, "name": name, "channel": channel,
                        "description": objective, "objective": objective, "products": products,
                        "slots": slots, "discounts": [],
                        "private": {"max_discount_percent": discount, "min_margin_percent": margin,
                                    "delivery_cost": delivery_cost}})
    return {"id": "proposed-house-25", "version": "house-25-proposal-1",
            "label": "Proposed 25-line synthetic supplier world — buyer adoption pending",
            "simulated": True, "adoption_status": "proposal_pending_buyer_agreement", "currency": "USD",
            "tax_treatment": "all_fixture_taxes_included", "quote_ttl_seconds": 3600,
            "delivery_zone": "94103", "required_delivery_date": "2026-09-18",
            "delivery_date_basis": "scenario_start_2026-09-12; absolute dates are synthetic scenario constraints",
            "source_message": source, "source_path": "examples/procurement/contractor-house-request.txt",
            "scenario_notes": ["All products, product evidence, prices, tax treatment and business constraints are invented demo data.",
                               "Full sale packs only; source quantities already include the contractor allowance.",
                               "Facing and existing PEX fitting identity remain unresolved; a complete catalog is not a complete eligible plan.",
                               "No real purchase, code compliance, engineering suitability or manufacturer approval is implied."],
            "requirements": requirements, "vendors": vendors}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path("examples/procurement/contractor-house-request.txt"))
    parser.add_argument("--output", type=Path, default=Path(__file__).parent / "fixtures/house.json")
    args = parser.parse_args()
    args.output.write_text(json.dumps(build_house_fixture(args.source), indent=2, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
