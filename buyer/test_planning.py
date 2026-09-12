import copy
import unittest

from buyer.planning import evaluate_plan, compare_opening, rank_plans


NOW = "2026-09-12T22:00:00+00:00"


def example():
    """Public synthetic terms, hand-calculated: 3 packs*20 + 5 fee - 2 discount = 63."""
    run = {"run_id": "r", "request_revision": 1, "authority": {"budget_cap": "80"},
           "constraints": {"delivery_deadline": "2026-09-18T17:00:00-07:00"},
           "requirements": [{"id": "wall", "revision": 1, "source_text": "12 sheets",
                             "quantity": "12", "unit": "sheet", "specifications": {"type": "regular"}}]}
    product = {"id": "board", "revision": 1, "vendor_id": "v", "unit": "pack",
               "pack_size": "1", "minimum_quantity": "1", "coverage_quantity": "4",
               "coverage_unit": "sheet", "stock": "10", "specifications": {"type": "regular"},
               "evidence_refs": ["catalog-1"]}
    quote = {"quote_id": "q", "run_id": "r", "request_id": "request", "vendor_id": "v",
             "revision": 1, "status": "issued", "currency": "USD",
             "lines": [{"requirement_id": "wall", "product_id": "board", "quantity": "3", "unit": "pack",
                        "unit_price": "20.00", "line_total": "60.00"}],
             "subtotal": "60.00", "fees": [{"name": "delivery", "amount": "5.00"}],
             "discounts": [{"code": "package", "amount": "2.00"}],
             "taxes": {"status": "known", "amount": "0.00"}, "total": "63.00",
             "delivery": {"date": "2026-09-15T12:00:00-07:00"},
             "expires_at": "2026-09-14T23:00:00+00:00", "evidence_refs": ["offer-1"]}
    run["candidates"] = [{"requirement_id": "wall", "product": product}]
    run["quotes"] = [quote]
    return run, quote, product


def variant_example(colors=("red", "blue")):
    run, quote, base = example()
    run["authority"] = {}
    run["requirements"] = [{"id": "house-16", "revision": 1, "quantity": 200, "unit": "linear_ft",
        "source_text": "100 ft red and 100 ft blue PEX", "specifications": {"material": "PEX"},
        "variants": [{"id": color, "quantity": 100, "unit": "linear_ft",
                      "specifications": {"color": color, "coil_length_ft": 100}} for color in ("red", "blue")]}]
    run["candidates"] = []
    for color in ("red", "blue"):
        product = copy.deepcopy(base)
        product.update(id="pex-" + color, unit="coil", coverage_unit="linear_ft", coverage_quantity=100,
                       specifications={"material": "PEX", "color": color, "coil_length_ft": 100})
        run["candidates"].append({"requirement_id": "house-16", "product": product})
    quote["lines"] = [{"requirement_id": "house-16", "product_id": "pex-" + color, "quantity": 1,
                       "unit": "coil", "unit_price": "10", "line_total": "10"} for color in colors]
    quote.update(subtotal=str(10 * len(colors)), total=str(10 * len(colors) + 3))
    return run, quote


def compatibility_example():
    run, quote, base = example()
    run["requirements"] = [
        {"id": "tape", "revision": 1, "quantity": 2, "unit": "roll", "specifications": {"material": "seam tape"},
         "compatibility": [{"requirement_id": "wrap", "product_attribute": "approved_wrap_family",
                            "related_attribute": "product_family", "evidence_attributes": ["approval_evidence_ref"]}]},
        {"id": "wrap", "revision": 1, "quantity": 1, "unit": "roll", "specifications": {"purpose": "WRB"}}]
    tape = copy.deepcopy(base)
    tape.update(id="tape", unit="roll", related_requirements=["wrap"],
                specifications={"material": "seam tape", "approved_wrap_family": "family-A",
                                "approval_evidence_ref": "synthetic-tape-data"})
    wrap = copy.deepcopy(base)
    wrap.update(id="wrap", unit="roll", specifications={"purpose": "WRB", "product_family": "family-A"})
    run["candidates"] = [{"requirement_id": "tape", "product": tape}, {"requirement_id": "wrap", "product": wrap}]
    quote["lines"] = [{"requirement_id": "tape", "product_id": "tape", "quantity": 2, "unit": "roll", "unit_price": "3", "line_total": "6"},
                      {"requirement_id": "wrap", "product_id": "wrap", "quantity": 1, "unit": "roll", "unit_price": "10", "line_total": "10"}]
    quote.update(subtotal="16", total="19")
    return run, quote, tape, wrap


class PlanningTests(unittest.TestCase):
    def test_both_pex_variants_cover_one_requirement_group(self):
        run, quote = variant_example()
        plan = evaluate_plan(run, [quote], now=NOW)
        self.assertTrue(plan["complete"], plan["blockers"])
        self.assertEqual(plan["coverage"]["required_count"], 1)
        self.assertEqual(plan["coverage"]["covered_count"], 1)
        self.assertEqual(plan["coverage"]["variants"], {"house-16": {"red": "100", "blue": "100"}})
        self.assertEqual([line["variant_id"] for line in plan["selected_offers"][0]["lines"]], ["red", "blue"])

    def test_two_red_coils_cannot_cover_the_blue_requirement(self):
        run, quote = variant_example(("red", "red"))
        plan = evaluate_plan(run, [quote], now=NOW)
        self.assertFalse(plan["complete"])
        self.assertEqual(plan["coverage"]["quantities"]["house-16"], "200")
        self.assertEqual(plan["coverage"]["covered_count"], 0)
        self.assertTrue(any("variant blue: 0 of 100" in b for b in plan["blockers"]))

    def test_variant_parent_remains_one_of_25_groups(self):
        run, quote = variant_example()
        run["requirements"].extend({"id": f"other-{i}", "revision": 1, "quantity": 1, "unit": "each"} for i in range(24))
        plan = evaluate_plan(run, [quote], now=NOW)
        self.assertEqual(plan["coverage"]["required_count"], 25)
        self.assertEqual(plan["coverage"]["covered_count"], 1)
        self.assertFalse(plan["complete"])

    def test_compatibility_rechecks_the_actual_selected_related_product(self):
        run, quote, _, wrap = compatibility_example()
        plan = evaluate_plan(run, [quote], now=NOW)
        self.assertTrue(plan["complete"], plan["blockers"])
        wrap["specifications"]["product_family"] = "family-B"
        changed = evaluate_plan(run, [quote], now=NOW)
        self.assertFalse(changed["complete"])
        self.assertTrue(any("incompatible" in b for b in changed["blockers"]))

    def test_catalog_only_related_product_and_missing_evidence_do_not_prove_compatibility(self):
        run, quote, tape, _ = compatibility_example()
        quote["lines"].pop()
        quote.update(subtotal="6", total="9")
        missing_selection = evaluate_plan(run, [quote], now=NOW)
        self.assertFalse(missing_selection["complete"])
        self.assertTrue(any("needs_evidence" in b for b in missing_selection["blockers"]))
        run, quote, tape, _ = compatibility_example()
        del tape["specifications"]["approval_evidence_ref"]
        self.assertFalse(evaluate_plan(run, [quote], now=NOW)["complete"])

    def test_confirmed_atomic_package_decimal_and_coverage(self):
        run, quote, _ = example()
        original = copy.deepcopy(run)
        plan = evaluate_plan(run, ["q"], now=NOW)
        self.assertTrue(plan["complete"], plan["blockers"])
        self.assertEqual(plan["total_payable"], "63.00")
        self.assertEqual(plan["coverage"]["quantities"], {"wall": "12"})
        self.assertEqual(run, original)

    def test_unknown_tax_cannot_complete(self):
        run, quote, _ = example()
        del quote["taxes"]
        plan = evaluate_plan(run, [quote], now=NOW)
        self.assertFalse(plan["complete"])
        self.assertIsNone(plan["total_payable"])
        self.assertIn("Quote q: taxes", plan["blockers"])

    def test_missing_or_malformed_commercial_terms_remain_partial(self):
        run, quote, _ = example()
        quote.update(fees=None, discounts=["unconfirmed"], delivery="soon")
        plan = evaluate_plan(run, [quote], now=NOW)
        self.assertFalse(plan["complete"])
        self.assertIsNone(plan["total_payable"])

    def test_uncovered_requirement_and_actual_count(self):
        run, quote, _ = example()
        for n in range(24):
            run["requirements"].append({"id": f"other-{n}", "quantity": 1, "unit": "each", "revision": 1})
        plan = evaluate_plan(run, [quote], now=NOW)
        self.assertFalse(plan["complete"])
        self.assertEqual(plan["coverage"]["required_count"], 25)
        self.assertEqual(plan["coverage"]["covered_count"], 1)

    def test_changed_stock_and_offer_revision(self):
        run, quote, product = example()
        product["stock"] = "2"
        self.assertFalse(evaluate_plan(run, [quote], now=NOW)["complete"])
        product["stock"] = "10"
        revised = copy.deepcopy(quote)
        revised.update(revision=2)
        run["quotes"].append(revised)
        plan = evaluate_plan(run, [quote], now=NOW)
        self.assertTrue(any("newer" in b for b in plan["blockers"]))

    def test_current_product_stock_overrides_older_candidate_snapshot(self):
        run, quote, candidate_product = example()
        current = copy.deepcopy(candidate_product)
        current.update(revision="current-catalog-hash", stock="2")
        run["products"] = {"board": current}
        plan = evaluate_plan(run, [quote], now=NOW)
        self.assertFalse(plan["complete"])
        self.assertEqual(plan["selected_offers"][0]["lines"][0]["assessment"]["product_revision"], "current-catalog-hash")
        self.assertEqual(candidate_product["stock"], "10")
        current["stock"] = "10"
        self.assertTrue(evaluate_plan(run, [quote], now=NOW)["complete"])

    def test_current_revision_does_not_inherit_old_candidate_substitution_approval(self):
        run, quote, candidate_product = example()
        candidate_product["specifications"]["type"] = "moisture"
        run["approvals"] = [{"id": "old-approval", "validated": True, "decision": "approved", "run_id": "r",
            "request_revision": 1, "requirement_id": "wall", "requirement_revision": 1, "product_id": "board",
            "product_revision": 1, "candidate_id": "old-candidate", "approved_specifications": {"type": "moisture"},
            "evidence_refs": ["old-human-answer"]}]
        self.assertTrue(evaluate_plan(run, [quote], now=NOW)["complete"])
        current = copy.deepcopy(candidate_product)
        current["revision"] = 2
        run["products"] = {"board": current}
        plan = evaluate_plan(run, [quote], now=NOW)
        self.assertFalse(plan["complete"])
        self.assertEqual(plan["approvals_used"], [])

    def test_current_related_product_facts_override_compatible_old_snapshot(self):
        run, quote, _, old_wrap = compatibility_example()
        current = copy.deepcopy(old_wrap)
        current["revision"] = 2
        current["specifications"]["product_family"] = "different-family"
        run["products"] = {"wrap": current}
        plan = evaluate_plan(run, [quote], now=NOW)
        self.assertFalse(plan["complete"])
        self.assertTrue(any("incompatible" in blocker for blocker in plan["blockers"]))

    def test_short_quantity_and_fractional_packs(self):
        for amount, subtotal, total in (("2", "40", "43"), ("3.5", "70", "73")):
            run, quote, _ = example()
            quote["lines"][0].update(quantity=amount, line_total=subtotal)
            quote.update(subtotal=subtotal, total=total)
            self.assertFalse(evaluate_plan(run, [quote], now=NOW)["complete"])

    def test_changed_price_arithmetic_and_budget(self):
        run, quote, _ = example()
        quote["lines"][0]["unit_price"] = "30"
        self.assertFalse(evaluate_plan(run, [quote], now=NOW)["complete"])
        quote["lines"][0]["line_total"] = "90"
        quote.update(subtotal="90", total="93")
        self.assertIn("Quoted package exceeds the approved budget.", evaluate_plan(run, [quote], now=NOW)["blockers"])

    def test_same_supplier_quotes_cannot_cherry_pick_packages(self):
        run, quote, _ = example()
        other = copy.deepcopy(quote)
        other["quote_id"] = "q2"
        plan = evaluate_plan(run, [quote, other], now=NOW)
        self.assertFalse(plan["complete"])
        self.assertTrue(any("combined offer" in b for b in plan["blockers"]))

    def test_issued_whole_package_preserves_supplier_conditions_without_extra_flag(self):
        from buyer.explanation import explain_plan
        run, quote, _ = example()
        quote["conditions"] = ["Stock is only reserved on acceptance.",
                               "Discount applies to the full quoted package.",
                               "This is a simulated business; no real order is placed."]
        quote["discounts"][0]["conditions"] = "Purchase the full quoted package."
        plan = evaluate_plan(run, [quote], now=NOW)
        self.assertTrue(plan["complete"], plan["blockers"])
        self.assertEqual(plan["selected_offers"][0]["conditions"], quote["conditions"])
        self.assertEqual(plan["total_payable"], "63.00")
        rendered = explain_plan(plan)
        for condition in quote["conditions"]:
            self.assertIn(condition, rendered)
        self.assertIn("Purchase the full quoted package.", rendered)

    def test_explicit_unresolved_machine_conditions_still_block(self):
        for condition in ({"name": "bundle minimum", "satisfied": False},
                          {"name": "delivery", "status": "unknown"},
                          {"name": "substitution", "approval_required": True}):
            run, quote, _ = example()
            quote["conditions"] = [condition]
            plan = evaluate_plan(run, [quote], now=NOW)
            self.assertFalse(plan["complete"])

    def test_unapproved_substitute_and_validated_revision_bound_approval(self):
        run, quote, product = example()
        product["specifications"]["type"] = "moisture"
        self.assertFalse(evaluate_plan(run, [quote], now=NOW)["complete"])
        approval = {"id": "a", "run_id": "r", "request_revision": 1, "requirement_id": "wall",
                    "requirement_revision": 1, "product_id": "board", "decision": "approved",
                    "validated": True, "quote_id": "q", "quote_revision": 1,
                    "approved_specifications": {"type": "moisture"}, "evidence_refs": ["human-answer"]}
        run["approvals"] = [approval]
        plan = evaluate_plan(run, [quote], now=NOW)
        self.assertTrue(plan["complete"], plan["blockers"])
        self.assertEqual(plan["approvals_used"][0]["id"], "a")
        refusal = copy.deepcopy(approval)
        refusal.update(id="refusal", decision="rejected", source={"created_at": "2026-09-12T23:00:00Z"})
        approval["source"] = {"created_at": "2026-09-12T22:00:00Z"}
        run["approvals"].append(refusal)
        self.assertFalse(evaluate_plan(run, [quote], now=NOW)["complete"])
        run["approvals"].pop()
        approval["quote_revision"] = 0
        self.assertFalse(evaluate_plan(run, [quote], now=NOW)["complete"])

    def test_expired_or_late_quotes_are_not_feasible(self):
        run, quote, _ = example()
        quote["expires_at"] = NOW
        self.assertFalse(evaluate_plan(run, [quote], now=NOW)["complete"])
        quote["expires_at"] = "2026-09-14T23:00:00Z"
        quote["delivery"] = {"date": "2026-09-20T12:00:00-07:00"}
        self.assertFalse(evaluate_plan(run, [quote], now=NOW)["complete"])
        quote["delivery"] = {"days": 2}
        self.assertTrue(any("starting timestamp" in b for b in evaluate_plan(run, [quote], now=NOW)["blockers"]))

    def test_like_for_like_opening_comparison_only(self):
        run, quote, _ = example()
        negotiated = evaluate_plan(run, [quote], now=NOW)
        quote["discounts"] = []
        quote["total"] = "65"
        opening = evaluate_plan(run, [quote], now=NOW)
        result = compare_opening(negotiated, opening)
        self.assertEqual(result["opening_comparison"]["savings"], "2.00")
        self.assertEqual(rank_plans([opening, negotiated])[0], negotiated)
        run["requirements"][0]["quantity"] = "11"
        changed = evaluate_plan(run, [quote], now=NOW)
        self.assertFalse(compare_opening(negotiated, changed)["opening_comparison"]["comparable"])

    def test_split_requirement_uses_each_suppliers_actual_stock(self):
        run, quote, product = example()
        run["authority"]["budget_cap"] = "100"
        product["stock"] = "2"
        quote["lines"][0].update(quantity="2", line_total="40")
        quote.update(subtotal="40", total="43")
        second_product = copy.deepcopy(product)
        second_product.update(id="board2", vendor_id="v2", stock="1")
        run["candidates"].append({"requirement_id": "wall", "product": second_product})
        second = copy.deepcopy(quote)
        second.update(quote_id="q2", vendor_id="v2", subtotal="20", total="23")
        second["lines"][0].update(product_id="board2", quantity="1", line_total="20")
        run["quotes"].append(second)
        plan = evaluate_plan(run, [quote, second], now=NOW)
        self.assertTrue(plan["complete"], plan["blockers"])
        self.assertEqual(plan["total_payable"], "66")

    def test_normalized_quote_preserves_received_source_evidence(self):
        from buyer.quotes import normalize_quote
        run, quote, _ = example()
        del quote["evidence_refs"]
        normalized = normalize_quote(quote, evidence={"id": "http-response", "run_id": "r"}, now=NOW)
        run["quotes"] = [normalized]
        plan = evaluate_plan(run, [normalized], now=NOW)
        self.assertTrue(plan["complete"], plan["blockers"])
        self.assertIn("http-response", plan["selected_offers"][0]["evidence_refs"])

    def test_model_cannot_edit_a_recorded_quote_in_place(self):
        run, quote, _ = example()
        invented = copy.deepcopy(quote)
        invented["fees"] = []
        invented["total"] = "58"
        self.assertTrue(any("recorded whole quote" in b for b in evaluate_plan(run, [invented], now=NOW)["blockers"]))

    def test_changed_tax_basis_cannot_claim_savings(self):
        run, quote, _ = example()
        inclusive = evaluate_plan(run, [quote], now=NOW)
        quote["taxes"] = {"status": "excluded", "agreed": True}
        exclusive = evaluate_plan(run, [quote], now=NOW)
        self.assertFalse(compare_opening(inclusive, exclusive)["opening_comparison"]["comparable"])


if __name__ == "__main__":
    unittest.main()
