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

Preview the complete authored content locally, without credentials or API calls:

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
visibility records are present. No workspace changes are implied by this document.
