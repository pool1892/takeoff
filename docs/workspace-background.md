# Residential workspace background

[Demo context](demo-context.md) describes the business scenario and live-channel
boundaries. `examples/workspace/residential-projects.json` adds three authored
residential projects around Bill's house build: a Sunset kitchen remodel, a
Bernal Heights backyard ADU, and a Richmond primary bath renovation. Each has
four practical tasks, dated around September 12, 2026.

These background descriptions and statuses are authored presentation context.
They are not observed construction progress, completed procurement outcomes, or
work performed by Chip. Ambiguous's `todo` status represents the backlog. Task
owners are the existing human contractor identity (presented as Bill) or nobody;
the contractor is also a project member and task subscriber. The script does not
rename the user's account or assign background tasks to Chip.

Four companion Markdown documents live in
[`examples/workspace/documents/`](../examples/workspace/documents/): Sunset
rough-in and cabinet coordination, Bernal ADU access and foundation readiness,
Richmond bathroom finish decisions and pre-tile checks, and Bill's September
14–18 week-ahead brief. They use the same project names, owners, dates, and open
dependencies as the task examples. Bill is the project lead in the authored
content; the Ambiguous API records the actual identity that creates each copy.
The week-ahead brief carries the single discreet link to the shared demo context.

The separate original contractor material request comes from
[`examples/procurement/contractor-house-request.txt`](../examples/procurement/contractor-house-request.txt).
Its workspace copy identifies Chip as the copying agent, links the procurement
task, and keeps the original wording in a verbatim block. It is a source record,
not an additional authored background note or a new buying recommendation.

## Workspace publication checkpoint

The original request copy, four background documents, and three background
spreadsheets have been created and verified in Ambiguous. A separate native
procurement spreadsheet created by Chip is also verified. The three background
spreadsheets provide project planning context; they do not establish purchased
materials, passed inspections, or construction performed by Chip.

Three actual supplier messages were forwarded to the operator's inbox. Raw
forwarding drafts intended for the shared contractor inbox were not sent at this
checkpoint. Six human-style emails were subsequently delivered to the shared
contractor inbox and verified by readback at 22:45:12 UTC. They are separate staged
presentation material. Their ten-home prices,
derivation, and limits are recorded centrally in
[demo context](demo-context.md#ten-home-presentation-correspondence).

The [ten-home contractor request](../examples/procurement/contractor-ten-home-request.txt)
is a separate prepared source. It requires fresh quotes for the larger quantities;
neither the background records nor the staged correspondence establish a completed
ten-home buying run.

## Project and task seed commands

Preview the authored projects and tasks locally, without credentials or API calls:

```sh
python integrations/ambiguous/seed_workspace.py --preview
```

Inside the configured runtime, review what is missing before applying:

```sh
scripts/hermes exec python /workspace/integrations/ambiguous/seed_workspace.py --check
scripts/hermes exec python /workspace/integrations/ambiguous/seed_workspace.py --apply
```

Optionally add `--main-project-id "$TAKEOFF_MAIN_PROJECT_ID"` to check/apply.
That changes only the selected project's name to `Bill's house build` and ensures
contractor membership. Existing live task contents, assignments, statuses,
subscriptions, and procurement state remain untouched. Update any separate local
project alias record through its owner; this script does not rewrite that file.

The default journal lives under `$HERMES_HOME/workspace-seed/`. Stable invisible
Markdown markers identify authored resources across restarts, including a write
whose response was lost. Reapplying preserves edits to existing task content and
repairs missing contractor membership/subscriptions. A same-name resource without
a marker, duplicate markers, or an uncertain write missing from the API requires
manual review; the script stops rather than silently retrying creation. Keep one
runtime journal and do not run independent copies concurrently. Credentials come
from the existing bridge API environment and are never printed.

After applying, rerun `--check`; an empty operations list confirms the seed and
visibility records are present. These commands seed projects and tasks; the
document, spreadsheet, and mail publication checkpoint above is reported separately.
