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

## Status (September 12, following the 2:46 pm Pacific call)

Christoph chose GPT-Live (`gpt-live-1`, full duplex) for the buyer's voice and a
live human teammate playing the seller for the demo. Implementation and interface:
[`integrations/voice/README.md`](../integrations/voice/README.md). Speech stays on
`gpt-live-1`. Delegated decisions: **defaults `gpt-5.6-luna` at
`reasoning.effort=xhigh`** — Christoph's call for the live demo: use what worked
(a Sol/medium switch was tried after the API tier upgrade and reverted; set in
`integrations/voice/call.py`, overridable with `TAKEOFF_VOICE_MODEL` /
`TAKEOFF_VOICE_REASONING`). The Live delegation rejects `max` (HTTP 400); `xhigh`
is the accepted cap. Launch: `scripts/hermes voice-web --request /opt/data/voice/human-request.json`
(main's launcher publishes `127.0.0.1:3000`; the seller reaches it over an SSH
local forward from the Mac and opens the printed `/s/<token>/` page). A running
server keeps the defaults it started with; main restarts it only when no call is
active.

Verified (evidence under `/opt/data/voice/calls/`, i.e. `.local/hermes/voice/calls/`):

- `c0b4bad0fe49` — **live human call** from the hackathon Mac to the buyer agent
  in the isolated container (session `live_u7_ENPqYgriGjqchDSmqEbW8`, 67 s,
  2026-09-12 21:46:46Z), run with the then-configured `gpt-5.6-luna` / `xhigh`
  backend. Full-duplex conversation with interruptions; both transcripts recorded
  by the buyer sideband. Status `unconfirmed`: the seller quoted no prices, so no
  `record_quote`/`confirm_readback` fired and there is no confirmed quote.
  Connection milestone only, not a completed quote.
- `a7d59524ec0f` — headless SDP → session → sideband → close handshake through
  the published port (`live_usage {"seconds": 15}`).
- `f047de3b8d62` — in-container mock smoke of the AI-supplier bridge with real
  audio both ways (scripted mock supplier, labeled mock); buyer spoke and heard
  the readback; confirmation was blocked because STT rendered the total in words —
  fixed by spoken-number normalization in `call.py` (not re-run; no further paid
  mocks unless a new bug appears).

Not verified: a human call that reaches a confirmed quote (none as of 22:13Z; the
live demo runs the same luna/xhigh configuration as that call), and any live
call to the supplier computer (it has no speech key yet). Seller script for the
quote-producing take: [`voice-demo-cue.md`](voice-demo-cue.md).
