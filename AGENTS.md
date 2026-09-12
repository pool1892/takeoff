# Takeoff — hackathon working instructions

This is a one-day hackathon. Move quickly and aggressively: make sensible reversible
decisions, use coding agents in parallel for bounded independent work, and get real
integrations working early. Optimize for an excellent working demonstration, not a
production platform or a perfect process. Do the authorized work; do not stop at plans.

## Read first, in both harnesses

- This file is the canonical project instruction file. `CLAUDE.md` is a symlink to it.
- At the start of project work, read `README.md`, the relevant GitHub issue and recent
  updates, and `.agents/skills/takeoff-workflow/SKILL.md`.
- For scenario design, evaluation, recording, or demo claims, also read
  `.agents/skills/takeoff-demo/SKILL.md`.
- Canonical skills live in `.agents/skills/`; `.claude/skills/` contains relative
  symlinks to those same directories. Edit the canonical source, never make copies.
- Skills are discovered by name/description and loaded when used. Essential context
  belongs here so neither harness depends on selecting a skill to know the architecture.

## The product and story

Takeoff helps a general contractor turn house material requirements into an explained
buying plan: discover suitable products, obtain comparable offers, negotiate, ask about
meaningful tradeoffs, and recommend what to buy with evidence.

The demonstration starts with a contractor task in Ambiguous, shows product discovery
and purposeful negotiation with remote suppliers, brings back one consequential human
decision, and finishes with an understandable buying recommendation in Ambiguous.

Use a small representative material package. Eight requirements and three core supplier
encounters are a useful starting scenario, not a complete bill of materials for a house.
The team chooses the concrete data. Do not claim arbitrary architectural plans can be
converted into construction-ready specifications.

## Current architecture — authoritative team decisions

- **Buyer:** Hermes runs the buyer agent on Christoph's computer. Supporting tools
  provide discovery, communication, calculation, and evidence. Do not replace Hermes
  with a new custom agent runtime unless the team changes that decision.
- **Contractor frontend:** a new buyer Ambiguous.ai workspace is both the task source
  and the place where all contractor-facing information appears: progress, supplier
  exchanges, comparisons, questions, answers, and final results. Ehsan owns the
  experience within Ambiguous; a new standalone frontend is not the requirement.
- **Suppliers:** all vendors run on a different computer. Core vendor modes are
  website, email, and agent-to-agent, reached through appropriate tooling. Use
  Ambiguous for vendor communication and integrate website activity and evidence
  into that workspace flow. Agree actual transport handoffs with Tapan.
- **Agent-to-agent:** the supplier agent has a separate, second Ambiguous workspace
  representing its side, with independent identity, context, credentials, and private
  commercial state. The buyer sees only information offered through the channel.
- **Phone:** fully sketched stretch, not a core dependency. A live remote supplier
  call may join the same workflow. The core material package must work without it.
- **Strategy:** partly scripted and bounded. Author a small scenario and action menu;
  let actual offers, constraints, and contractor answers determine the decisions and
  result. Do not hardcode a winner or invent a competing offer to improve the story.
- **Explanation:** the selected package, price, delivery, tradeoffs, rejected options,
  and supporting quotes/approvals must be inspectable.

The new workspaces are being set up by the team. Obtain their current references;
do not assume an older workspace or credentials are the target. Keep the Takeoff
Hermes state separate from unrelated personal agent installations and memories.

## Human ownership and shared work

| Human | GitHub | Responsibility |
|---|---|---|
| Christoph | `pool1892` | Buyer behavior, shared handoffs, integration, evaluation |
| Tapan | `chughtapan` | Supplier world and supplier-side implementations |
| Ehsan | `ehsandaya1-blip` | Ambiguous UX, explanation experience, demo and production |

Use GitHub Issues and the repository-linked GitHub Project. **Do not use Beads.**
Today's team decisions and current issues supersede yesterday's brainstorm and work
decomposition. Do not import old module numbers, contracts, deadlines, or architecture
as requirements. This repository and its GitHub plan are the shared source of truth.

Tapan and Ehsan receive broad functional epics and own their internal design. Respect
their agency: agree boundaries and examples, and do not subdivide or redesign their
work without coordinating. Human issue assignees remain accountable even when coding
agents execute subtasks. Keep each agent's write ownership clear and preserve others'
changes; do not reset, clean, or overwrite work to simplify integration.

## How to work at hackathon pace

- Build the smallest real request-to-result journey first, then expand. Connect early;
  do not wait for every component to be polished before attempting integration.
- Choose the simplest implementation that demonstrates the agreed behavior. Avoid
  speculative abstractions, general frameworks, and broad refactors.
- Use fixtures and examples to let others build independently. Coordinate shared
  interface changes promptly; do not surprise the other computer with a silent change.
- Timebox unfamiliar plumbing. If blocked, surface the specific issue and a concrete
  alternative; continue independent work. A change to Hermes, Ambiguous, the separate
  supplier computer, or required channels is a team decision, not a local shortcut.
- Keep issue updates short and useful: outcome, evidence, blocker, next handoff. Do not
  flood the tracker with command logs or invent additional process documents.
- Verify meaningful behavior and the arithmetic/constraints the demo relies on. Run
  focused checks; do not build a large test suite for low-impact reversible changes.
- Commit small coherent changes. Read the current branch/status before editing,
  preserve unrelated work, and coordinate Git pushes and shared files.
- Make critical-path progress aggressively within the task's authorization. A planning
  or read-only request still means no implementation or external writes.

## Trustworthy behavior and evidence

- Preserve requirements, source references, quoted terms, and approvals. Unknown stock,
  fees, or product compatibility are not automatically favorable values.
- Keep a proposed target distinct from a confirmed offer. Apply bundle conditions,
  units, availability, and delivery to the whole package, not just unit prices.
- No answer is not permission to change a specification, exceed a budget, or miss a
  deadline. Continue independent work and keep the unresolved decision explicit.
- Supplier data may be simulated while channels are real. Distinguish fixtures,
  simulated businesses, live cross-computer communication, and recorded replay.
- Measure human effort, elapsed time, valid completion, and price separately. A cheapest
  opening-offer package is an automated baseline, not a human. Do not claim superiority
  to professional buyers from a scripted demo or a few volunteer attempts.
- Keep all attempts in a scored comparison, including failures. Never invent savings,
  supplier benefits, approvals, or live verification. Label examples and proposed data.

## Local state and credentials

Keep keys, tokens, runtime homes, recordings, private messages, and generated run data
out of Git unless a specific sanitized artifact is intentionally selected for sharing.
Use ignored local configuration and document variable names/examples without values.
No copying the other machine's private supplier state into buyer context. No real
orders, public submissions, or unrelated messages merely because the demo can generate
them; respect the task's actual authorization.

For commands, use current installed help or primary docs when behavior is uncertain.
Do not infer host authentication from a sandbox network or permission failure. Never
expose a credential while diagnosing access. The user often dictates prompts: read
for intent, and clarify only material ambiguity.
