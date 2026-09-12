# Implementation coordination

The buyer implementation agent is **christoph-6932@agentmail.to**; Tapan's supplier
implementation agent is **tapan-agent@agentmail.to**. Their coordination thread is
active. GitHub Issues remain the shared record for agreed interfaces and decisions.
Christoph authorized all coordination emails. The earlier handoff from a supplier
demo mailbox was corrected; use the coding address for implementation coordination.

This AgentMail inbox is for the coding agents. It is not Chip's mailbox and does
not replace the product's Ambiguous supplier communication. Do not send supplier
private economics, API keys, or credentials through a public issue or shared
buyer fixture; provide public endpoint/address references and shareable examples.

## Current buyer side

- Chip is Christoph's personal agent in the `takeoffAI` Ambiguous workspace.
  Its direct chat works through isolated Hermes with Sol, high reasoning, and
  Fast requested via OpenAI's priority tier.
- Hermes and its tools have only the repository mounted, with non-root execution,
  read-only source, writable local state, and restricted HTTPS egress. Supplier
  destinations need explicit configuration when their endpoints are known.
- The bridge handles contractor DMs and explicitly configured assigned tasks.
  Buyer tools now implement discovery checks, quote normalization, model-proposed
  action validation, scoped contractor decisions, and package evaluation. Focused
  tests pass; the first live task/supplier/result run is being exercised. This is
  not yet a completed full 25-component procurement demonstration.
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
`https://multiply-cameo-clash.ngrok-free.dev/public/manifest` and
`/public/vendors/{general,overstock,local}/catalog`; scripted requests include
`ngrok-skip-browser-warning: takeoff`. Access from inside the isolated buyer
container has passed. The public host is explicitly allowed by the egress proxy.

Chip sends procurement mail from `takeoff-hermes@takeoffai.ambi.cc` to
`takeoff-overstock@spike-team.ambi.cc` for the first path. The supplier confirmed
the buyer identity mapping and is starting its sender-scoped worker. Structured
messages use `takeoff.supplier.v1`, a fresh supplier run ID, vendor ID and message;
replies preserve inquiry correlation and contain canonical quote JSON. The first
three-line run is `run_402632f04bb94032b83ffa8ecd69f96f`; a new independent trial
requires a fresh supplier run. These are simulated businesses communicating over
real services. `tax_treatment=all_fixture_taxes_included` explicitly means zero
additional tax for this synthetic scenario, not a real tax rule.

Start with one requirement and one remote supplier so both sides can connect
early, then expand to the core website, email, and agent-to-agent channels.
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
Insulation facing and PEX fitting identity remain unresolved contractor facts.

The earlier painting JSON files remain useful arithmetic fixtures. The separate
`src/demoScenario.js` framing-lumber fixture is a UX simulation. Neither is the
current 25-component scenario or evidence of real negotiations. Supplier and
buyer work can proceed in parallel from the natural source and shared product/
offer fields; don't preassign SKUs or a winning supplier to the contractor input.

Ehsan owns the actual Ambiguous task, progress, contractor-decision, and result
presentation. Keep the corresponding references and input/output examples small
and explicit so buyer, supplier, and UX work can proceed in parallel.

Fable in OMP owns the separate optional voice adapter under `integrations/voice/`.
See [its handoff](voice-handoff.md). It uses the existing remote supplier audio
protocol and stays inside the buyer container. Mock voice work proceeds while
the endpoint and scoped supplier token are coordinated; voice cannot block core.
