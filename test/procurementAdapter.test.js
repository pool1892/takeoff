import test from "node:test";
import assert from "node:assert/strict";
import { DemoProcurementAdapter, LiveProcurementAdapter, applyProcurementEvent } from "../src/state/procurementAdapter.js";

test("demo adapter runs an interactive, visibly simulated procurement flow", async () => {
  const adapter = new DemoProcurementAdapter();
  assert.equal(adapter.getSnapshot().mode, "demo");
  assert.equal(adapter.getSnapshot().status, "draft");
  assert.equal(adapter.getSnapshot().quotes.length, 0);
  await adapter.startProcurement();
  assert.equal(adapter.getSnapshot().status, "briefing");
  assert.equal(adapter.getSnapshot().activity.length, 1);
  await adapter.answerPriorities();
  assert.equal(adapter.getSnapshot().status, "needs_contractor_decision");
  assert.equal(adapter.getSnapshot().quotes.length, 3);
  assert.ok(adapter.getSnapshot().decision?.question);
  await adapter.submitApproval();
  assert.match(adapter.getSnapshot().activity.at(-1).message, /approval recorded/i);
  await adapter.submitNegotiationDecision("accept-five-day");
  assert.equal(adapter.getSnapshot().recommendation.supplierId, "cascade");
});

test("live adapter completes snapshot, streamed procurement events, and contractor actions", async () => {
  const calls = []; let source;
  class Source { constructor() { source = this; } addEventListener(type, cb) { this[type] = cb; } close() {} }
  const adapter = new LiveProcurementAdapter({ baseUrl: "https://buyer.example", taskId: "task-7", eventSourceFactory: () => new Source(), fetchImpl: async (url, options = {}) => {
    calls.push({ url, options });
    if (options.method === "POST") return new Response(JSON.stringify({ id: "task-7", title: "Framing", status: "sourcing" }), { status: 200 });
    return new Response(JSON.stringify({ id: "task-7", title: "Framing", status: "sourcing", activity: [] }), { status: 200 });
  } });
  await adapter.connect(); source.onopen();
  source.agent_activity({ data: JSON.stringify({ message: "Hermes requested quotes.", type: "agent_action" }), lastEventId: "9" });
  source.quote({ data: JSON.stringify({ supplierId: "cascade", supplier: "Cascade", total: 76400 }), lastEventId: "10" });
  source.decision({ data: JSON.stringify({ question: "Accept five-day delivery?", options: [] }), lastEventId: "11" });
  source.recommendation({ data: JSON.stringify({ supplier: "Cascade", total: 76400 }), lastEventId: "12" });
  assert.equal(adapter.getSnapshot().activity.length, 1);
  assert.equal(adapter.getSnapshot().quotes[0].supplier, "Cascade");
  assert.equal(adapter.getSnapshot().recommendation.supplier, "Cascade");
  await adapter.startProcurement({ requirements: [] });
  await adapter.answerPriorities({ delivery: 40 });
  await adapter.submitApproval({ approvalId: "approval-1" });
  await adapter.submitNegotiationDecision({ optionId: "accept-five-day" });
  assert.deepEqual(calls.slice(1).map(({ options }) => JSON.parse(options.body).type), ["start_procurement", "priority_answers", "approval", "negotiation_decision"]);
});

test("stream errors expose a reconnecting state", () => {
  const state = applyProcurementEvent({ activity: [], suppliers: [], quotes: [], negotiations: [] }, { type: "error", data: { message: "Supplier channel unavailable" } });
  assert.equal(state.error, "Supplier channel unavailable");
});
