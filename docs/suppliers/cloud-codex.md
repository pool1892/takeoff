# Supplier cloud host

The Railway `supplier-codex` service runs the existing supplier Codex app-server
harness and canonical quote engine. It uses a saved ChatGPT account login, without
an OpenAI API key. The buyer Hermes installation stays separate.

The image pins Codex CLI `0.154.0`. A persistent volume stores the supplier SQLite
ledger and transport evidence in `/data/suppliers`, and the independent Codex home
in `/data/codex`. Startup creates a fresh scenario only if no active run exists;
restarts retain the active run, quotes, and conversations. The model has the same
restricted dynamic tools as the local supplier runtime: commercial validation
executes in the host, while shell, filesystem, unrelated MCP, and personal context
tools are disabled. No laptop ledger or buyer configuration is uploaded.

## Authentication and deployment

Build `deploy/codex-supplier/Dockerfile` from an explicitly staged source tree that
contains only `src/takeoff_suppliers`, `pyproject.toml`, and the Dockerfile. Exclude
`.git`, `.local`, caches, recordings, credentials, and generated runs before upload.
Mount a persistent volume at `/data`. Configure fresh, distinct provider secrets
`TAKEOFF_OPERATOR_TOKEN` and `TAKEOFF_BUYER_TOKEN`; set `CODEX_HOME=/data/codex`,
`TAKEOFF_CLOUD_HOME=/data/suppliers`, and `PORT=8000`.

OpenAI documents [copying an existing authentication cache to a headless host](https://learn.chatgpt.com/docs/auth#fallback-authenticate-locally-and-copy-your-auth-cache).
Transfer only the authorized `auth.json` through the private service's SSH stdin,
write it to `/data/codex/auth.json` with mode `0600`, and never include it in a build,
command argument, log, repository, or chat. Codex handles its own login and refresh.
Keep the refreshed cloud file on the volume: do not repeatedly overwrite it with a
stale laptop copy. If the account stops authenticating, use the supported Codex
login flow; do not race multiple refresh writers against the same file.

## Verification and controlled cutover

The existing website and REST offer/approval routes are available. Operator bearer
authentication protects the additional endpoints:

- `GET /operator/status` returns the active run ID and safe Codex account status.
- `POST /operator/vendors/{vendor_id}/agent` accepts `request_id` and `message`,
  invokes the existing supplier runtime, and returns canonical records. Reusing an
  ID with a different message returns `409`. This endpoint does not send mail.

Validate an isolated request, inspect its actual quote and arithmetic, and verify
the same run and quote survive restart before changing the live handoff. Automated
tests exercise the HTTP boundary with a fake runtime; only a successful cloud model
turn establishes cloud model execution.

The cloud service initially starts no mailbox workers. To cut over, the operator
must first stop the local worker for each vendor, then configure that vendor's
authorized Ambiguous identity, buyer mappings, and the agreed run in the cloud.
Run the existing `takeoff-suppliers --home /data/suppliers worker RUN_ID VENDOR_ID`
under the deployment supervisor. Never poll the same vendor identity concurrently
from local and cloud workers. Export canonical and transport evidence through the
existing CLI before any deliberate state migration; starting a fresh cloud trial
does not silently continue a laptop run.
