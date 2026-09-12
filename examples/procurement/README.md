# Proposed procurement starter

[`material-request.json`](material-request.json) is an **invented proposal for
review**, not a finalized team scenario, real jobsite request, supplier quote, or
construction-ready material schedule. Christoph approved starting from a concrete
material request and asking only missing essentials; a mandatory priority
interview is not part of this first path. The particular materials, quantities,
specifications, dates, and budgets here still need Christoph and Tapan's agreement.

The separate UX simulation in `src/demoScenario.js` uses a framing-lumber scenario.
That example and this painting package are independent provisional examples;
the team still needs to reconcile the scenario before an integrated run. Neither
fixture establishes an agreed material package or live supplier offer.

This example connects the [shared story (#1)](https://github.com/pool1892/takeoff/issues/1),
[buyer discovery (#4)](https://github.com/pool1892/takeoff/issues/4), and
[first real integration slice (#9)](https://github.com/pool1892/takeoff/issues/9).
It gives parallel work a concrete input without deciding supplier implementations
or Ehsan's Ambiguous presentation.

## Scope and identifiers

The eight lines form a small interior painting/finishing supply package: wall
paint, trim paint, caulk, masking tape, roller covers, brushes, sandpaper, and
spackling compound. Counts are supplied requirements, not quantities inferred
from floor area or coverage calculations. The specification strings are proposed
matching constraints; they make no engineering, structural, regulatory, or
cross-product equivalence claims.

Stable fixture references are `request-001`, revision `1`, `fixture-task-001`, and
`demo-interior-001`. These are synthetic IDs, not verified Ambiguous objects. Real
executions need their actual task references and distinct run IDs; preserve the
fixture source and request revision when recording adoption or later changes.
`schema_version: 0.1-proposed` labels a starting example, not a frozen API contract.

Start #9 with `first_live_path` / `slice-01`: **req-01, six one-US-gallon cans of
untinted white water-based interior wall paint with eggshell sheen**. This uses
one understandable product and unit so the first remote inquiry and recommendation
can connect quickly. The other seven requirements are for expansion. A successful
one-item slice must not be reported as completion of the eight-item package.

The synthetic all-in budget is USD 400 for that first slice and USD 1,500 for the
expanded package. Neither amount is a supplier price or a claimed market estimate.
Quotes must separately establish materials, delivery, tax, and mandatory fees;
an omitted charge is unknown. Keep the selected slice and requirement revision
with any comparison or benchmark so different scopes are not compared as savings.

## A decision the offers can create

The proposed delivery deadline is September 18, 2026 at 17:00 America/Los_Angeles,
for a synthetic San Francisco 94103 delivery zone. There is no real street address
or shipment authority. For req-01, the buyer may inquire whether delivery through
September 21 improves the supplier's terms. The original deadline remains binding
unless the contractor explicitly approves a concrete alternative after seeing its
price and timing consequences. The supplier may decline or offer no improvement;
neither a concession nor a winning package is scripted here.

Supplier inquiries, negotiation, and task-related messages are modeled as
delegated authority **only after this proposal is adopted in an actual contractor
task**. Reading the fixture alone authorizes no live sends. Orders, substitutions,
budget increases, and deadline relaxation need separate explicit authority.
Supplier offers, endpoints, credentials, and private economics belong elsewhere;
none are supplied or implied by this request.

## Linked offline flow

[`linked-flow.json`](linked-flow.json) adds **invented supplier quotes, messages,
contractor answers, and expected outcomes** for `slice-01` only. It is a proposed
test scenario, not an agreed supplier world or evidence of a live run. The shared
request, task, run, requirement, and revision references link it to the starter
request. Req-01 uses `can` consistently: one can contains one US gallon.

The cases evaluate on September 12, 2026 at noon Pacific, before the September 16
quote expiry. Replaying later does not renew a quote. Product eligibility alone
does not establish that stock, price, delivery, or quote validity is acceptable.
All quoted amounts include the fixture taxes; delivery and other fees are still
included separately in total payable. A confirmed minimum quantity of `0` means
no minimum; `null` or missing terms mean unknown. An empty confirmed bundle list
means no bundle condition.

At the original deadline, the feasible opening package costs USD 270
(`6 × 42 + 18`). Approval changes only req-01's inherited delivery deadline through
`requirement_delivery_overrides`; all other requirements keep September 18.
Revalidating the opening quotes under that approved deadline gives a USD 234
benchmark (`6 × 39`). The approved branch's revised quote totals USD 222
(`6 × 37`): **USD 12 is negotiation savings under the same approved requirements;
USD 36 is the cost difference from relaxing the deadline**. The combined USD 48
difference must not be labeled negotiation savings. No human baseline exists in
this fixture. Rejection or silence preserves the original deadline; the partial
quote cannot win, and the seven other requirements remain incomplete in every case.

## Align before the first run

- Christoph and Tapan: accept or revise the material lines, quantities, matching
  constraints, synthetic location, budgets, and delivery opportunity. A different
  package size or tradeoff is still possible.
- Tapan: provide actual buyer-visible product/offer data and the first supported
  remote channel. No supplier URL or catalog has yet been agreed in this example.
- Christoph and Ehsan: map these input fields and fixture references to the real
  Ambiguous task, missing-essential question, and result locations.

This fixture supports implementation and offline checks. Live acceptance still
requires Hermes to receive the real task, obtain a real remote supplier response,
and post the explained result to the originating buyer workspace.
