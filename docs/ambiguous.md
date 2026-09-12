# Ambiguous buyer connection

The verified buyer workspace is **takeoffAI**, supplied by Christoph. **Chip** is
Christoph's managed personal agent there (username `takeoff-hermes`). Its scoped
runtime key is separate from Christoph's bootstrap admin key. The supplier agent must keep its own
workspace and credentials on the supplier computer.

The official `ambiguous` CLI is pinned to **0.9.0** under
`integrations/ambiguous/`. Its command catalog comes from the live OpenAPI schema;
use `catalog <module>` before choosing command flags.

## Install and identify

Use the repository container launcher described in [Hermes setup](hermes.md).
The CLI and dependencies stay in this checkout; nothing is installed globally on
the host. Run npm from the repository on the host because Hermes sees the code
mount as read-only. To reproduce the dependency install:

```bash
npm ci --prefix integrations/ambiguous --ignore-scripts --no-audit --no-fund --cache .local/npm-cache
scripts/hermes ambi --version
scripts/hermes ambi catalog tasks
```

Enter the new buyer agent's token with `scripts/hermes credentials`. It is stored
in the ignored `.local/hermes/.env`; do not paste it into chat, a command argument,
or Git. The integration reads these variables from that file:

| Variable | Meaning |
| --- | --- |
| `AMBI_API_TOKEN` | New takeoffAI buyer agent API key |
| `AMBI_API_URL` | `https://api.ambiguous.ai`, the pinned CLI's production default |
| `TAKEOFF_AMBIGUOUS_WORKSPACE_REF` | `takeoffAI`, the human-supplied name/reference |
| `TAKEOFF_AMBIGUOUS_WORKSPACE_ID` | Verified `workspace_id` from the API |
| `TAKEOFF_AMBIGUOUS_USER_ID` | Verified buyer agent `user_id` from the API |

With the token present, connect the buyer identity:

```bash
scripts/hermes ambi connect
```

This reads only `/api/users/me` and `/api/workspace`. It requires a dedicated
`agent` identity and a complete workspace name or slug matching `takeoffAI`,
without regard to case. On success it saves the returned workspace/user UUIDs to
the two ID variables in `.local/hermes/.env`, preserving other configuration and
setting permissions to `0600`. Symlink configuration paths are rejected. It makes
no external changes and never prints the token.

If the name/slug or identity type does not match, connect prints the safe returned
identity and leaves local configuration unchanged. Obtain the correct buyer agent
Connect instructions from Ehsan. `scripts/hermes ambi identify` provides the same
read-only discovery without saving the IDs, if needed.

Then verify the configured identity and the read paths:

```bash
scripts/hermes ambi check
scripts/hermes ambi tasks list --limit 5 --json
scripts/hermes ambi poll
```

`check` verifies the token against **both** IDs. Every authenticated command through
the wrapper repeats that check before passing control to the official CLI. Public
version/help/catalog discovery and the read-only `identify` step do not require
the saved IDs. `connect` discovers and saves them after checking the workspace
reference and agent type. Rejected credentials, a different identity, and network failure
remain errors; they are never treated as an empty inbox.

## API key scopes

Create the key for the **dedicated buyer agent user** in takeoffAI. This starting
preset covers the planned task, notification, chat, supplier mail, document, and
attachment operations without granting wildcard or administrative write scopes:

```text
tasks.read,tasks.write,notifications.read,notifications.write,chat.read,chat.write,mail.read,mail.write,mail.send,documents.read,documents.write,drive.read,drive.write,users.view,settings.view
```

These exact scope names and descriptions were verified in the
[official public admin client](https://app.ambiguous.ai/assets/AdminPage-Bv9AFKgI.js).
The preset is an initial integration selection, not a proven minimal set: live
permission checks still have to pass. The public OpenAPI schema exposes scope
strings but does not publish the full scope-to-endpoint mapping. If a specific
operation returns a scope error, inspect that requirement before changing the key.

The current personal API-key settings UI accepts a comma-separated list but does
not send the API's `confirm_wildcard` flag, explaining its wildcard-confirmation
error. That personal page creates a key for the currently signed-in user; using
the buyer agent as the key's owner is a separate requirement from selecting scopes.

## Hermes task intake

The bridge now includes an assigned-task listener with a private explicit task
allowlist, supplier-mail intake, durable tools, and native Hermes session resume.
See [configuration and recovery](procurement.md). An actual three-line integration
task has reached the remote supplier and received a reply; completing the buying
recommendation and full25-line journey remains separate verification.

`scripts/hermes ambi poll` calls the CLI's actual
`notifications poll --format hermes` command with expected user/workspace IDs. It
returns complete unread events, `has_more`, `next_cursor`, and `wakeAgent`; it does
not mark notifications read, send messages, or start a listener. Drain subsequent
pages using `--cursor` when `has_more` is true.

The upstream `notifications setup hermes` helper creates a native recurring Hermes
job, but it also attempts `hermes gateway install --start-now --start-on-login` and
requires a saved CLI credential instead of an environment token. The Takeoff
wrapper therefore leaves that helper disabled. Schedule the poll command inside
the container when the runtime's gateway lifecycle is wired; a one-off poll is not
autonomous intake. Do not install a host daemon or reuse a personal Hermes profile.

The [official operating guide](https://api.ambiguous.ai/skill) specifies that a
handler marks each notification read immediately before acting, proceeds only
when `was_unread` is true, and replies in the originating Workspace conversation.
A Hermes final response using local delivery does not itself post to Ambiguous.
Task triggers, contractor decision locations, and output presentation still need
Ehsan's actual workspace handoff. Supplier email/address and agent transport remain
Tapan's handoff.

## Isolation and verification

Docker, configured by `scripts/hermes`, supplies the filesystem boundary. The
Ambiguous wrapper additionally rejects accidental host launches and requires a
home directory inside the mounted checkout. CLI cache/config fallback stays under
that isolated home, and authenticated calls require an explicit buyer token.
The guard is not an independent sandbox. Ambiguous necessarily receives network
requests and any content intentionally sent through its API.

Verified during setup: npm package/version, bundled CLI behavior, public live
OpenAPI schema, and offline identity checks for mismatched users/workspaces,
failed authentication/network, safe output, configuration preservation, private
file permissions, and symlink rejection. The identity checks can be rerun:

```bash
node integrations/ambiguous/identity.test.mjs
```

Authenticated identity and workspace access are verified. Setup created the
managed member agent, installed its 15-scope runtime key, and revoked its temporary
initial key. It did not create a new workspace. Autonomous procurement task
handling and cross-computer supplier exchanges remain separate milestones.

## Talk to Chip

Open a direct message to **Chip** in takeoffAI. Start the listener from the Docker
admin pane with `scripts/hermes bridge-start`; check or stop it with
`scripts/hermes bridge-status` or `scripts/hermes bridge-stop`.

The listener accepts only two-person DMs between the verified contractor and
Chip. It uses actual message IDs and a durable local ledger, supplies recent
conversation context to Hermes, and posts its reply to the same conversation.
Chip's voice and behavior live in `runtime/hermes/SOUL.md`, copied into the isolated
runtime as `.local/hermes/SOUL.md`. The bridge loads that runtime personality for
each message. Keep the runtime copy in sync when intentionally changing it.
It does not depend on notifications remaining unread. Ambiguous has no documented
idempotency key for chat sends; uncertain delivery is reconciled before a retry.

Verified September 12: the listener received Christoph's DM, ran Hermes with Sol
and high reasoning, and posted the final reply back to that conversation. Fast
(`service_tier: priority`) was verified in the serialized request configuration;
the exact tier served by OpenAI was not separately recorded. This confirms chat,
not the complete procurement workflow.

Primary references, inspected September 12, 2026:

- [Official CLI quickstart](https://www.ambiguous.ai/agents/cli)
- [Published CLI package and source bundle](https://www.npmjs.com/package/ambiguous/v/0.9.0)
- [Live OpenAPI schema](https://api.ambiguous.ai/api/openapi.json)
- [Official operating guide](https://api.ambiguous.ai/skill)
- [Official MCP setup](https://www.ambiguous.ai/agents/mcp), if a later tool path
  needs the HTTP endpoint at `https://app.ambiguous.ai/mcp`

The marketing examples use `AMBIGUOUS_API_KEY`; the current CLI actually consumes
`AMBI_API_TOKEN`. The package README also contains older configuration examples.
The pinned CLI implementation and its live catalog are authoritative for the
commands above.
