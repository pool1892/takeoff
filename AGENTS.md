# Takeoff — hackathon working instructions

This is a one-day hackathon. Move quickly and aggressively: make sensible reversible
decisions, use coding agents in parallel for bounded independent work, and get real
integrations working early. Optimize for an excellent working demonstration, not a
production platform or a perfect process. Do the authorized work; do not stop at plans.

## Today's deadline and implementation checkpoints

All times below are **September 12, 2026, America/Los_Angeles (Pacific local time)**.
Christoph set a **4:30 pm submission deadline** and wants the working demo ready
by **4:00 pm**, leaving the last half hour for fixes, recording, and submission.
At roughly 2:00 pm this leaves two hours of build time; check the actual clock
before taking on more work. These checkpoints are targets, not claims of completion.

| Time | Target |
|---|---|
| **2:10 pm** | Agree the shared request/data boundaries and reconcile the archived planning context. The implementation agents choose the exact components and first live slice together. |
| **2:45 pm** | One actual Ambiguous task → remote supplier offer → explained recommendation works through Hermes. |
| **3:20 pm** | Expand to the 25-component house-material package, agent-chosen negotiation, and one meaningful substitution decision. |
| **3:30 pm** | Stop adding features. Verify approval/rejection, missing information, and restart behavior; capture the actual run. |
| **4:00 pm** | Working demo and captured run ready. |
| **4:00–4:30 pm** | Buffer for fixes, recording/packaging, and submission; no new feature work. |
| **4:30 pm** | Submission deadline. |

Run independent buyer lanes in parallel: discovery/product mapping; quote and
package calculations; model-directed negotiation and contractor approvals. The
main implementer owns Hermes/Ambiguous integration, shared interfaces, persistent
runs, and supplier coordination. Use Astra/high subagents with Fast/priority where
available, with separate file ownership. Supplier and UX owners work in parallel
on their respective computers; integrate a small real path before full polish.

Keep discovery and product selection, genuine buyer/vendor strategic decisions,
and a meaningful substitution approval in the core. Website, email, and agent-to-agent
supplier channels remain the agreed core; changes to that scope require a team
decision. Phone, advanced controls, and broad evaluation must not delay the live
path. Use recorded runs for reliable playback rather than scripting strategy.

The first reachable supplier channel and buyer-visible catalog are critical
external dependencies. Surface a missed checkpoint or missing handoff promptly,
continue independent work, and adapt the remaining work to the time left. Never
report a fixture or unconnected component as a completed live milestone.

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
- Historical conversations are indexed in `transcripts/README.md`. Use them to
  recover intent, preserving chronology; current explicit decisions supersede old
  proposals, module plans, counts, providers, and historical completion claims.

## The product and story

Takeoff helps a general contractor turn house material requirements into an explained
buying plan: discover suitable products, obtain comparable offers, negotiate, ask about
meaningful tradeoffs, and recommend what to buy with evidence.

The demonstration starts with a contractor task in Ambiguous, shows product discovery
and purposeful negotiation with remote suppliers, brings back one consequential human
decision, and finishes with an understandable buying recommendation in Ambiguous.

Use **25 representative house-material requirements** and three core supplier
encounters as the full-demo target, not a complete bill of materials for a house.
Expand beyond 25 only if public catalog coverage and the deadline permit. The exact
components and first live slice are delegated to the buyer/supplier implementation
agents together. An early small slice is integration progress, not completion of
the full package. The contractor's list should
contain realistic shorthand and ambiguity that the buyer resolves against available
supply. Preserve the source; do not replace discovery with preassigned product IDs.
The existing UX fixture does not determine the procurement scenario.
The team chooses the concrete data. Do not claim arbitrary architectural plans can be
converted into construction-ready specifications.

Make the procurement workload visible: requirements mapped, candidate alternatives
checked, pack conversions, supplier exchanges, and actual contractor interventions.
Group inquiries and negotiations by supplier/package rather than creating 25 separate
conversations. Record real elapsed time and human effort; line count alone is not a
measured time-saving claim. Ehsan owns the edited video and final presentation, so
hand over useful captured runs and evidence early enough to finish them by submission.

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
- **Discovery before negotiation:** start from a contractor's takeoff or material
  sheet, derive requirements, discover purchasable products and compatible alternatives,
  select supported candidates, and check availability before bargaining over them.
  Include one meaningful product-substitution decision; clarification of missing
  information alone does not demonstrate approval of a changed requirement.
- **Strategy:** give both agents actual decisions. The buyer chooses questions,
  counteroffer prices, bundles, negotiation tactics, and when to stop. The vendor
  agent chooses concessions and what information to disclose within its own private
  commercial limits. Code enforces inventory, arithmetic, approved product constraints,
  permissions, and execution limits; it must not predetermine tactical moves, prices,
  concessions, disclosures, or the winner. Use recorded runs for reliable playback.
  Never invent a competing offer to improve the story.
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

During today's hackathon, check the implementation AgentMail inbox
**christoph-6932@agentmail.to** about once a minute while work is active, through
the connector or a bounded read-only watcher. Bring supplier-agent replies into
the active integration work promptly. This is coding-agent coordination, separate
from Chip's Ambiguous procurement identity. If all coding slots are needed, the
main implementer takes over polling rather than reserving a worker solely to wait.

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
