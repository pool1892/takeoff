# Buyer voice calls (issue #11, stretch)

Buyer-side voice for Takeoff. Two ways to reach a supplier by voice, one result
shape. Everything runs inside the isolated Hermes container; evidence lands under
`TAKEOFF_VOICE_HOME` (default `/opt/data/voice` in the container, `.local/voice`
elsewhere). Keys are read from the runtime environment and never printed.

| Path | Module | Other side | Speech |
|---|---|---|---|
| Human seller (demo) | `integrations.voice.human_call` | a teammate in a browser (WebRTC) | `gpt-live-1` full duplex |
| AI supplier (Tapan, PR #30) | `integrations.voice.live` | supplier WebSocket call, whole-WAV turns | `gpt-live-1` bridged to turns |
| Cascaded fallback | `integrations.voice.call` | same supplier WebSocket | TTS out / STT in, model-chosen text |

Delegated decisions default to `gpt-5.6-luna` with `reasoning.effort=xhigh` (the
configuration that carried the verified live human call; the call needs little
reasoning) —
the Live delegation accepts `none…xhigh` and rejects `max` with HTTP 400
(`TAKEOFF_VOICE_MODEL`, `TAKEOFF_VOICE_REASONING`, `TAKEOFF_VOICE_SERVICE_TIER`
override). Code owns the hard gates in every path: authorization checks on
proposals, exact-readback or spoken confirmation, exchange/time budgets, end of
call. Speech is model-chosen. A confirmed readback is a quote, never an order or
a substitution approval.

## Environment

- `OPENAI_API_KEY` — buyer key (Live session, delegated model, TTS/STT).
- `TAKEOFF_BUYER_TOKEN` — supplier-issued buyer token (AI-supplier paths only).
- `TAKEOFF_SUPPLIER_HOST` — your bare supplier hostname; the default
  `supplier.example.invalid` is an inert placeholder. Review and add the hostname
  to `runtime/hermes/egress.py` before a container-based supplier call.
- `TAKEOFF_VOICE_HOME`, `TAKEOFF_VOICE_WEB_PORT` (3000), `TAKEOFF_VOICE_WEB_TOKEN` (share-URL token).
- Egress: `api.openai.com` (HTTPS + WSS) and the supplier host through the container proxy.

## Call request (all paths)

```json
{
  "run_id": "run_…", "vendor_id": "overstock",
  "objective": "Get a complete, confirmed delivered quote for …",
  "requirements": [{"requirement_id": "R7", "description": "…", "quantity": 40, "unit": "sheet", "must": ["…"]}],
  "known_alternatives": [{"product": "7/16 OSB", "status": "substitution requires contractor approval"}],
  "allowed_actions": {"counteroffer": true, "max_total": "1600.00", "delivery_deadline": "2026-09-17", "bundle_ask": false},
  "disclosures": ["…what the buyer may reveal…"],
  "constraints": {"max_exchanges": 5, "max_seconds": 105}
}
```

`example-request.json` is a **mock-only fixture** (synthetic IDs, synthetic
plywood line matching `mock_supplier.py`, no competing-offer claim). The live
human demo uses a separate ignored request prepared from the actual contractor
source (`/opt/data/voice/human-request.json`), with disclosures limited to
documented facts and `max_total: null` unless the contractor set a budget.
Human calls accept `max_seconds` up to 900.

## Result (all paths)

`status`: `confirmed` | `unconfirmed` | `failed` | `no_connect`, plus
`outcome_reason`, timestamps, `transcript`, `candidates`, `confirmed_quote`
(supplier public quote, or for human calls a quote built from spoken terms with
`source: "human_vendor_spoken"` and explicit nulls), `proposed_offer`,
`tool_calls`, `authorization_flags`, `labels` (transport, what was live, what was
simulated), and `evidence.path` (`call.json` next to the WAVs). Feed
`confirmed_quote` to `buyer.quotes.normalize_quote(quote, evidence={"id": call_id,
"run_id", "vendor_id", "request_id"})`; unknown facts stay unresolved there.

## Human seller path

```sh
python -m integrations.voice.human_call --request integrations/voice/example-request.json --public-url https://HOST
```

Prints `Seller page: https://HOST/s/<token>/`. The seller opens it, clicks
*Answer the call*, and talks; audio flows browser↔OpenAI over WebRTC. The server
creates the Live session from the request file (re-read per call, so Hermes can
rewrite it), attaches a sideband to record both transcripts, runs the backend
tools (`check_proposal`, `record_quote`, `confirm_readback`, `end_call`), and
writes `call.json`. `GET …/api/calls` lists results. The browser must reach port
3000: inside the container the launcher publishes `127.0.0.1:3000`; put an HTTPS
front (tailscale serve/funnel, SSH forward) in front of it for a remote seller.

## AI supplier paths

```sh
python -m integrations.voice.live integrations/voice/example-request.json   # GPT-Live bridge
python -m integrations.voice.call integrations/voice/example-request.json   # cascaded fallback
python -m integrations.voice.smoke --tts                                    # local mock supplier, real audio both ways
```

`mock_supplier.py` is a scripted, key-free stand-in for the supplier endpoint
(protocol from `docs/suppliers/voice.md`); it cannot hear the buyer and its quote
is synthetic. Label mock runs as such. The supplier needs `serve --voice` with its
own speech key before a live cross-computer call is possible.

## Evidence labels

Distinguish: local mock; live buyer session with a human seller (simulated
business, real conversation); live cross-computer AI supplier call; recorded
replay. `labels` in each result state which applies.
