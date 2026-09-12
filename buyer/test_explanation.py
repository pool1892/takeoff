import unittest

from buyer.explanation import explain_plan
from buyer.planning import evaluate_plan
from buyer.test_planning import example, NOW


class ExplanationTests(unittest.TestCase):
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
