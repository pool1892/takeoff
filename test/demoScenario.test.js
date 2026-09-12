import test from "node:test";
import assert from "node:assert/strict";
import { contractorDecision, createDemoProcurement } from "../src/demoScenario.js";

test("the fixture waits for the consequential contractor decision", () => {
  const task = createDemoProcurement();
  assert.equal(task.mode, "simulated");
  assert.equal(task.status, "needs_contractor_decision");
  assert.equal(task.recommendation, undefined);
  assert.equal(task.purchasePlan, undefined);
});

test("a five-day approval selects the negotiated eligible offer", () => {
  const task = createDemoProcurement("accept-five-day");
  assert.equal(task.status, "recommended");
  assert.equal(task.recommendation.supplier, "Cascade Supply");
  assert.equal(task.recommendation.total, 76400);
  assert.equal(task.purchasePlan.totalPayable, 76400);
  assert.match(task.purchasePlan.notice, /no external order/i);
});

test("a delivery priority selects Northwest instead of hardcoding Cascade", () => {
  const task = createDemoProcurement("require-three-day");
  assert.equal(task.recommendation.supplier, "Northwest Lumber");
  assert.equal(task.recommendation.total, 78900);
  assert.equal(task.recommendation.deliveryDays, 3);
});

test("every contractor decision option has an explicit price and delivery impact", () => {
  for (const option of contractorDecision.options) {
    assert.ok(option.priceImpact);
    assert.ok(option.deliveryImpact);
  }
});

test("contractor-visible fixture excludes private commercial state", () => {
  const serialized = JSON.stringify(createDemoProcurement("accept-five-day")).toLowerCase();
  for (const forbidden of ["cost basis", "reservation", "margin", "willingness"]) {
    assert.equal(serialized.includes(forbidden), false, `leaked: ${forbidden}`);
  }
});
