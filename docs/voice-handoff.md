# Fable voice workstream

Christoph delegates optional supplier voice calls to the Fable agent in OMP. This
is independent of the core website, email, and agent-to-agent procurement flow.
Read `AGENTS.md`, the workflow/demo skills, issue #11, and the relevant transcripts.
Current decisions win over older plans. Demo target: today at 16:00 Pacific;
submission: 16:30. Do not delay core integration for phone.

Own new buyer-side files under `integrations/voice/` and this document. Coordinate
before editing any other path. The main Codex agent owns `buyer/`, Hermes isolation,
Ambiguous task/mail transport, and common runtime configuration. Other coding
agents are actively editing those files. No resets, cleanup, or unilateral merges.

The supplier implementation lives on branch `origin/codex/supplier-epic` (PR #30).
Read its public `docs/suppliers/voice.md` and runbook first. Coordinate with its
owner rather than duplicate or change the supplier adapter. Do not read private
supplier economics into buyer context.

Build a small callable adapter: receive run/request references, supplier contact,
the buyer model's call objective and authorized requirements/disclosures; return
call status, timestamps, transcript/evidence references, and extracted proposed
offer facts with unknowns explicit. Chip remains the contractor's agent and chooses
the negotiation strategy. A transcript alone is not a confirmed quote; preserve
supplier confirmation, price/units, fees/taxes, stock, delivery, expiry and source.
No order or substitution approval can be inferred from the call. No real calls to
unagreed contacts; use the agreed remote synthetic supplier endpoint for testing.

Report concrete endpoint/credential-variable needs to the main implementer. Keep
secrets and recordings in ignored `.local/` state. Do not weaken Hermes isolation
or mount host credentials. Label local/mock, actual cross-computer audio, and
recorded replay distinctly. Deliver the smallest verified slice first.

The user starts Fable in OMP in Herdr. The main implementer can read and prompt
that thread through its observed pane ID after the user's initial prompt is
submitted. Send short progress and interface messages through that same channel;
main can read results. Supplier coding coordination is with
`tapan-agent@agentmail.to`; main currently handles that mailbox conversation to
avoid conflicting instructions. All coordination emails are user-authorized.

## Status (September 12, ~16:20 Pacific)

Christoph chose GPT-Live (`gpt-live-1`, full duplex) for the buyer's voice and a
live human teammate playing the seller for the demo. Implementation and interface:
[`integrations/voice/README.md`](../integrations/voice/README.md). Delegated
decisions run on `gpt-5.6-luna` at `reasoning.effort=max`; speech stays on
`gpt-live-1`. Launch: `scripts/hermes voice-web --request /opt/data/voice/human-request.json`
(main's launcher publishes `127.0.0.1:3000`; the seller reaches it over an SSH
local forward from the Mac and opens the printed `/s/<token>/` page).

Verified: a real `gpt-live-1` session starts from inside the isolated container
through the egress proxy with the Responses-delegation config; helper arithmetic,
authorization checks, and quote mapping pass local checks; the seller page serves.
Not yet verified: a complete WebRTC conversation with a human, the in-container
audio mock smoke, and any live call to the supplier computer (it has no speech
key yet). Nothing here is a live milestone until those runs exist as evidence.
