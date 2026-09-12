# Implementation coordination

The buyer implementation agent working with Christoph is reachable at
**christoph-6932@agentmail.to**. The agent building the supplier side should email
this address to establish direct coordination. Include `Takeoff supplier handoff`
in the subject and link the relevant GitHub issue or commit. GitHub Issues remain
the shared record for agreed interfaces and decisions.

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
- The live bridge handles contractor DMs. Assigned-task intake, the remote
  supplier connection, negotiation, and final buying-plan integration remain to
  be implemented. The three procurement skills are initial behavior drafts;
  they have not passed an end-to-end supplier run.
- The accepted starting flow is a concrete request, with questions only for
  missing essentials. A priority interview is not a prerequisite for discovery.
- Product discovery and selection come before negotiation: material sheet →
  requirements → purchasable SKUs and compatible alternatives → availability.
- Buyer and vendor models choose strategy, including numeric counteroffers,
  bundles, concessions, and disclosures. Code validates constraints/arithmetic;
  it does not schedule their moves. Include one meaningful substitution decision.
- Target a working demo by **16:00 America/Los_Angeles on September 12**; reserve
  the remaining half hour for fixes/capture before the **16:30 submission**.

## First supplier handoff

Tapan owns the supplier implementation and internal design in
[#2](https://github.com/pool1892/takeoff/issues/2). Please send:

1. Your coding agent's reply address and current branch/commit.
2. The first reachable supplier channel and its public URL/email/workspace
   reference, plus the intended request/reply format.
3. One buyer-visible product and sample inquiry/confirmed offer: quantity and
   unit, required specifications, stock, delivery, fees/tax, minimums, expiry,
   and conditions. Keep unknown values explicit.
4. How the two agents should correlate inquiries and revised offers, and the
   basic reset procedure for a repeatable demonstration.

Start with one requirement and one remote supplier so both sides can connect
early, then expand to the core website, email, and agent-to-agent channels.
The supplier agent retains its separate Ambiguous workspace and private state.
The documented Ambiguous API has no verified general cross-workspace agent-chat
transport yet; agree and test the exact channel rather than assuming one exists.

## Scenario alignment still required

Christoph's current full-demo target is 25 representative house components, with
realistic ambiguity in the contractor's list that the buyer maps to available
supply. Ignore the UX fixture when choosing this procurement scenario. The
[house request proposal](../examples/procurement/house-discovery.md) supplies a
natural source message and mapping cases; its exact quantities/specifications are
still proposed synthetic data. Christoph delegated the exact component choices
and first live slice to the implementation agents together. Agree public catalog
coverage and the actual substitution tradeoff with Tapan through
[#1](https://github.com/pool1892/takeoff/issues/1), without using the UX fixture as
the scenario authority.

The earlier painting JSON files remain useful arithmetic fixtures. The separate
`src/demoScenario.js` framing-lumber fixture is a UX simulation. Neither is the
current 25-component scenario or evidence of real negotiations. Supplier and
buyer work can proceed in parallel from the natural source and shared product/
offer fields; don't preassign SKUs or a winning supplier to the contractor input.

Ehsan owns the actual Ambiguous task, progress, contractor-decision, and result
presentation. Keep the corresponding references and input/output examples small
and explicit so buyer, supplier, and UX work can proceed in parallel.
