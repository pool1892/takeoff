/**
 * Buyer-safe demo adapter for the supplier market fixture.
 *
 * The matching Python fixture is the source of product, quantity, unit, list
 * price, availability, and delivery values.  This module intentionally contains
 * only the public projection a contractor may see; private supplier rules and
 * costs stay in `src/takeoff_suppliers/fixtures/demo.json` on the supplier side.
 */
export const PROCUREMENT_PHASES = Object.freeze([
  "draft", "briefing", "sourcing", "quoting", "negotiating", "needs_decision", "recommending", "plan_ready", "complete", "blocked",
]);

const requirements = Object.freeze([
  ["stud", "Structural framing timber", 60, "each", "38 × 89 mm · 2,440 mm · C24"],
  ["sheathing", "Structural sheathing", 20, "sheet", "OSB · 11 mm"],
  ["insulation", "Wall insulation", 10, "pack", "Mineral wool · R13"],
  ["drywall", "Interior wall board", 30, "sheet", "12.5 mm · 1,200 × 2,400 mm"],
  ["screws", "Exterior fasteners", 8, "box", "50 mm galvanized · 100/box"],
  ["membrane", "Breather membrane", 2, "roll", "Breathable · 100 m² coverage"],
  ["concrete", "Concrete mix", 30, "bag", "25 kg"],
  ["underlay", "Roof underlayment", 3, "roll", "20 m² coverage"],
].map(([id, name, quantity, unit, specification]) => Object.freeze({ id, name, quantity, unit, specification })));

const vendors = Object.freeze([
  { id: "general", name: "General Building Supply", channel: "Website", deliveryDays: 4, freight: 45, coverage: 8, status: "Quote received" },
  { id: "overstock", name: "Second Shift Materials", channel: "Email", deliveryDays: 5, freight: 35, coverage: 4, status: "Quote received" },
  { id: "local", name: "Neighborhood Delivery Supply", channel: "Supplier agent", deliveryDays: 3, freight: 20, coverage: 6, status: "Negotiating" },
  { id: "trader", name: "Forward Materials Desk", channel: "Supplier agent", deliveryDays: 14, freight: 40, coverage: 3, status: "Partial response" },
]);

const priceBooks = Object.freeze({
  general: { stud: 6, sheathing: 22, insulation: 35, drywall: 15, screws: 12, membrane: 80, concrete: 8, underlay: 55 },
  overstock: { stud: 5.7, sheathing: 20.9, drywall: 14.25, screws: 11.4 },
  local: { stud: 6.36, insulation: 37.1, screws: 12.72, membrane: 84.8, concrete: 8.48, underlay: 58.3 },
  trader: { stud: 6, sheathing: 22, concrete: 8 },
});

const basePriorities = Object.freeze({ delivery: 40, quality: 30, cost: 20, reliability: 10 });

function quoteFor(vendor) {
  const prices = priceBooks[vendor.id];
  const lines = requirements.filter((requirement) => prices[requirement.id] !== undefined).map((requirement) => ({
    ...requirement, unitPrice: prices[requirement.id], total: requirement.quantity * prices[requirement.id], match: "exact",
  }));
  const subtotal = lines.reduce((sum, line) => sum + line.total, 0);
  return { ...vendor, lines, subtotal, total: subtotal + vendor.freight, complete: lines.length === requirements.length,
    unknowns: lines.length === requirements.length ? [] : [`${requirements.length - lines.length} requirements are not covered by this supplier.`] };
}

export const publicMarket = Object.freeze({ requirements, quotes: vendors.map(quoteFor) });

export function createProcurementState({ mode = "demo", phase = "draft", priorities = basePriorities, decision } = {}) {
  if (!PROCUREMENT_PHASES.includes(phase)) throw new Error(`Unknown phase: ${phase}`);
  const recommendation = decision === "faster" ? "general" : undefined;
  return {
    mode, phase, project: { name: "Custom Home", location: "Project site · Seattle, WA", neededBy: "September 19, 2026", source: "Contractor material request" },
    requirements: publicMarket.requirements, priorities: { ...priorities }, quotes: publicMarket.quotes,
    decision, recommendation,
    activity: [
      ["Requirements structured from contractor request", "fact"], ["Priority brief confirmed before supplier outreach", "fact"],
      ["Four supplier channels searched", "action"], ["General Building Supply returned complete coverage", "fact"],
      ["Second Shift Materials returned partial catalog coverage", "fact"], ["Neighborhood Delivery Supply is evaluating a package counter", "action"],
    ],
  };
}

export function transition(state, event) {
  const next = { ...state };
  if (event === "start") next.phase = "briefing";
  else if (event === "priorities-confirmed") next.phase = "sourcing";
  else if (event === "quotes-ready") next.phase = "negotiating";
  else if (event === "decision-needed") next.phase = "needs_decision";
  else if (event === "choose-faster") { next.decision = "faster"; next.recommendation = "general"; next.phase = "recommending"; }
  else if (event === "choose-lower-cost") { next.decision = "lower-cost"; next.phase = "blocked"; }
  else if (event === "plan-ready" && next.recommendation) next.phase = "plan_ready";
  else throw new Error(`Invalid procurement event: ${event}`);
  return next;
}

export function completeQuote(state) { return state.quotes.find((quote) => quote.complete); }
