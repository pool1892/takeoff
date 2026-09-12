# Takeoff supplier service

This implements supplier epic [#2](https://github.com/pool1892/takeoff/issues/2): a simulated supplier market reached through a website, Ambiguous email, and supplier agents. Hermes remains the buyer on the other computer. Ambiguous remains the workspace interface. The supplier service owns commercial validation and its private ledger.

The four personalities are general packages, overstock negotiation, local delivery coordination, and a market-aware trader. The first three support the core package without phone or trading. The fixture is proposed representative data, not a construction-ready house specification. Replace it with the team’s chosen scenario before scoring.

## Start the local market

Python 3.11 or newer:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[test]'
.venv/bin/python -m takeoff_suppliers.cli init
.venv/bin/python -m takeoff_suppliers.cli run --policy collaboration
.venv/bin/python -m takeoff_suppliers.cli serve --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000/`. The website and HTTP API work without an OpenAI key. After installation, `takeoff-suppliers` is equivalent to `python -m takeoff_suppliers.cli`. Use `--home DIRECTORY` before the command to select a different ignored local configuration directory.

`init` creates `.local/suppliers/config.json` and `.local/suppliers/secrets.json` with mode 600. It preserves existing settings and keys, creates distinct buyer and operator tokens when missing, and never prints them. Keep the entire local directory out of Git. Relative configured paths resolve from the working directory.

The supplier machine must serve a public HTTPS tunnel or another mutually reachable endpoint for the buyer machine. Share that URL and the buyer-scoped token through the team’s agreed private channel. Tunnel creation and the cross-computer connection require verification on the actual machines; local tests do not establish either.

## Configure the real channels

Workspace setup is separate from the fixture. Configure the current supplier workspace; the buyer workspace remains intentionally deferred until the team supplies its new reference. Never reuse an unrelated old buyer workspace.

The nonsecret configuration has this shape:

```json
{
  "database_path": ".local/suppliers/market.sqlite",
  "transport_path": ".local/suppliers/transport.sqlite",
  "scenario_path": null,
  "buyer_id": "demo-buyer",
  "buyer_workspace_id": null,
  "supplier_workspace_id": "CURRENT_SUPPLIER_WORKSPACE_ID",
  "supplier_workspace_slug": "CURRENT_SUPPLIER_WORKSPACE_SLUG",
  "runtime_backend": "codex",
  "model": "gpt-6-astra",
  "exa_mcp_url": null,
  "vendors": {
    "general": {
      "user_id": "GENERAL_VENDOR_USER_ID",
      "token_env": "AMBIGUOUS_GENERAL_API_KEY",
      "email": "GENERAL_VENDOR_EMAIL",
      "chat_threads": [],
      "buyers": {},
      "chat_buyers": {}
    }
  }
}
```

The generated file includes all four vendor entries. Each uses its own identity and token variable: `AMBIGUOUS_GENERAL_API_KEY`, `AMBIGUOUS_OVERSTOCK_API_KEY`, `AMBIGUOUS_LOCAL_API_KEY`, and `AMBIGUOUS_TRADER_API_KEY`. `AMBIGUOUS_SUPPLIER_API_KEY` is the setup-owner credential used by diagnostics; vendor runtimes do not inherit it. Store values in environment variables or the ignored secrets mapping; environment variables take precedence.

The default supplier runtime uses the installed Codex CLI and its existing account login. Check `codex login status`; no new OpenAI API key is needed for this local runtime. Set `runtime_backend` to `agents_api` to select the optional hosted backend, which requires `OPENAI_API_KEY`. The optional speech adapter also uses that key separately.

Codex uses isolated supplier threads and host-controlled catalog, inquiry, and offer tools. The host connects those agents to Ambiguous mail and records. Personal Codex tools and filesystem execution are disabled for supplier turns. The hosted backend additionally supports read-only Ambiguous MCP and optional Exa MCP through `exa_mcp_url`; keep credential-bearing URLs in ignored configuration. Exa research in the Codex backend and trading execution remain extensions.

For each participating vendor, configure `buyers` as `{"actual-buyer-email": "demo-buyer"}`. Chat uses `chat_threads` pairs of `[channel_id, root_message_id]` and `chat_buyers` mapping sender user IDs to the logical buyer ID. Polling is limited to those configured senders and threads. Email is the proposed cross-workspace agent transport; chat is supported within configured workspace conversations. Confirm the actual handoff with Christoph before claiming cross-computer integration.

```sh
.venv/bin/python -m takeoff_suppliers.cli doctor
.venv/bin/python -m takeoff_suppliers.cli doctor --vendor general
.venv/bin/python -m takeoff_suppliers.cli worker RUN_ID general
```

`doctor` reads identity and reports runtime configuration. It can verify the supplier while reporting the buyer as pending. The worker refuses to start until distinct buyer/supplier workspace IDs, a vendor identity, usable runtime authentication, and authorized sender mappings exist. Start one worker process per vendor; do not run two processes for the same vendor and transport database. `--once` processes one polling pass. A running worker sends real Ambiguous messages to configured demo participants.

For an operator-triggered agent turn without outgoing email:

```sh
.venv/bin/python -m takeoff_suppliers.cli agent RUN_ID general 'What packages and delivery choices can you offer?' --request-id operator-example-1
```

This verifies the supplier identity and may issue simulated commercial records through OpenAI. Reuse the printed request ID after a timeout. It is not a substitute for the remote buyer test.

Publish the run’s public catalogs, issued quotes, and simulated commitments into the supplier workspace:

```sh
.venv/bin/python -m takeoff_suppliers.cli sync-records RUN_ID
```

This command creates real Ambiguous documents and simulated fulfillment tasks using each vendor’s identity. It retains remote IDs locally so rerunning does not duplicate confirmed records. Catalogs are labeled publication-time snapshots; current stock and quote validity come from the commercial engine. Private costs, negotiation floors, and raw model traces stay on the supplier computer. Do not run record synchronization concurrently against the same transport database.

## Buyer handoff and message examples

The supplier website exposes product discovery and quote inspection. HTTP clients authenticate with the buyer token:

- `GET /v1/runs/RUN_ID/vendors`
- `GET /v1/runs/RUN_ID/vendors/general/catalog?query=plywood`
- `POST /v1/runs/RUN_ID/vendors/general/inquiries`
- `POST /v1/runs/RUN_ID/vendors/general/offers`
- `GET /v1/runs/RUN_ID/offers/QUOTE_ID`
- `POST /v1/runs/RUN_ID/offers/QUOTE_ID/accept`

Use `/docs` for the current HTTP schema. Quotes carry complete canonical terms: units, pack constraints, fees, discounts, delivery, conditions, expiry, source references, and total. Buyer-facing data excludes private costs and negotiation floors. Counters reference `previous_quote_id`; issued revisions stay distinguishable from proposals and commitments.

Ordinary email may contain free text. For structured agent-to-agent exchanges, send a JSON object as the email’s plain-text body:

```json
{
  "schema_version": "takeoff.supplier.v1",
  "type": "inquiry",
  "run_id": "RUN_ID",
  "vendor_id": "overstock",
  "message": "Please find a package for these requirements and explain delivery options."
}
```

`counter` uses the same envelope with proposed terms and the prior quote reference in the body. The supplier agent interprets it and asks the commercial engine to issue validated terms. The authenticated channel sender determines the buyer identity; a model cannot supply another buyer or vendor scope.

Explicit substitution approval is separate:

```json
{
  "schema_version": "takeoff.supplier.v1",
  "type": "approval",
  "run_id": "RUN_ID",
  "vendor_id": "local",
  "requirement_id": "REQUIREMENT_ID",
  "product_id": "SUBSTITUTE_PRODUCT_ID"
}
```

The reply contains a recorded approval ID with the incoming source message as evidence. Accept a specific quote using its ID and those approval references:

```json
{
  "schema_version": "takeoff.supplier.v1",
  "type": "acceptance",
  "run_id": "RUN_ID",
  "vendor_id": "local",
  "quote_id": "QUOTE_ID",
  "approval_refs": ["RECORDED_APPROVAL_ID"]
}
```

Free-text “yes” does not create a commitment. Acceptance rechecks stock and recorded approvals, reserves simulated inventory, and creates a simulated fulfillment task in the supplier Ambiguous workspace. The response links the accepted terms to the task ID. No real order or dispatch occurs.

## Reset, evidence, and recovery

```sh
.venv/bin/python -m takeoff_suppliers.cli pause RUN_ID general
.venv/bin/python -m takeoff_suppliers.cli pause RUN_ID general --resume
.venv/bin/python -m takeoff_suppliers.cli reset RUN_ID
.venv/bin/python -m takeoff_suppliers.cli export RUN_ID --output .local/suppliers/public-run.json
.venv/bin/python -m takeoff_suppliers.cli export RUN_ID --private --output .local/suppliers/private-run.json
.venv/bin/python -m takeoff_suppliers.cli score RUN_ID QUOTE_ID_1 QUOTE_ID_2
```

Reset creates a **new run ID** from the same initial scenario and retains old evidence. Agents use fresh sessions for the new run. Restart workers against that new ID and ensure buyer requests reference it. Use matching scenario data and starting opportunities for human/agent or baseline/collaboration comparisons. Freeze external research inputs if research affects scored trials.

Public exports contain commercial evidence. `--private` additionally includes private economics, local messages, OpenAI session/tool traces, and Ambiguous task mirrors: keep it on the supplier computer. Score validity before cost; human active time, elapsed time, and all attempts belong in the team evaluator. Do not label opening-offer optimization as human performance or claim universal savings.

Confirmed email sends use Ambiguous idempotency keys. Saved function outcomes are resubmitted after disconnects without repeating confirmed commercial actions. Chat/task creation has no assumed send-idempotency guarantee: uncertain outcomes halt for operator reconciliation. Do not delete a pending state entry or create a new request ID blindly; inspect the saved record and remote thread/task first. Timeouts retain the session for resumption. Paused workers leave incoming requests queued.

## Optional phone and verification status

`serve --voice` enables the bounded OpenAI speech adapter and requires `OPENAI_API_KEY`; see [phone setup and protocol](voice.md). Phone is not required to complete the core package. It must pass a live remote exchange before joining the recorded demonstration.

Focused tests cover commercial arithmetic and constraints, browser discovery and acceptance, identity checks, message deduplication, durable function recovery, explicit approval, task mirroring, and CLI configuration. Run:

```sh
.venv/bin/python -m pytest
```

MockTransport tests exercise documented API contracts, not a live OpenAI or Ambiguous exchange. A real supplier identity check, a live agent turn, a live email round trip, a cross-computer trial, and recorded replay are separate milestones. Report which actually occurred. The three intended demo themes are negotiation quality, observed benefit to both sides, and rapid completion into inspectable records; outcomes must come from the recorded run.

On September 12, 2026, the local setup verified four distinct supplier identities and published their catalog documents and Sheets in the configured supplier workspace. A live Codex 0.154.0 turn using the existing ChatGPT account called the catalog and offer tools, producing a simulated $358.38 delivered quote for 10 sheathing sheets and 10 drywall sheets. The first unsuccessful tool-host attempt was retained alongside the successful retry. The running website returned its authenticated catalog and rejected unauthenticated access. Buyer-workspace setup, live email exchange, cross-computer operation, human comparison, and live audio remain unverified.
