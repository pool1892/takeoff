---
name: takeoff-workflow
description: Implement or coordinate Takeoff hackathon work from its GitHub issues, including ownership, shared interfaces, focused checks, and cross-computer handoffs. Use for project implementation, integration, review, and work-status updates.
---

# Work from the current Takeoff issue

Read the repository `AGENTS.md`, `README.md`, and the assigned GitHub issue with its
recent updates. Today's accepted team decisions take precedence over older plans.
Use GitHub Issues and the linked Project; do not initialize or use Beads.

Christoph (`pool1892`) owns buyer/integration; Tapan (`chughtapan`) owns suppliers;
Ehsan (`ehsandaya1-blip`) owns Ambiguous UX/demo. Keep human assignees intact when
agents do the work. Supplier and UX epics describe outcomes; their owners choose
their internal implementation and breakdown.

Before editing, identify the smallest useful outcome, current branch/worktree,
the files you own, and the real handoff needed from another person. Preserve
concurrent work. Independent bounded agent work is welcome; do not duplicate a
running lane or send multiple writers into the same shared interface.

Use representative examples to start work before every remote dependency exists.
Connect a thin real path early: Ambiguous task to local Hermes, remote supplier
interaction, result back in Ambiguous. A local fixture is preparation for that
connection, not proof that it works across computers or workspaces.

When an interface changes, communicate the concrete request/response or data
example and the effect on the other owner. When blocked, name the missing input
or failed boundary and continue independent work. Do not silently replace Hermes,
Ambiguous, the supplier computer, or a core channel to pass a test. Phone remains
stretch and cannot block core acceptance.

Validate the meaningful changed behavior with focused checks. Report what was
tested and what remains: fixture, actual workspace, cross-computer interaction,
human-visible approval, and replay are distinct evidence. Commit coherent changes
and link the relevant revision or result in the issue when authorized to update it.

An issue update should say what now works, the evidence, any material blocker,
and the next handoff. Close an issue only when its outcome is met; move the linked
Project status consistently. Keep detailed implementation in code and concise
documentation, not repeated comments or a parallel tracking system.
