# Running the Hermes procurement buyer

The managed [Hermes bridge](hermes.md) now includes an assigned-task listener in
`integrations/ambiguous/procurement.py`. Hermes chooses products, questions,
numeric counters, bundles, and when to stop. The Python tools check evidence,
constraints, calculations, and authority; they do not select a bargaining tactic
or price. Supplier sends use Ambiguous email, and contractor progress, decisions,
and recommendations appear as comments on the originating Ambiguous task.

The first live integration slice completed at **14:35 PDT on September 12, 2026**,
using actual task
`285b8a73-572a-4e0a-9509-f97cf994f6f6` and fresh supplier run
`run_402632f04bb94032b83ffa8ecd69f96f`. It covers the first three source lines;
it does not establish completion of the 25-component house package. The task was
created under Chip for integration testing, not authored by the contractor.
Hermes received the remote supplier's canonical issued quote
`quote_d7479895425441aa89b8ddb47946ddcc` revision 1, validated all three lines at
**USD 2,300 delivered**, published the recommendation, and completed the task.
The buyer chose its initial $2,300 proposal and stopped when the supplier matched
it; this run does not demonstrate a post-quote counteroffer or substitution approval.
Two earlier emails reached the recipient without their intended content and are
retained as failed attempts. No order was placed. See [demo context](demo-context.md)
for scenario provenance and the distinction between live channels and material data.

## Enable an actual task

A contractor can also start through Chip's direct chat. Configure the ignored
`.local/hermes/procurement/intake-config.json` with `enabled`, a fresh `run_id`,
`suppliers`, `catalog_urls`, `project_id`, and `armed_at` (UTC). Optional
`expected_mailbox_id` verifies the intended shared mailbox. The DM model invokes
`python /workspace/integrations/ambiguous/intake.py --message-id MESSAGE_UUID`.
The tool reads the actual unedited contractor DM, preserves its text in a new
assigned task, verifies contractor project access and subscription, then enables
that task's procurement configuration. A durable message journal prevents a
second task or reuse of the supplier run. Merely drafting a chat message starts
nothing; the contractor sends it.

Set `TAKEOFF_AMBIGUOUS_MAILBOX_ID` in the ignored runtime `.env` to use Builders Co
or another authorized shared mailbox for both supplier sending and reply ingestion.
The listener binds this setting when a task is initialized. Existing runs retain
their original mailbox, including personal mail for legacy runs. Restart the chat
listener after changing its environment; the separate voice server is unaffected.
Supplier mail remains the strict JSON envelope by default. The optional
`TAKEOFF_SUPPLIER_MAIL_MESSAGE_FIRST=1` adds the model's readable message before
that envelope only when the receiving supplier supports mixed-text parsing.

Use the isolated credentials and runtime described in [Ambiguous setup](ambiguous.md).
The ignored configuration is `.local/hermes/procurement/config.json`, resolved
inside the container through `HERMES_HOME`. Its shape is:

```json
{
  "enabled": true,
  "run_id": "FRESH_SUPPLIER_RUN_ID",
  "task_ids": ["ACTUAL_AMBIGUOUS_TASK_UUID"],
  "suppliers": [{"id": "ACTUAL_VENDOR_ID", "email": "ACTUAL_VENDOR_EMAIL"}],
  "catalog_urls": ["https://SUPPLIER_HOST/CONFIRMED_PUBLIC_CATALOG_PATH"]
}
```

These are placeholders, not working endpoints or authorization. The implementer
configures only an authorized procurement task and its agreed suppliers. The task
must be assigned to Chip, explicitly allowlisted, active, and created by the
verified contractor or Chip. The Chip-created case supports authorized integration
tests; task authorship must be represented accurately. No task is admitted while
configuration is disabled or required references are missing.

**Make integration tasks visible to the contractor.** Ambiguous tasks without a
`project_id` are private to their creator and assignee. A task created by Chip and
assigned to Chip must belong to a project the contractor can access. Create a
private project, add the contractor through `POST /api/projects/{id}/members`, and
set the task's `project_id`. Add the contractor to `subscriber_ids` for updates.
Verify project membership and task assignment after writing; a successful task
API response under Chip's identity does not verify contractor visibility.

Bind **one fresh remote supplier run to one actual task**. A different task cannot
reuse an existing local binding to that supplier run. Obtain a reset/new run from
the supplier owner for another attempt, retain the previous evidence, and configure
the new references. Editing configuration does not rewrite an initialized task's
saved run, suppliers, or requirements.

The configured public supplier host must also be permitted by
`runtime/hermes/egress.py`; a URL in this JSON alone does not enable network access.
Catalog fetches require HTTPS, the configured hostname, no redirect, and no embedded
credentials. Use the supplied public catalog surface; private supplier state is
not a buyer input. Keep runtime configuration and credentials out of Git.

```bash
scripts/hermes bridge-start
scripts/hermes bridge-status
```

The same bridge polls contractor DMs and procurement tasks. A single procurement
worker thread runs bounded task turns while the main thread continues polling DMs,
so an active procurement turn does not prevent direct replies. Each thread has its
own API client; the existing listener lock still permits only one listener process.
Shutdown stops new polls and lets an in-flight task finish its durable writes.
There is no separate host daemon. After a successful turn, the
listener records the native Hermes session ID. New contractor comments and
correlated supplier replies resume that task's session with `--resume`, together
with its persisted procurement snapshot. Hermes should send a grouped inquiry,
finish the turn, and wait for the reply event rather than sleep or busy-poll.

## Tools and JSON inputs

Inside the isolated container, inspect the tool entry point and current task:

```bash
python /workspace/buyer/cli.py --help
python /workspace/buyer/cli.py --task-id TASK_UUID snapshot
python /workspace/buyer/cli.py --task-id TASK_UUID COMMAND --input /opt/data/workspace/input.json
```

From the host, prefix the Python command with `scripts/hermes exec`. Every command
except `snapshot` takes JSON from `--input` or stdin. Snapshot is a compact private
working index; fetch an individual preserved source with `evidence` instead of
repeating entire catalogs and message bodies in every model turn. Use the actual task UUID for `--task-id`;
use the separate supplier run ID and current request revision from the snapshot
inside action/proposal payloads. IDs must remain stable across retries.

| Command | JSON input and effect |
| --- | --- |
| `evidence` | `{"id":"SOURCE_ID"}` retrieves one complete preserved source from the snapshot's evidence index. |
| `requirements` | `{"requirements":[{"id":"house-01","source_text":"original line","quantity":12,"unit":"sheet","specifications":{},"missing_essentials":[]}],"constraints":{}}` records source-derived requirements. Optional `budget_cap` records an explicit positive hard budget; constraints may include `delivery_deadline` and `delivery_zone`. Never invent a budget or erase an ambiguous specification. |
| `catalog` | `{"url":"CONFIRMED_PUBLIC_CATALOG_URL"}` fetches JSON and saves public product/source evidence. |
| `clarify` | `{"requirement_id":"house-10","key":"facing","specification_attribute":"facing","value":"unfaced","source_id":"ACTUAL_CONTRACTOR_COMMENT"}` records a missing essential only from the actual unedited contractor answer. Fitting clarification uses `fitting_system` and `connection_system`. These values are syntax examples, not supplied contractor answers. |
| `assess` | `{"requirement_id":"house-01","product_id":"DISCOVERED_PRODUCT_ID"}` checks specifications, pack conversions, minimum quantity, stock, and approvals. |
| `assess_all` | `{}` checks every saved product whose catalog `requirement_id` matches a saved requirement, using the same checks as `assess`. Returns compact candidate IDs/status counts and explicit skipped mappings; does not select products or send inquiries. |
| `send` | Inquiry/counter object below. Checks authority, known supplier, current quote references, numeric terms, and action limits before sending an idempotent email. |
| `offer` | `{"source_id":"RECEIVED_EVIDENCE_ID","quote":{}}`, replacing `{}` with the **exact full supplier quote object** already present in saved evidence. Preserves raw terms and returns normalization results; unknown fees/taxes or invalid arithmetic remain blockers. |
| `decision` | Proposal/question object below. Validates the substitution against current evidence, saves it before publication, and posts the exact proposed scope. |
| `plan` | `{"quote_ids":["CURRENT_QUOTE_ID"]}` checks the selected whole packages, coverage, approved products, stock, delivery, fees, conditions, and budget. Hermes chooses which packages to evaluate. |
| `publish` | `{"id":"result-1","plan":true}` freshly validates and posts the saved evaluated explanation. Adding `"final":true` marks the task done only if its plan is complete. `{"id":"progress-1","content":"Factual progress"}` posts a progress comment. Neither action places an order. |

An inquiry has this shape; all values below are illustrative:

```json
{
  "id": "inquiry-1",
  "type": "inquiry",
  "run_id": "CURRENT_SUPPLIER_RUN_ID",
  "request_revision": 1,
  "vendor_id": "CONFIGURED_VENDOR_ID",
  "message": "Quote the specified quantities, confirm stock and delivery, and include taxes and mandatory fees."
}
```

For a counter, use `type: "counter"`, `previous_quote_id`, and the numeric terms
Hermes chooses, such as `target_total` and `currency: "USD"`. Optional `items`
identify real requirement/product pairs and positive quantities. The message must
state the actual requested requirements and terms. A proposed target is not a
supplier quote. Use `send`, not raw Ambiguous mail commands; neither orders nor
supplier acceptance are supported, including simulated commitments.

## Contractor substitution decision

```json
{
  "proposal": {
    "id": "substitution-1",
    "run_id": "CURRENT_SUPPLIER_RUN_ID",
    "request_revision": 1,
    "requirement_id": "house-01",
    "product_id": "DISCOVERED_SUBSTITUTE_ID",
    "changed_attributes": {"type": "EXACT_CONFIRMED_NEW_VALUE"},
    "candidate_id": "CURRENT_CANDIDATE_ID",
    "product_revision": "CURRENT_PRODUCT_REVISION"
  },
  "question": "Explain the actual specification change and supported consequences."
}
```

Use either `candidate_id`/`product_revision` or `quote_id`/`quote_revision`, not both.
Attributes must exactly match the assessed substitution. The visible comment
includes that scope. The actual contractor must reply **to that comment** with
`Approve substitution-1` or `Reject substitution-1`. The listener checks the
author, parent comment, immutable source ID/time, current proposal, and explicit
choice. A resolved thread, silence, supplier message, conditional sentence, or
stale answer grants no approval. Changed/deleted answer comments invalidate their
effective decision; a revised decision requires a fresh reviewed proposal and
explicit answer. A missing-information clarification is not substitution approval.

## Recovery and evidence

Atomic task snapshots, events, source evidence, action receipts, proposals, and
session references live under the ignored procurement state directory. Confirmed
email retries return the saved receipt. Uncertain email retries reuse the exact
saved body/idempotency key and do not consume another action. Comment publication
has no assumed server idempotency: recovery requires one matching recent unedited
comment; absent or ambiguous matches stop for reconciliation. Never change an ID
or delete a saved transmission to force a retry.

Supplier sends must use `body_markdown`: the live service accepted a `body_text`
payload but delivered tracking-only messages. Those first failed attempts remain
in the run evidence. Incoming list rows can omit bodies even with `detail=full`;
hydrate the individual message and extract text from HTML when necessary. Send
receipts prove acceptance by the mail service, not successful supplier processing.

A changed task title/description pauses procurement as `source_changed`.
An interrupted generating turn pauses as `interrupted`; a failed/timed-out turn
pauses as `failed`. The listener preserves evidence and reports the interruption.
There is no general resume/reset command: the implementer must inspect the saved
actions and actual remote outcomes, reconcile the checkpoint, and deliberately
restore an appropriate state. Restarting the bridge alone does not clear a pause.
Only `snapshot` and `publish` are available through the buyer CLI while paused.

Focused offline checks cover the buyer calculations/validators and transport
recovery. They are not proof of live supplier or contractor interaction:

```bash
python3 -m unittest discover -s buyer -p 'test_*.py'
python3 -m unittest discover -s integrations/ambiguous -p 'test_*.py'
```

Record the real request, discovery, remote offer, negotiation, contractor answer,
and final evaluated result before claiming that journey. A three-line slice,
complete 25-component run, failed attempt, and captured replay remain distinct.
