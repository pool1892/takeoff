import unittest

from buyer.explanation import explain_plan
from buyer.planning import evaluate_plan
from buyer.test_planning import example, NOW


class ExplanationTests(unittest.TestCase):
    def test_friendly_names_dates_and_compact_receipts_leave_math_unchanged(self):
        run, quote, product = example()
        run["suppliers"] = [{"id": "v", "name": "General Building Supply"}]
        product["name"] = "Regular half-inch drywall"
        quote["quote_id"] = "quote_0123456789abcdef_long_receipt"
        quote["conditions"] = ["Stock is reserved only on acceptance."]
        plan = evaluate_plan(run, [quote], now=NOW)
        rendered = explain_plan(plan)
        table = "\n".join(line for line in rendered.splitlines() if line.startswith("|"))
        self.assertIn("Regular half-inch drywall", table)
        self.assertIn("General Building Supply [1]", table)
        self.assertIn("3 packs", table)
        self.assertNotIn(quote["quote_id"], table)
        self.assertNotIn("offer-1", table)
        self.assertEqual(rendered.count(quote["quote_id"]), 1)
        self.assertIn("Sep 15, 2026, 12:00 PM (UTC-07:00)", rendered)
        self.assertIn("Quote valid until Sep 14, 2026", rendered)
        self.assertIn("Stock is reserved only on acceptance.", rendered)
        self.assertEqual(plan["total_payable"], "63.00")
        self.assertEqual(plan["selected_offers"][0]["lines"][0]["product_id"], "board")
        self.assertNotIn("global optimality", rendered)
        self.assertNotIn("human comparison", rendered)
        self.assertNotIn("Opening-offer comparison unavailable", rendered)
        self.assertEqual(rendered.count("[Demo context]"), 1)

    def test_quote_line_name_is_preserved_and_ids_remain_fallbacks(self):
        run, quote, product = example()
        product["name"] = "Catalog description"
        quote["lines"][0]["name"] = "Supplier's quoted board"
        plan = evaluate_plan(run, [quote], now=NOW)
        self.assertEqual(plan["selected_offers"][0]["lines"][0]["product_name"], "Supplier's quoted board")
        del quote["lines"][0]["name"]
        del product["name"]
        rendered = explain_plan(evaluate_plan(run, [quote], now=NOW))
        self.assertIn("| board | 3 packs | v [1] |", rendered)

    def test_comparable_opening_price_difference_is_kept_without_extra_claims(self):
        from buyer.planning import compare_opening
        run, quote, _ = example()
        negotiated = evaluate_plan(run, [quote], now=NOW)
        quote["discounts"] = []
        quote["total"] = "65"
        opening = evaluate_plan(run, [quote], now=NOW)
        rendered = explain_plan(compare_opening(negotiated, opening))
        self.assertIn("Opening-offer package: USD 65.00", rendered)
        self.assertIn("Price difference under the same requirements: USD 2.00", rendered)
        self.assertNotIn("human comparison", rendered)

    def test_explains_selected_terms_and_nonordering_endpoint(self):
        run, quote, _ = example()
        text = explain_plan(evaluate_plan(run, [quote], now=NOW))
        for expected in ("1 of 1", "USD 63.00", "offer-1", "3 pack", "no order placed", "delivery", "package"):
            self.assertIn(expected, text)

    def test_partial_result_and_rejected_evidence_are_explicit(self):
        run, quote, _ = example()
        del quote["taxes"]
        run["quotes"].append({"quote_id": "other", "evidence_refs": ["alternative-quote"]})
        text = explain_plan(evaluate_plan(run, [quote], now=NOW))
        self.assertIn("Total payable: unknown", text)
        self.assertIn("not ready to buy", text)
        self.assertIn("alternative-quote", text)
        self.assertIn("no further rejection reason recorded", text)
        self.assertNotIn("saved hours", text)


if __name__ == "__main__":
    unittest.main()
