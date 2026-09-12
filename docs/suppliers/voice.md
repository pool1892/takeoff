# Optional live supplier voice

The supplier exposes a turn-based, bidirectional WebSocket call at
`/v1/runs/{run_id}/vendors/{vendor_id}/call`. This is VoIP over a WebSocket,
not a PSTN telephone number. The caller opens and closes the connection. Use
the same supplier host and HTTPS tunnel as the core service, changing `https`
to `wss`. The core package is available without voice.

The host attaches the adapter with `attach_voice(app, market, runtime,
buyer_token, buyer_id, openai_api_key)`. OpenAI transcription and speech use
`gpt-4o-mini-transcribe` and `gpt-4o-mini-tts`; vendor reasoning and commercial
validation reuse the existing runtime. No purchase/acceptance tools are called
by the voice adapter. It announces that its speech is AI generated.

## Wire handoff

1. Connect and send `{"token":"<local buyer token>"}` as the first JSON frame.
   Never put credentials in the URL. The server verifies buyer ownership of
   the trial before accepting audio. It replies with `ready`, a call ID, and limits.
2. Send each complete PCM WAV as a binary frame, or send JSON
   `{"type":"audio","wav_base64":"..."}`. Use 8–48 kHz, mono or stereo,
   at most 30 seconds and 2 MB per turn.
3. Receive a `transcript` event, then `supplier_turn` containing canonical text,
   WAV audio encoded as base64, and `candidates`. Each candidate contains the
   entire public `quote` and its `readback_digest`. The voice reads back the
   full quoted terms. Correct uncertain quantities, units, dates, or numbers
   through another spoken turn before confirming.
4. Confirm the exact supplier readback by sending
   `{"type":"confirm_quote","quote":{...},"readback_digest":"..."}`.
   Copy the entire candidate. The server rechecks the current quote; mismatched
   terms or revisions remain unconfirmed. The final `confirmed_quote` event
   includes the call ID and quote, with `order_placed: false`.
5. Otherwise send `{"type":"end"}`. Disconnects, errors, timeouts, and missing
   readback confirmation leave the call unconfirmed. An existing issued offer
   in the commercial ledger is not proof that the caller heard or confirmed it.

There are at most eight audio exchanges and a total two-minute deadline,
including transcription, reasoning, synthesis, and waiting for caller input.
After exchange eight the caller may confirm the last quote or end. A shorter
remaining trial window can be set with `max_seconds` when attaching the adapter.
No answer, readback confirmation, or call completion constitutes approval of a
substitution, order placement, or relaxed contractor constraint.

## Small caller

Set `TAKEOFF_BUYER_TOKEN` locally, then run:

```sh
python -m takeoff_suppliers.voice \
  wss://SUPPLIER-HOST/v1/runs/RUN-ID/vendors/local/call \
  /private/path/request.wav /private/path/clarification.wav
```

This small client sends caller-provided WAV turns, displays each response, saves
supplier WAV responses under ignored `.local/suppliers/call-audio`, and asks for
manual readback confirmation. It does not record a microphone or play audio;
use an existing recorder/player or call the protocol from Hermes's audio tools.
Prerecorded WAV inputs are fixtures; labeling them as a spontaneous live human
conversation would be inaccurate. A successful live cross-computer exchange
with generated or recorded audio must still be described accurately.

Christoph's buyer adapter should publish the call ID, useful exchange, and
confirmed quote through its normal Ambiguous comparison path. The voice server
does not write directly into the buyer workspace. Keep the transcript separate
from approvals and preserve failed attempts. Fresh trial IDs reset runtime
conversation state; previous call evidence remains available.

## Evidence and verification

`voice.sqlite3` beside the supplier market database retains outcome, public
terms, timestamps, and text exchanges. It excludes audio, authentication frames,
private commercial configuration, and provider error bodies. Keep this local
database ignored. Tests use HTTP mocks and an in-process WebSocket client;
they verify protocol behavior, not live credentials or cross-computer access.

Include this stretch in the demo only after the actual buyer and supplier
computers complete a useful negotiation and confirmed terms appear in the
buyer's Ambiguous comparison. If used for scored trials, both human and agent
arms need equivalent access to the opportunity; otherwise exclude it from both.

References: [OpenAI speech transcription](https://developers.openai.com/api/docs/guides/speech-to-text),
[speech generation](https://developers.openai.com/api/docs/guides/text-to-speech),
and [Takeoff phone issue #11](https://github.com/pool1892/takeoff/issues/11).
