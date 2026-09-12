"""Offline integration regressions for the buyer's durable command boundary."""
from copy import deepcopy
import json
import unittest
from unittest.mock import patch

from buyer import cli


class FakeAPI:
    def __init__(self, response=None, failure=None, rows=None):
        self.response = response or {"id": "mail-1", "delivery_status": "sent"}
        self.failure = failure
        self.rows = rows or []
        self.calls = []

    def call(self, path, method="GET", body=None, **kwargs):
        self.calls.append((path, method, deepcopy(body), kwargs))
        if method == "POST":
            if self.failure:
                raise self.failure
            return deepcopy(self.response)
        return {"data": deepcopy(self.rows), "has_more": False}

    @property
    def posts(self):
        return [call for call in self.calls if call[1] == "POST"]


def run_state():
    return {"task_id": "task-1", "run_id": "run-1", "request_revision": 1,
            "agent_id": "buyer-agent", "remaining_actions": 5,
            "authority": {"supplier_inquiries": True, "supplier_negotiation": True},
            "requirements": [{"id": "wall", "revision": 1, "quantity": 12, "unit": "sheet",
                              "source_text": "twelve regular sheets", "specifications": {"type": "regular"}}],
            "suppliers": [{"id": "general", "email": "synthetic-vendor@example.test"}],
            "candidates": {"candidate-1": {"id": "candidate-1", "run_id": "run-1", "request_revision": 1,
                "requirement_id": "wall", "requirement_revision": 1, "product_id": "board-moisture",
                "product_revision": 1, "assessment": {"status": "needs_approval",
                    "mismatches": [{"attribute": "type", "required": "regular", "actual": "moisture"}]}}}}


def inquiry():
    return {"id": "ask-1", "type": "inquire", "run_id": "run-1", "request_revision": 1,
            "vendor_id": "general", "message": "Please quote twelve sheets and confirm availability."}


class CLITests(unittest.TestCase):
    def setUp(self):
        self.state = run_state()
        self.snapshots = []

    def persist(self):
        self.snapshots.append(deepcopy(self.state))

    def test_snapshot_indexes_large_evidence_without_repeating_its_body(self):
        source = {"id": "supplier-mail", "channel": "email", "vendor_id": "general",
                  "body": "large-supplier-source " * 10000}
        self.state["evidence"] = {source["id"]: source}
        self.state["events"] = [{"type": "supplier_reply", "at": "2026-09-12T21:00:00Z",
                                 "content": deepcopy(source)}]
        result = cli.execute("snapshot", {}, self.state, self.persist, FakeAPI())
        self.assertLess(len(json.dumps(result)), 5000)
        self.assertEqual(result["evidence"][0]["id"], source["id"])
        self.assertNotIn("large-supplier-source", json.dumps(result))
        fetched = cli.execute("evidence", {"id": source["id"]}, self.state, self.persist, FakeAPI())
        self.assertEqual(fetched, source)
        self.assertFalse(self.snapshots)

    def test_confirmed_action_retry_returns_same_result_without_new_post(self):
        api = FakeAPI()
        first = cli.execute("send", inquiry(), self.state, self.persist, api)
        # Reload a saved snapshot, rather than relying on shared in-memory objects.
        self.state = deepcopy(self.snapshots[-1])
        repeated = cli.execute("send", inquiry(), self.state, self.persist, api)
        self.assertEqual(repeated, first)
        self.assertEqual(len(api.posts), 1)
        self.assertEqual(self.state["remaining_actions"], 4)
        self.assertEqual(api.posts[0][2]["idempotency_key"], "takeoff-task-1-ask-1")
        # The live service requires the Markdown authoring field for delivery.
        envelope = json.loads(api.posts[0][2]["body_markdown"])
        self.assertEqual(envelope['message'], inquiry()['message'])
        self.assertEqual(envelope['run_id'], 'run-1')
        self.assertNotIn('body_text', api.posts[0][2])

    def test_changed_action_payload_cannot_reuse_confirmed_identity(self):
        api = FakeAPI()
        cli.execute("send", inquiry(), self.state, self.persist, api)
        changed = inquiry()
        changed["message"] = "Different order and destination terms."
        with self.assertRaises(ValueError):
            cli.execute("send", changed, self.state, self.persist, api)
        self.assertEqual(len(api.posts), 1)
        self.assertEqual(self.state["remaining_actions"], 4)

    def test_uncertain_send_is_saved_before_post_and_uses_same_retry_key(self):
        api = FakeAPI(failure=TimeoutError("synthetic connection lost after send"))
        with self.assertRaises(TimeoutError):
            cli.execute("send", inquiry(), self.state, self.persist, api)
        durable = self.snapshots[-1]
        self.assertEqual(durable["actions"]["ask-1"]["status"], "sending")
        self.assertEqual(durable["remaining_actions"], 4)
        saved_body = deepcopy(durable["actions"]["ask-1"]["body"])
        self.state = deepcopy(durable)
        retry = FakeAPI()
        cli.execute("send", inquiry(), self.state, self.persist, retry)
        self.assertEqual(retry.posts[0][2], saved_body)
        self.assertEqual(self.state["remaining_actions"], 4)

    def test_offer_requires_exact_preserved_supplier_object_and_source(self):
        quote = {"quote_id": "q-1", "run_id": "run-1", "request_id": "ask-1",
                 "vendor_id": "general", "revision": 1, "status": "issued", "currency": "USD",
                 "lines": [{"requirement_id": "wall", "product_id": "board", "quantity": 12,
                            "unit": "sheet", "unit_price": "10", "line_total": "120"}],
                 "subtotal": "120", "fees": [], "discounts": [], "total": "120",
                 "taxes": {"status": "known", "amount": "0"}, "delivery": {"days": 2},
                 "expires_at": "2099-01-01T00:00:00Z"}
        self.state["evidence"] = {"mail-source": {"id": "mail-source", "run_id": "run-1",
            "vendor_id": "general", "body": "Supplier response:\n" + json.dumps({"quote": quote})}}
        result = cli.execute("offer", {"source_id": "mail-source", "quote": quote}, self.state, self.persist, FakeAPI())
        self.assertEqual(self.state["quotes"]["q-1"], quote)
        self.assertEqual(self.state["quote_sources"]["q-1"], "mail-source")
        self.assertIn("mail-source", result["evidence_refs"])
        edited = deepcopy(quote)
        edited["total"] = "100"
        with self.assertRaises(ValueError):
            cli.execute("offer", {"source_id": "mail-source", "quote": edited}, self.state, self.persist, FakeAPI())
        self.assertEqual(self.state["quotes"]["q-1"]["total"], "120")

    def test_plan_restores_separate_evidence_without_rewriting_supplier_quote(self):
        from buyer.test_planning import example
        self.state, quote, _ = example()
        quote.pop("evidence_refs")
        quote["expires_at"] = "2099-01-01T00:00:00Z"
        self.state["quotes"] = {"q": quote}
        self.state["quote_sources"] = {"q": "received-quote"}
        self.state["evidence"] = {"received-quote": {"id": "received-quote", "run_id": "r",
                                                    "vendor_id": "v", "data": deepcopy(quote)}}
        original = deepcopy(quote)
        result = cli.execute("plan", {"quote_ids": ["q"]}, self.state, self.persist, FakeAPI())
        self.assertTrue(result["complete"], result["blockers"])
        self.assertIn("received-quote", result["selected_offers"][0]["evidence_refs"])
        self.assertEqual(self.state["quotes"]["q"], original)

    def test_decision_crash_preserves_immutable_proposal_before_post(self):
        proposal = {"id": "substitute-1", "run_id": "run-1", "request_revision": 1,
                    "requirement_id": "wall", "requirement_revision": 1, "product_id": "board-moisture",
                    "candidate_id": "candidate-1", "product_revision": 1,
                    "changed_attributes": {"type": "moisture"}}
        payload = {"proposal": proposal, "question": "Approve moisture board instead of regular board?"}
        api = FakeAPI(failure=TimeoutError("synthetic comment response lost"))
        with self.assertRaises(TimeoutError):
            cli.execute("decision", payload, self.state, self.persist, api)
        durable = self.snapshots[-1]
        self.assertIn("substitute-1", durable.get("proposals", {}))
        self.assertEqual(durable["proposals"]["substitute-1"]["changed_attributes"], {"type": "moisture"})
        self.state = deepcopy(durable)
        changed = deepcopy(payload)
        changed["proposal"]["changed_attributes"] = {"type": "different"}
        with self.assertRaises(ValueError):
            cli.execute("decision", changed, self.state, self.persist, api)
        self.assertEqual(len(api.posts), 1)

    def test_confirmed_decision_cannot_change_proposal_or_visible_question(self):
        proposal = {"id": "substitute-1", "run_id": "run-1", "request_revision": 1,
                    "requirement_id": "wall", "requirement_revision": 1, "product_id": "board-moisture",
                    "candidate_id": "candidate-1", "product_revision": 1,
                    "changed_attributes": {"type": "moisture"}}
        payload = {"proposal": proposal, "question": "Approve moisture board instead of regular board?"}
        api = FakeAPI(response={"id": "question-comment"})
        first = cli.execute("decision", payload, self.state, self.persist, api)
        repeated = cli.execute("decision", deepcopy(payload), self.state, self.persist, api)
        self.assertEqual(repeated, first)
        for changed in ({"proposal": {**proposal, "product_id": "different"}, "question": payload["question"]},
                        {"proposal": proposal, "question": "Approve without the previous price caveat?"}):
            with self.assertRaises(ValueError):
                cli.execute("decision", changed, self.state, self.persist, api)
        self.assertEqual(len(api.posts), 1)

    def test_uncertain_comment_does_not_adopt_older_identical_content(self):
        body = {"content": "The quote is ready."}
        self.state["publications"] = {"pub-1": {"body": body, "status": "sending",
                                                "at": "2026-09-12T23:00:00+00:00"}}
        api = FakeAPI(rows=[{"id": "old-comment", "content": body["content"], "parent_id": None,
                             "author": {"id": "buyer-agent"}, "created_at": "2026-09-12T22:00:00+00:00"}])
        with self.assertRaises(ValueError):
            cli.comment(api, self.state, self.persist, "pub-1", body["content"])
        self.assertFalse(api.posts)
        self.assertNotIn("remote_id", self.state["publications"]["pub-1"])

    def test_comment_reconciliation_compares_instants_across_timezones(self):
        body = {"content": "The quote is ready."}
        self.state["publications"] = {"pub-1": {"body": body, "status": "sending",
                                                "at": "2026-09-12T16:00:00-07:00"}}
        api = FakeAPI(rows=[{"id": "old-comment", "content": body["content"], "parent_id": None,
                             "author": {"id": "buyer-agent"}, "created_at": "2026-09-12T22:00:00Z"}])
        with self.assertRaises(ValueError):
            cli.comment(api, self.state, self.persist, "pub-1", body["content"])
        self.assertFalse(api.posts)

    def test_uncertain_comment_recovers_single_current_match_without_post(self):
        body = {"content": "The quote is ready."}
        self.state["publications"] = {"pub-1": {"body": body, "status": "sending",
                                                "at": "2026-09-12T23:00:00+00:00"}}
        api = FakeAPI(rows=[{"id": "new-comment", "content": body["content"], "parent_id": None,
                             "author": {"id": "buyer-agent"}, "created_at": "2026-09-12T23:00:01+00:00"}])
        recovered = cli.comment(api, self.state, self.persist, "pub-1", body["content"])
        self.assertEqual(recovered, "new-comment")
        self.assertFalse(api.posts)

    def test_uncertain_comment_multiple_current_matches_stays_unresolved(self):
        body = {"content": "The quote is ready."}
        self.state["publications"] = {"pub-1": {"body": body, "status": "sending",
                                                "at": "2026-09-12T23:00:00+00:00"}}
        api = FakeAPI(rows=[{"id": f"possible-{index}", "content": body["content"], "parent_id": None,
                             "author": {"id": "buyer-agent"}, "created_at": "2026-09-12T23:00:01+00:00"}
                            for index in (1, 2)])
        with self.assertRaises(ValueError):
            cli.comment(api, self.state, self.persist, "pub-1", body["content"])
        self.assertFalse(api.posts)


if __name__ == "__main__":
    unittest.main()
