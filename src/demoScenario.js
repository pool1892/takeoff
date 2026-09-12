/**
 * Deterministic, contractor-visible state for the Takeoff MVP walkthrough.
 *
 * This is explicitly simulated fixture data, not a record of a live supplier run.
 * It deliberately contains only shared/deal and buyer-visible information: supplier
 * cost bases, reservation prices, and buyer spend limits never belong in this model.
 */

export const DEMO_MODE = "simulated";
export const PROCUREMENT_STATES = Object.freeze([
  "draft", "sourcing", "quoting", "negotiating", "needs_contractor_decision",
  "recommended", "draft_order", "complete", "blocked",
]);

const requirement = Object.freeze({
  id: "framing-lumber",
  name: "Framing package",
  quantity: 4820,
  unit: "linear ft",
  specification: "Douglas Fir 2×6 #2",
  requiredBy: "2026-09-19",
  substitutionPolicy: "Equivalent materials require contractor approval.",
});

const quotes = Object.freeze([
  {
    supplierId: "cascade",
    supplier: "Cascade Supply",
    product: "Douglas Fir 2×6 #2 framing package",
    quantity: 4820,
    unit: "linear ft",
    status: "confirmed",
    total: 76400,
    deliveryDays: 5,
    availability: "Confirmed for the requested quantity.",
    fees: "Freight included.",
    channel: "Agent-to-agent + email",
    evidence: "Simulated negotiation record and emailed quote",
    offers: [79400, 77800, 76400],
  },
  {
    supplierId: "northwest",
    supplier: "Northwest Lumber",
    product: "Douglas Fir 2×6 #2 framing package",
    quantity: 4820,
    unit: "linear ft",
    status: "confirmed",
    total: 78900,
    deliveryDays: 3,
    availability: "Confirmed for the requested quantity.",
    fees: "Freight included.",
    channel: "Email + human representative",
    evidence: "Simulated emailed quote",
    offers: [78900],
  },
  {
    supplierId: "evergreen",
    supplier: "Evergreen Building",
    product: "Douglas Fir 2×6 #2 framing package",
    quantity: 4820,
    unit: "linear ft",
    status: "proposed",
    total: 81200,
    deliveryDays: 2,
    availability: "Availability unconfirmed; supplier callback outstanding.",
    fees: "Freight not yet confirmed.",
    channel: "Phone + human representative",
    evidence: "Simulated phone call note",
    offers: [81200],
  },
]);

const activity = Object.freeze([
  { time: "12:41", type: "agent_action", message: "Searching regional suppliers." },
  { time: "12:43", type: "agent_action", message: "Quote requests sent to three suppliers." },
  { time: "12:45", type: "fact", message: "Cascade confirmed the requested quantity and five-day delivery." },
  { time: "12:48", type: "agent_action", message: "Requested a volume discount and freight inclusion from Cascade." },
  { time: "12:50", type: "result", message: "Cascade countered at $76,400 with freight included." },
]);

export const contractorDecision = Object.freeze({
  id: "delivery-tradeoff",
  question: "Cascade saves $2,500 but arrives two days later than Northwest. Is five-day delivery acceptable?",
  whyItMatters: "The answer changes whether Takeoff may optimize for the negotiated lower total or must prioritize the earlier confirmed delivery.",
  options: Object.freeze([
    { id: "accept-five-day", label: "Accept five-day delivery", priceImpact: "Save $2,500", deliveryImpact: "Arrives in 5 days" },
    { id: "require-three-day", label: "Keep three-day delivery", priceImpact: "Pay $2,500 more", deliveryImpact: "Arrives in 3 days" },
  ]),
});

function selectedQuote(decision) {
  if (decision === "accept-five-day") return quotes.find((quote) => quote.supplierId === "cascade");
  if (decision === "require-three-day") return quotes.find((quote) => quote.supplierId === "northwest");
  return undefined;
}

/** Returns a complete buyer-visible fixture after the contractor's meaningful choice. */
export function createDemoProcurement(decision = undefined) {
  if (decision !== undefined && !contractorDecision.options.some((option) => option.id === decision)) {
    throw new Error(`Unknown contractor decision: ${decision}`);
  }

  const selected = selectedQuote(decision);
  const status = selected ? "recommended" : "needs_contractor_decision";
  return {
    id: "demo-framing-001",
    mode: DEMO_MODE,
    status,
    title: "Framing procurement",
    requirements: [requirement],
    brief: {
      hardRequirements: ["Douglas Fir 2×6 #2", "4,820 linear ft", "Delivery within 7 days"],
      preferences: ["Favor confirmed delivery", "Avoid unverified substitutions"],
      priorities: [
        { name: "Delivery certainty", weight: 40 },
        { name: "Quality", weight: 30 },
        { name: "Cost", weight: 20 },
        { name: "Supplier reliability", weight: 10 },
      ],
      budgetTarget: 78000,
    },
    suppliers: quotes,
    activity,
    decision: decision ? { ...contractorDecision, selected: decision } : contractorDecision,
    recommendation: selected && {
      supplierId: selected.supplierId,
      supplier: selected.supplier,
      total: selected.total,
      deliveryDays: selected.deliveryDays,
      rationale: decision === "accept-five-day"
        ? ["Meets the required specification and seven-day delivery constraint.", "Lowest confirmed total after negotiation.", "Freight is included in the confirmed total."]
        : ["Meets the required specification and delivery preference.", "Earliest confirmed delivery among eligible quotes.", "Freight is included in the confirmed total."],
      rejectedOptions: quotes.filter((quote) => quote.supplierId !== selected.supplierId).map((quote) => ({
        supplierId: quote.supplierId,
        reason: quote.supplierId === "evergreen"
          ? "Availability and freight remain unconfirmed."
          : "Not selected after the contractor's delivery tradeoff decision.",
      })),
    },
    purchasePlan: selected && {
      status: "draft",
      notice: "Draft purchase plan only — no external order has been placed.",
      supplier: selected.supplier,
      lineItems: [{ product: selected.product, quantity: selected.quantity, unit: selected.unit, total: selected.total }],
      totalPayable: selected.total,
      delivery: `${selected.deliveryDays}-day delivery`,
      conditions: [selected.fees, selected.availability],
    },
  };
}
