import { contractorDecision, createDemoProcurement } from "../demoScenario.js";

/**
 * Buyer-facing procurement boundary.
 *
 * Live service contract:
 * GET  {baseUrl}/v1/procurement/{taskId}             -> ProcurementSnapshot
 * GET  {baseUrl}/v1/procurement/{taskId}/events     -> text/event-stream
 * POST {baseUrl}/v1/procurement/{taskId}/actions    -> { type, payload }
 *
 * Stream events use `{ id, type, data }`. Supported types are `snapshot`,
 * `agent_activity`, `supplier_discovery`, `quote`, `negotiation`, `decision`,
 * `recommendation`, and `error`. Event IDs permit SSE resume via Last-Event-ID.
 * Every payload is buyer-safe: supplier private costs, floors, and credentials
 * must never be emitted through this boundary.
 */
export const LIVE_EVENT_TYPES = Object.freeze([
  "snapshot", "agent_activity", "supplier_discovery", "quote", "negotiation", "decision", "recommendation", "error",
]);

const copy = (value) => structuredClone(value);
const now = () => new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

export function normalizeSnapshot(snapshot, connection = "live") {
  const task = snapshot || {};
  return {
    id: task.id || task.taskId || "unknown-task",
    mode: task.mode === "demo" || task.mode === "simulated" ? "demo" : "live",
    title: task.title || "Procurement",
    status: task.status || task.phase || "draft",
    brief: task.brief || { priorities: [] },
    requirements: task.requirements || [],
    activity: task.activity || [],
    suppliers: task.suppliers || task.quotes || [],
    quotes: task.quotes || task.suppliers || [],
    negotiations: task.negotiations || [],
    decision: task.decision || null,
    recommendation: task.recommendation || null,
    purchasePlan: task.purchasePlan || null,
    connection,
    error: task.error || null,
  };
}

function appendActivity(state, event) {
  return [...state.activity, { time: event.time || now(), type: event.type || "agent_action", message: event.message || "Procurement updated." }];
}

export function applyProcurementEvent(state, event) {
  if (!LIVE_EVENT_TYPES.includes(event.type)) return state;
  if (event.type === "snapshot") return normalizeSnapshot(event.data, state.connection);
  const next = copy(state);
  const data = event.data || {};
  if (event.type === "agent_activity" || event.type === "supplier_discovery") next.activity = appendActivity(next, data);
  if (event.type === "supplier_discovery") next.suppliers = [...next.suppliers, data.supplier || data];
  if (event.type === "quote") next.quotes = [...next.quotes.filter((quote) => (quote.id || quote.supplierId) !== (data.id || data.supplierId)), data];
  if (event.type === "negotiation") next.negotiations = [...next.negotiations, data];
  if (event.type === "decision") next.decision = data;
  if (event.type === "recommendation") { next.recommendation = data; next.status = "recommended"; }
  if (event.type === "error") next.error = data.message || "The procurement service reported an error.";
  return next;
}

class BaseAdapter {
  constructor(initialState) { this.state = initialState; this.listeners = new Set(); }
  emit() { this.listeners.forEach((listener) => listener(this.state)); }
  subscribe(listener) { this.listeners.add(listener); listener(this.state); return () => this.listeners.delete(listener); }
  getSnapshot() { return this.state; }
}

export class DemoProcurementAdapter extends BaseAdapter {
  constructor() { super(normalizeSnapshot(createDemoProcurement(), "demo")); }
  async startProcurement() { this.state = { ...this.state, status: "needs_contractor_decision" }; this.emit(); }
  async answerPriorities() { this.emit(); }
  async submitApproval() { this.emit(); }
  async submitNegotiationDecision(decision) {
    this.state = normalizeSnapshot(createDemoProcurement(decision), "demo");
    this.emit();
  }
  disconnect() {}
}

export class LiveProcurementAdapter extends BaseAdapter {
  constructor({ baseUrl, taskId, fetchImpl = fetch, eventSourceFactory = (url) => new EventSource(url), retryMs = 1500 } = {}) {
    if (!baseUrl || !taskId) throw new Error("Live procurement requires VITE_PROCUREMENT_API_URL and VITE_PROCUREMENT_TASK_ID.");
    super(normalizeSnapshot({ id: taskId, title: "Loading procurement" }, "connecting"));
    this.baseUrl = baseUrl.replace(/\/$/, ""); this.taskId = taskId; this.fetchImpl = fetchImpl;
    this.eventSourceFactory = eventSourceFactory; this.retryMs = retryMs; this.eventSource = null; this.retryTimer = null; this.lastEventId = null; this.closed = false;
  }
  endpoint(path = "") { return `${this.baseUrl}/v1/procurement/${encodeURIComponent(this.taskId)}${path}`; }
  async connect() {
    this.closed = false;
    try {
      const response = await this.fetchImpl(this.endpoint(), { headers: { Accept: "application/json" } });
      if (!response.ok) throw new Error(`Snapshot request failed (${response.status}).`);
      this.state = normalizeSnapshot(await response.json(), "live"); this.emit(); this.openStream();
    } catch (error) { this.fail(error); }
  }
  openStream() {
    this.eventSource?.close();
    const url = new URL(this.endpoint("/events"), globalThis.location?.href || "http://localhost/");
    if (this.lastEventId) url.searchParams.set("lastEventId", this.lastEventId);
    this.eventSource = this.eventSourceFactory(url.toString());
    this.eventSource.onopen = () => { this.state = { ...this.state, connection: "live", error: null }; this.emit(); };
    this.eventSource.onmessage = (message) => this.receive(message);
    LIVE_EVENT_TYPES.filter((type) => type !== "snapshot").forEach((type) => this.eventSource.addEventListener(type, (message) => this.receive(message, type)));
    this.eventSource.onerror = () => this.reconnect();
  }
  receive(message, forcedType) {
    try {
      const parsed = JSON.parse(message.data); const event = { id: message.lastEventId, type: forcedType || parsed.type, data: parsed.data ?? parsed };
      if (event.id) this.lastEventId = event.id;
      this.state = applyProcurementEvent({ ...this.state, connection: "live", error: null }, event); this.emit();
    } catch { this.fail(new Error("Received an invalid procurement event.")); }
  }
  reconnect() {
    if (this.closed || this.retryTimer) return;
    this.eventSource?.close(); this.state = { ...this.state, connection: "reconnecting", error: "Connection interrupted. Reconnecting…" }; this.emit();
    this.retryTimer = setTimeout(() => { this.retryTimer = null; this.openStream(); }, this.retryMs);
  }
  fail(error) { this.state = { ...this.state, connection: "error", error: error.message || "Unable to reach the procurement service." }; this.emit(); this.reconnect(); }
  async action(type, payload = {}) {
    const response = await this.fetchImpl(this.endpoint("/actions"), { method: "POST", headers: { "Content-Type": "application/json", Accept: "application/json" }, body: JSON.stringify({ type, payload }) });
    if (!response.ok) { const detail = await response.json().catch(() => ({})); throw new Error(detail.message || `Action failed (${response.status}).`); }
    const result = await response.json().catch(() => null);
    if (result) { this.state = normalizeSnapshot(result, this.state.connection); this.emit(); }
  }
  async startProcurement(payload) { return this.action("start_procurement", payload); }
  async answerPriorities(payload) { return this.action("priority_answers", payload); }
  async submitApproval(payload) { return this.action("approval", payload); }
  async submitNegotiationDecision(payload) { return this.action("negotiation_decision", payload); }
  disconnect() { this.closed = true; clearTimeout(this.retryTimer); this.eventSource?.close(); }
}

export function createProcurementAdapter(environment = import.meta.env) {
  if (environment.VITE_PROCUREMENT_MODE === "live") return new LiveProcurementAdapter({ baseUrl: environment.VITE_PROCUREMENT_API_URL, taskId: environment.VITE_PROCUREMENT_TASK_ID });
  return new DemoProcurementAdapter();
}
