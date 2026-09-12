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

`examples/procurement/` contains proposed synthetic painting-supplies inputs and
linked offer/decision examples for buyer integration. The separate
`src/demoScenario.js` fixture on main presents a simulated framing-lumber UX
walkthrough. These are development examples, not one agreed scenario or evidence
of real negotiations. Choose the common material and delivery tradeoff with Tapan
and Ehsan through [#1](https://github.com/pool1892/takeoff/issues/1) before the first
integrated run. The owners can continue independent implementation meanwhile.

Ehsan owns the actual Ambiguous task, progress, contractor-decision, and result
presentation. Keep the corresponding references and input/output examples small
and explicit so buyer, supplier, and UX work can proceed in parallel.
