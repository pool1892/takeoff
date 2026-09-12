import test from "node:test";
import assert from "node:assert/strict";
import { completeQuote, createProcurementState, transition } from "../src/state/procurementDemo.js";

test("the demo starts with a request and cannot source before the priority interview", () => {
  let state = createProcurementState();
  assert.equal(state.phase, "draft");
  state = transition(state, "start");
  assert.equal(state.phase, "briefing");
  state = transition(state, "priorities-confirmed");
  assert.equal(state.phase, "sourcing");
});

test("the public adapter uses the house supplier-market requirements and excludes private economics", () => {
  const serialized = JSON.stringify(createProcurementState()).toLowerCase();
  assert.equal(createProcurementState().requirements.length, 8);
  for (const forbidden of ["unit_cost", "margin", "reservation", "max_discount", "private"]) {
    assert.equal(serialized.includes(forbidden), false, `leaked: ${forbidden}`);
  }
});

test("only complete coverage may become the recommended draft plan", () => {
  const state = createProcurementState();
  const quote = completeQuote(state);
  assert.equal(quote.name, "General Building Supply");
  assert.equal(quote.lines.length, state.requirements.length);
  assert.equal(quote.total, quote.subtotal + quote.freight);
  assert.ok(state.quotes.filter((item) => !item.complete).every((item) => item.unknowns.length));
});

test("keeping the schedule creates a recommendation, while a lower-cost exploration stays unresolved", () => {
  let state = createProcurementState({ phase: "needs_decision" });
  state = transition(state, "choose-faster");
  assert.equal(state.phase, "recommending");
  assert.equal(state.recommendation, "general");
  state = transition(state, "plan-ready");
  assert.equal(state.phase, "plan_ready");
  assert.equal(transition(createProcurementState({ phase: "needs_decision" }), "choose-lower-cost").phase, "blocked");
});
