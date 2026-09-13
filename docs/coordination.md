# Implementation coordination

The coding-agent email addresses have been removed from this source archive.
Configure private coordination channels for any new run. Their historical coordination thread was
active. GitHub Issues remain the shared record for agreed interfaces and decisions.
Christoph authorized all coordination emails. The earlier handoff from a supplier
demo mailbox was corrected; use the coding address for implementation coordination.

This AgentMail inbox is for the coding agents. It is not Chip's mailbox and does
not replace the product's Ambiguous supplier communication. Do not send supplier
private economics, API keys, or credentials through a public issue or shared
buyer fixture; provide public endpoint/address references and shareable examples.

## Current buyer side

- Chip is Christoph's personal agent in the `takeoffAI` Ambiguous workspace.
  Its direct chat works through isolated Hermes. Procurement and chat currently use
  **Sol, medium reasoning, and Fast requested via OpenAI's priority tier**. Earlier
  Luna turns remain recorded; explicit invocation arguments apply to resumed sessions.
- Hermes and its tools have only the repository mounted, with non-root execution,
  read-only source, writable local state, and restricted HTTPS egress. Supplier
  destinations need explicit configuration when their endpoints are known.
- The bridge handles contractor DMs and explicitly configured assigned tasks.
  Buyer tools now implement discovery checks, quote normalization, model-proposed
  action validation, scoped contractor decisions, and package evaluation. Focused
  tests pass. The first live three-line task completed at 14:35 PDT with a
  validated $2,300 delivered supplier quote and the recommendation published in
  Ambiguous. The full 25-component recommendation completed at **15:20 PDT**:
  Neighborhood Delivery Supply confirmed the buyer's $8,200 delivered counteroffer,
  $231.73 below its own opening quote, covering 25/25 requirements. The recommendation
  is published in Ambiguous and the task completion is recorded. No order was placed.
  See [the full-house run](runs/2026-09-12-full-house.md) for terms, recovery history,
  the remaining substitution gap, and capture guidance.
- The accepted starting flow is a concrete request, with questions only for
  missing essentials. A priority interview is not a prerequisite for discovery.
- Product discovery and selection come before negotiation: material sheet →
  requirements → purchasable SKUs and compatible alternatives → availability.
- Buyer and vendor models choose strategy, including numeric counteroffers,
  bundles, concessions, and disclosures. Code validates constraints/arithmetic;
  it does not schedule their moves. Include one meaningful substitution decision.
- Target a working demo by **16:00 America/Los_Angeles on September 12**; reserve
  the remaining half hour for fixes/capture before the **16:30 submission**.

## Active supplier handoff

Tapan owns [#2](https://github.com/pool1892/takeoff/issues/2), implemented on
`codex/supplier-epic` in PR #30. Its public read-only discovery is available at
`https://supplier.example.invalid/public/manifest` and
`/public/vendors/{general,overstock,local}/catalog`; scripted requests include
`ngrok-skip-browser-warning: takeoff`. Access from inside the isolated buyer
container has passed. The public host is explicitly allowed by the egress proxy.

Chip sends procurement mail from `buyer@example.invalid` to
`overstock@example.invalid` for the first path. The supplier confirmed
the buyer identity mapping and its sender-scoped worker produced the first live quote. Structured
messages use `takeoff.supplier.v1`, a fresh supplier run ID, vendor ID and message;
replies preserve inquiry correlation and contain canonical quote JSON. The first
three-line run is `run_redacted_14`; a new independent trial
requires a fresh supplier run. These are simulated businesses communicating over
real services. `tax_treatment=all_fixture_taxes_included` explicitly means zero
additional tax for this synthetic scenario, not a real tax rule.

All 25 requirements were discovered against 67 catalog products, with actual
Ambiguous email exchanges to three remote supplier workers. Website discovery and
supplier mail are verified; this does not establish a separate direct agent-chat channel.
The supplier agent retains its separate Ambiguous workspace and private state.
The documented Ambiguous API has no verified general cross-workspace agent-chat
transport yet; agree and test the exact channel rather than assuming one exists.

## Adopted scenario

Christoph's current full-demo target is 25 representative house components, with
realistic ambiguity in the contractor's list that the buyer maps to available
supply. Ignore the UX fixture when choosing this procurement scenario. The
[house request proposal](../examples/procurement/house-discovery.md) supplies a
natural source message and mapping cases. Both implementation agents adopted its
25 synthetic lines. The first live slice is lines 1–3: full-length SPF studs,
longer framing stock, and rated OSB sheathing. The supplier's public catalogs now
cover the larger request. A plywood-to-OSB subfloor alternative is a proposed
changed requirement; technical equivalence and contractor approval are not assumed.
The contractor has confirmed unfaced insulation and DemoPEX expansion fittings.
The OSB alternative now has a $716 standalone delivered quote; a complete revised
package, installation/warranty differences, and contractor approval remain open.

The earlier painting JSON files remain useful arithmetic fixtures. The separate
`src/demoScenario.js` framing-lumber fixture is a UX simulation. Neither is the
current 25-component scenario or evidence of real negotiations. Supplier and
buyer work can proceed in parallel from the natural source and shared product/
offer fields; don't preassign SKUs or a winning supplier to the contractor input.

Ehsan owns the actual Ambiguous task, progress, contractor-decision, and result
presentation. Keep the corresponding references and input/output examples small
and explicit so buyer, supplier, and UX work can proceed in parallel.

Fable in OMP owns the separate optional voice adapter under `integrations/voice/`.
See [its handoff](voice-handoff.md). It stays inside the buyer container. Christoph
now wants a human teammate playing the seller through browser WebRTC for the
voice demo. The `voice-web` launcher publishes a localhost-only session server;
use an SSH tunnel over Tailscale from the Mac. The separate AI supplier adapter
still uses the public supplier audio protocol. Keep the verified GPT-Live speech
and Luna/xhigh decision configuration frozen for capture. The verified human call
contained no price offer or confirmed quote. Voice cannot block the core path.
