import { contractorDecision, createDemoProcurement } from "./demoScenario.js";
import "./styles.css";

const money = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });
const stages = ["Request", "Brief", "Discover", "Compare", "Negotiate", "Decision", "Recommend"];
const app = document.querySelector("#app");
let role = "contractor";
let active = "Decision";
let decision;
let detailOpen = false;

const icon = (name) => ({
  home: "⌂", brief: "▤", sources: "◌", quotes: "↔", negotiate: "⇄", decision: "◇", plan: "✓", vendors: "◫", settings: "⚙",
}[name] || "•");

function statusTag(status) {
  const cls = status === "confirmed" ? "good" : status === "proposed" ? "warn" : "muted";
  return `<span class="tag ${cls}"><i></i>${status}</span>`;
}

function renderShell(content) {
  const nav = role === "contractor"
    ? [["home", "Overview"], ["brief", "Procurement brief"], ["sources", "Supplier activity"], ["quotes", "Quotes & evidence"], ["negotiate", "Negotiation"], ["decision", "Approvals"], ["plan", "Buying plan"]]
    : [["home", "Opportunity inbox"], ["quotes", "Active deals"], ["sources", "Catalog & inventory"], ["negotiate", "Agent strategy"], ["decision", "Human approvals"], ["plan", "Offer history"]];
  app.innerHTML = `<div class="app-shell">
    <aside class="sidebar">
      <div class="brand"><span class="mark">▲</span><span>TAKEOFF</span></div>
      <div class="workspace"><span class="avatar">${role === "contractor" ? "AC" : "CS"}</span><span><b>${role === "contractor" ? "Alder Carter" : "Cascade Supply"}</b><small>${role === "contractor" ? "General contractor" : "Supplier workspace"}</small></span><button class="switch-role" title="Switch workspace">⇄</button></div>
      <nav>${nav.map(([key, label]) => `<button class="nav-item ${label.includes(active) || (active === "Decision" && label === "Approvals") ? "active" : ""}" data-nav="${label}"><span>${icon(key)}</span>${label}</button>`).join("")}</nav>
      <div class="sidebar-bottom"><div class="mode-label"><span class="pulse"></span>SIMULATED DEMO</div><button class="help">? Help center</button></div>
    </aside>
    <main><header><div><p class="eyebrow">${role === "contractor" ? "RIVERSIDE APARTMENTS · SEATTLE, WA" : "PRIVATE SUPPLIER CONSOLE · SEATTLE, WA"}</p><h1>${role === "contractor" ? "Framing procurement" : "Framing opportunity"}</h1></div><div class="header-actions"><button class="quiet" id="viewEvidence">⌘ Evidence</button><button class="profile">${role === "contractor" ? "AC" : "CS"}</button></div></header>${content}</main>
  </div>`;
  bindShell();
}

function contractorView() {
  const task = createDemoProcurement(decision);
  const selected = task.recommendation;
  const stageIndex = selected ? 6 : 5;
  renderShell(`<section class="stagebar"><div class="stage-track">${stages.map((stage, index) => `<button class="stage ${index <= stageIndex ? "done" : ""} ${stage === active ? "current" : ""}" data-stage="${stage}"><span>${index < stageIndex ? "✓" : index + 1}</span>${stage}</button>`).join("")}</div><div class="agent-state"><span class="agent-dot"></span><b>${selected ? "Plan ready" : "Needs your input"}</b><small>Hermes buyer</small></div></section>
  <section class="hero-grid">
    <div class="card decision-card">
      <div class="card-kicker"><span class="agent-badge">✦</span> TAKEOFF NEEDS A DECISION <span class="tag urgent"><i></i>Action required</span></div>
      <h2>${selected ? `Your decision selected ${selected.supplier}.` : contractorDecision.question}</h2>
      <p class="lead">${selected ? "The recommendation and draft buying plan have been recalculated using your approved delivery tradeoff." : contractorDecision.whyItMatters}</p>
      ${selected ? recommendation(selected, task) : decisionOptions()}
    </div>
    <div class="side-stack">
      <div class="card brief-card"><div class="card-top"><div><p class="eyebrow">PROCUREMENT BRIEF</p><h3>What Takeoff is optimizing</h3></div><button class="text-button">Edit brief</button></div>
        <div class="requirement"><span>Material package</span><b>Douglas Fir 2×6 #2</b><small>4,820 linear ft · Exact match required</small></div>
        <div class="priorities">${task.brief.priorities.map((p) => `<div><span>${p.name}</span><em>${p.weight}%</em><i><b style="width:${p.weight * 2}%"></b></i></div>`).join("")}</div>
      </div>
      <div class="card activity-card"><div class="card-top"><div><p class="eyebrow">LIVE ACTIVITY</p><h3>Supplier work</h3></div><button class="text-button" id="activityBtn">View all</button></div>${task.activity.slice(-3).map((event) => `<div class="event"><span class="event-dot ${event.type}"></span><div><b>${event.message}</b><small>${event.time} · ${event.type === "fact" ? "Supplier fact" : "Agent action"}</small></div></div>`).join("")}</div>
    </div>
  </section>
  <section class="card quotes-card"><div class="card-top"><div><p class="eyebrow">NORMALIZED QUOTES</p><h3>Every supplier, on the same terms</h3></div><button class="text-button" id="compareBtn">Open comparison</button></div><div class="quote-table"><div class="quote-head"><span>Supplier & channel</span><span>Availability</span><span>Delivery</span><span>Total payable</span><span>Status</span></div>${task.suppliers.map((quote) => `<button class="quote-row" data-quote="${quote.supplierId}"><span><b>${quote.supplier}</b><small>${quote.channel}</small></span><span>${quote.availability}</span><span><b>${quote.deliveryDays} days</b></span><span><b>${money.format(quote.total)}</b><small>${quote.fees}</small></span><span>${statusTag(quote.status)} <b class="chevron">›</b></span></button>`).join("")}</div></section>
  ${detailOpen ? evidencePanel(task) : ""}`);
}

function decisionOptions() { return `<div class="option-list">${contractorDecision.options.map((option) => `<button class="decision-option" data-decision="${option.id}"><span class="radio"></span><span><b>${option.label}</b><small>${option.deliveryImpact}</small></span><strong>${option.priceImpact}</strong><span class="arrow">→</span></button>`).join("")}</div><div class="decision-footer"><span>Decision applies only to this task. You can revise the brief later.</span><button class="primary" disabled>Choose an option to continue</button></div>`; }

function recommendation(selected, task) { const saving = 78900 - selected.total; return `<div class="recommendation"><div class="recommendation-total"><span>Recommended total</span><strong>${money.format(selected.total)}</strong><small>${selected.deliveryDays}-day confirmed delivery · Freight included</small></div><div class="recommendation-reasons">${task.recommendation.rationale.map((r) => `<p><span>✓</span>${r}</p>`).join("")}</div><div class="decision-footer"><span class="approved">✓ Approval recorded · ${decision === "accept-five-day" ? "Five-day delivery accepted" : "Three-day delivery required"}</span><button class="primary" id="planBtn">Review draft plan ${saving > 0 ? `· Saves ${money.format(saving)}` : ""}</button></div></div>`; }

function evidencePanel(task) { return `<div class="overlay" id="closeOverlay"><aside class="evidence-panel" onclick="event.stopPropagation()"><div class="card-top"><div><p class="eyebrow">EVIDENCE TRAIL</p><h3>Quote & decision record</h3></div><button class="close" id="closeEvidence">×</button></div><div class="evidence-note"><b>Simulated fixture</b><p>This is seeded demonstration data, not a live supplier run or external order.</p></div>${task.suppliers.map((quote) => `<article class="evidence-item"><div><span class="channel">${quote.channel}</span>${statusTag(quote.status)}</div><h4>${quote.supplier}</h4><p>${quote.product}</p><dl><dt>Quote evidence</dt><dd>${quote.evidence}</dd><dt>Terms</dt><dd>${quote.availability} ${quote.fees}</dd></dl></article>`).join("")}</aside></div>`; }

function vendorView() { renderShell(`<section class="vendor-hero"><div><p class="eyebrow">INCOMING AGENT-TO-AGENT REQUEST</p><h2>Riverside Apartments framing package</h2><p>Takeoff is requesting a confirmed package offer for 4,820 linear ft of Douglas Fir 2×6 #2.</p></div><span class="tag good"><i></i>Buyer verified</span></section><section class="vendor-grid"><div class="card"><div class="card-top"><div><p class="eyebrow">SHARED DEAL</p><h3>Offer progression</h3></div><span class="tag good"><i></i>Negotiating</span></div><div class="offer-ladder"><div><span>Buyer request</span><b>4,820 linear ft</b><small>Delivery within 7 days</small></div><div><span>Your opening offer</span><b>$79,400</b><small>Freight not included</small></div><div class="current-offer"><span>Your counteroffer</span><b>$76,400</b><small>Freight included · 5-day delivery</small></div></div><button class="primary wide" id="acceptOffer">Confirm current offer</button></div><div class="card private-card"><p class="eyebrow">PRIVATE TO CASCADE SUPPLY</p><h3>Agent strategy & guardrails</h3><div class="private-notice">🔒 This information is never sent to the buyer workspace.</div><label>Offer authority <input type="range" min="0" max="100" value="72" /><span>Package counteroffer permitted</span></label><label>Delivery promise <select><option>5-day delivery</option><option>6-day delivery</option></select><span>Must remain confirmed before sharing</span></label><div class="strategy-check"><span>✓ Freight may be included</span><span>✓ Human takeover available</span><span>✓ Counteroffer needs audit record</span></div></div></section><section class="card shared-record"><div class="card-top"><div><p class="eyebrow">WHAT THE BUYER CAN SEE</p><h3>Shared deal record</h3></div><span class="tag muted"><i></i>Agent-to-agent</span></div><div class="shared-fields"><span>Requirement <b>Douglas Fir 2×6 #2</b></span><span>Quantity <b>4,820 linear ft</b></span><span>Current offer <b>$76,400, freight included</b></span><span>Delivery <b>5 days, confirmed</b></span></div></section></section>`); }

function bindShell() {
  document.querySelector(".switch-role")?.addEventListener("click", () => { role = role === "contractor" ? "vendor" : "contractor"; render(); });
  document.querySelectorAll("[data-stage]").forEach((button) => button.addEventListener("click", () => { active = button.dataset.stage; render(); }));
  document.querySelectorAll("[data-decision]").forEach((button) => button.addEventListener("click", () => { decision = button.dataset.decision; active = "Recommend"; render(); }));
  document.querySelector("#viewEvidence")?.addEventListener("click", () => { detailOpen = true; render(); });
  document.querySelector("#compareBtn")?.addEventListener("click", () => { detailOpen = true; render(); });
  document.querySelectorAll("[data-quote]").forEach((button) => button.addEventListener("click", () => { detailOpen = true; render(); }));
  document.querySelector("#closeOverlay")?.addEventListener("click", () => { detailOpen = false; render(); });
  document.querySelector("#closeEvidence")?.addEventListener("click", () => { detailOpen = false; render(); });
  document.querySelector("#planBtn")?.addEventListener("click", () => { detailOpen = true; render(); });
  document.querySelector("#acceptOffer")?.addEventListener("click", (event) => { event.target.textContent = "Offer confirmed · buyer notified"; event.target.classList.add("confirmed-button"); });
}
function render() { role === "contractor" ? contractorView() : vendorView(); }
render();
