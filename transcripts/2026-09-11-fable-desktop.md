# Claude desktop thread: Hackathon ideas and strategies (2026-09-11)



## HUMAN 1

please read up on the hackathon i am joining tomorrow. there should be an email explaining the rules and a web site with more information. i want to discuss great ideas and strategies


## EMAIL (confirmation, plain body)

Hi Christoph,

🚀 You’re officially in for Agents, Everywhere: Bots, Channels, &amp; More — Global Hackathon on September 12, 2026 from 10AM to 5PM PDT.

View QR Code

Heads up: This event is super popular! We've got everything locked in: venue, food, judges, and prizes. If your plans change, please cancel your RSVP now so someone else can join.

What to do now:

  Form or confirm your team in the portal

Open Hackathon Portal »

Manage Team / Entry »

View Handbook »

RSVP for: Christoph Schwerdtfeger [cancel]

Venue: 119 South Main St, 4th Floor, Seattle, WA 98104

Date/Time: September 12, 2026 from 10AM to 5PM PDT

Thanks to our sponsors: OpenAI, CopilotKit, OpenRouter, Exa, Auth0, Ambiguous AI, Trigger.dev, Mozilla, and Google Cloud Run

Add to Apple Wallet

+ Google Calendar

+ Apple Calendar

Download .ics file


## ASSISTANT 1

**The brief**

Agents, Everywhere: AI Tinkerers' global build day, OpenAI as marquee sponsor. Tomorrow 10:00 to 17:00 at 119 South Main St, 4th floor. You're confirmed and registered solo. Seattle shows about 91 attending with 7 teams already formed in the portal; globally it's 49 cities and roughly 5,000 registered. Starter repo isn't posted yet; check the portal in the morning.

Theme: build an agent for a place people already work, talk, or live, and make it meaningfully more useful because of that context.

Schedule: doors 10:00, global broadcast 10:30, team formation 11:00 to 11:15, build 11:15 to 15:30, then submissions. Hard deadline 17:00 PDT. That's 4h15m of build.

Submission: title, written description, public GitHub repo, two-minute video, social post tagging sponsors. Must be net-new and built during the event; templates, libraries and starter code are allowed, and you should be able to say which parts were built on the day.

Judging is global and remote, four criteria scored 1 to 5: functionality, innovation and theme alignment, technical execution and integration, usefulness and agentic experience. The 5 on innovation requires a pattern whose central value "could not be reproduced in a standalone chatbox"; the 5 on technical execution calls out orchestration and failure handling.

Prizes: 1st $10k OpenAI credits, a Mac mini per member, $1k Exa. 2nd $5k credits and Ray-Ban Meta glasses. 3rd $2.5k and a LOOI robot. Best Use of Ambiguous AI: one NVIDIA DGX Spark. Best Use of CopilotKit: AirPods Max per member.

**Strategic read**

1. Prize math. Likely 1,000+ submissions worldwide judged from video plus description plus repo. Top 3 is a lottery even for excellent work. The Ambiguous AI category (a DGX Spark, roughly $4k, and the one prize you'd actually use) will have a tiny competitor pool: obscure sponsor, most teams default to Slack or CopilotKit. Highest EV target by a wide margin. Ambiguous's pitch is an AI coworker with its own identity working inside Mail, Chat, Sheets and CRM, which is the theme restated and your Mayfly thesis in miniature.

2. The video is the product. Nobody runs code at that volume. Reserve 60 minutes for video, description and post. First ten seconds show the agent acting in its environment, no intro. Show one failure case handled explicitly and one human approval interrupt; both criteria pay for it. Last round's Seattle entries read as stack name-drops, and one shipped its LLM's editing notes inside the description. The bar is beatable with a clean working demo and a description a human wrote.

3. Environment must be essential. What scores 4 to 5: the agent is triggered by the environment (a mention, inbound mail, a camera frame), holds state across third parties or time, and acts where the work is. Request-response in a new skin scores 2.

4. Free rubric points: OpenAI primary with OpenRouter fallback (failure handling, two tags), Trigger.dev for durable waits and retries (orchestration, tag), Exa for any lookup.

5. Team. Solo is viable for a narrow scope, but code plus video in 4h15 is brutal. Arrive at 10:00 with a one-sentence pitch and recruit one person to own demo, video and writing. People join whoever has a plan.

**Two directions**

A, my lean: vendor quote loop inside Ambiguous AI. Contractor drops a takeoff into a Sheet and @mentions the coworker; it emails RFQs to vendors, waits durably, parses replies including partial and ambiguous ones, asks the contractor only for real decisions (substitutions, lead-time tradeoffs), and fills a comparison sheet. A chatbox can't hold open loops with third parties. It's the defensible piece from your GC discovery call, so the output doubles as the transparent demo you wanted for that channel. Demo trick: a second agent plays three vendors, one deliberately messy. Risk: I don't know how mature Ambiguous's MCP is. Sign up tonight and confirm mail send and receive work end to end; if not, same idea on Gmail and forgo the category prize. One caveat: public repo plus post exposes a Mayfly hypothesis. Early and generic enough that I wouldn't worry.

B: agent in the room, camera-driven. Phone camera on a workbench; agent detects state (missing part, completed step) and acts in software (order, work-order update). Physical-world entries will be rare and memorable, and you have the CV depth to land it in four hours where others can't. Weaker usefulness story unless the workflow is crisp; higher staging risk.

**Tonight**: accounts and working keys for OpenAI, OpenRouter, Ambiguous AI with MCP, Trigger.dev, Exa. Read Ambiguous and Trigger docs. Storyboard the two minutes. Draft the social post. No shippable code.

Two things that change the plan: is the objective prize EV, a Mayfly artifact, or both? And solo, or willing to recruit on site?


## HUMAN 2

The goal honestly is just to have a bit of fun. Like I don't care about winning the prize. I just wanted to try this once and see how it feels to go there. Maybe just, like, work with a few people and, like, have fun with that. So, like, yeah, I definitely would want to convert somebody into, like, a recruiter, like find somebody to work with. That would be fun. I like your takeoff idea. I think that's very demoable, especially if you have, like, the agents really negotiating and playing the different vendors against each other or something, right? That can be, like, a cool way to just enjoy the, or, like, to give the whole thing really, like, a feeling of, okay, here is, like, an intelligence working for me. It's not just, like, information gathering. It's doing more than that, and so, like, you end up with the perfect sheet and you end up with better prices.


## ASSISTANT 2

Fun changes the plan in a useful way: drop the prize engineering (sponsor tags, category targeting) and optimize for a demo that's satisfying to watch come alive and a scope that three strangers can split in minutes.

**What makes it feel like an intelligence working for you**

Three visible behaviors, and the demo should be built around exactly these moments: initiative (it sends the RFQs and runs the rounds without being driven), leverage (it quotes vendor A's number to vendor B and asks them to beat it, asks for bundle discounts, threatens to split the award), and judgment (it comes back to you only with the two decisions that need a human, like a substitution or taking a longer lead time for a bigger discount). Information gathering is round one. Rounds two and three are where it stops looking like a form-filler.

**The one design decision that determines whether it's real or a puppet show**

If the vendor agents are just LLMs with a persona, they'll cave to any counter and the numbers are theater. Give each vendor private state the buyer can't see: a cost floor per line item, stock levels, lead times, a bundle-discount rule, a match-competitor threshold, a temperament. Enforce it in code, not in the prompt: every quoted price goes through a validator against the floor, out-of-stock items can't be quoted, and the LLM only writes the email around numbers the simulator produced. Now the negotiation has actual structure and the buyer agent has to extract information through the conversation, which is the interesting part for you.

The payoff: because you simulate the vendors, you know the oracle optimum (sum of floors across the best vendor per line). Scoreboard at the end: first quotes vs. final sheet vs. oracle. "Captured 74% of available surplus" is a far better closing line than "here's a sheet."

**Scope that fits 4h15**

Three vendors, eight line items, three rounds. Vendor side simulated. Contractor side on real email if it's cheap for whoever's on it (Gmail API), otherwise a fake inbox UI. Don't do real email on both sides. The live view is a split screen: threads streaming on the left, the comparison sheet updating on the right. That split screen is the video.

One touch worth the time: the contractor answers a decision in plain language ("take longer lead time on rebar if it saves more than 8%") and the agent treats it as policy for the remaining rounds.

**Team split**

The idea decomposes cleanly, which is why it's good for strangers:

1. Vendor simulator: state schema, validator, persona prompts, reply generation.
2. Negotiator: round logic, leverage tactics, split-award threats, escalation to human, final award.
3. Surface and video: inbox/sheet UI, screen capture, the two-minute narrative.

Agree on two schemas at 11:00 and everyone can work alone until 14:30: a message (thread id, from, to, subject, body, structured quote lines) and vendor state. Integration at 14:30, video at 15:00.

**Recruiting**

Pitch during food, not in the 15-minute slot. One sentence: "An agent that takes your bill of materials, emails vendors, and plays them against each other until you have the best sheet. The vendors are agents with secret cost floors, so we can score how much it actually saved." Then ask what they want to touch. Someone who's excited about the vendor personas is a good sign; someone who wants to own the video is gold.

Tonight: sketch the two schemas and the vendor state on paper, and decide your negotiation tactics list so the negotiator prompt isn't invented under time pressure. That's design, not code.


## HUMAN 3

put on your creative genius hat. what are some great additions to this sketch that make it really mind blowing and impressive and that are feasible in 4 hours of work?


## ASSISTANT 3

The multiplier for everything below: build the whole thing as a single event log (message sent, quote received, tactic chosen, decision escalated, award made) that the UI subscribes to. Then every visualization is a 20-minute view over the same stream, and the video practically edits itself.

**Ranked by wow per hour**

1. **The reveal** (30 min). Vendor floors stay hidden throughout, then flip at the end like hole cards. Chart shows first quote, final price, and floor per line. Closing line: "captured 74% of available surplus, left $312 on the table with vendor B." Cheapest big moment on the list.

2. **Traps the agent catches** (30 min, mostly prompts plus one validator). Seed two: vendor C quotes rebar per foot when the RFQ was per 20-foot stick, and vendor A's chatty reply mentions they're overstocked on lumber. The negotiator flags the unit mismatch before it poisons the sheet and squeezes A on lumber specifically. Perception, not process, is what makes people say "it noticed."

3. **Strategy ticker** (20 min). A side panel where the negotiator narrates its plan before each round: "B is 12% high on rebar but fastest on delivery; using A's price as leverage, holding lead time as a concession." Intelligence is invisible unless you show the intent.

4. **Decisions by text message** (40 min, Twilio). The two escalations arrive on your phone: "C offers 9% off lumber for a 3-week lead time. Reply Y, N, or a rule." You reply "Y if it saves more than $400" and the agent applies it as policy. Phone buzzing in the video is the theme made physical.

5. **Sealed-bid final round** (20 min of round logic). After two open rounds the agent announces best-and-final to all vendors by 2:15. Vendors respond against their floors. Real procurement mechanism, and it creates a clock.

6. **A real award solver** (45 min, yours). Assignment across vendors with bundle discounts, minimum-vendor and no-split constraints from the contractor's rules. It also makes the split threat credible: "my optimizer says splitting lands at $X; beat that as a bundle and you get everything."

7. **Market grounding** (30 min, Exa). Negotiator pulls lumber and steel price moves and cites them: "lumber futures are down 6% this month; your quote should reflect that." Turns the agent from bargainer into informed buyer.

8. **A human vendor in the room** (30 min if over Slack DM, more for email). One teammate plays vendor B live from their phone during show-and-tell and gets out-negotiated in front of everyone. For the room this beats any simulation; for the video, one real thread among simulated ones.

9. **Price trajectory chart** (30 min, recharts). Per line item, per vendor, over rounds, converging live. Pairs with the reveal.

10. **Vendor playbook that persists** (20 min). At the end the agent writes what it learned: who matches, who bluffs, who folds under a walk-away. Run two: it uses the playbook and converges in fewer rounds. Learning across runs is rare in demos.

11. **Purchase orders on arrival** (30 min). Three PDFs, one per vendor, in the contractor's inbox at the end. The ending has to be a deliverable, not a chart.

**Stretch, high risk, highest ceiling**

12. **Photo to takeoff** (45 min, vision). Opening beat: contractor photographs a plan page, the BoM appears, the emails go out. The story starts in the physical world.

13. **One vendor only takes calls** (60 to 90 min, OpenAI Realtime, browser audio). The agent switches channel and negotiates by voice, transcript streaming. If it works it's the most memorable 20 seconds of the day; if it doesn't, it eats an hour. Only if a teammate has done Realtime before.

**The two-minute cut** if you land 1 through 5: emails going out unprompted, ticker announcing leverage, the unit trap caught, your phone buzzing and you texting a rule, best-and-final clock, the reveal. Everything else is bonus.


## HUMAN 4

1. we are showing a proactive agent, but how are we answering the challenge? i think it'd be great to start not-in-a-chat

The challenge
Most agents still wait inside a separate chat window. This build day starts from a different premise: the most useful agents will show up inside the tools, channels, devices, and environments where people already have work to do.
Build a working agent that belongs somewhere new.
Your project might live:

* At work: Slack, Teams, email, documents, calendars, tickets, support, or live collaboration
* In your pocket: messaging, mobile, notifications, and short asynchronous moments
* On the web: browsers and software where an agent can research, navigate, transact, or take action
* In the room: voice, vision, wearables, robotics, and other physical-world interfaces

These are examples, not separate tracks. Every team around the world enters the same global submission pool.

2. how can we scale this to 1,2,3,4 people participating (and remember, i don't know the people, so we have to assume some of them are really useless. what could i build alone?
3. do you see any path to force this into this ambiguous tool? as you pointed out, the dgx spark would be the only actually interesting price
4. i don't know how many tokens they give you for this event, but many of the features seem incredibly parallelizable. how far can we push that? 
5. do you think i should register a team with this idea today?


## ASSISTANT 4

**1. Answering the challenge without a chat**

The contractor never opens an app. Three environments in one flow:

Trigger from the room: a photo of the plan page or a takeoff spreadsheet, sent by email or MMS to the agent's own address. Vision extracts the BoM. The agent wakes up from an inbound message, not a form.

Home at work: the negotiation lives in email threads under the agent's identity (procurement@yourco). Vendors have always been negotiated in email between humans; the agent joins as a participant with its own address. This is also the argument for why the context matters: thread history, attachments, vendor tone, and the contractor's replies become policy.

Interrupts in the pocket: two escalations by SMS, answered in plain language. Deliverable back in email: the sheet and three POs.

The live dashboard becomes observability, not product. Frame it as "the agent's desk," what's happening behind the inbox. Video opens with a phone clip on a job site, then cuts to the inbox. Rubric aside, that opening is what "not in a chat" looks like.

**2. Scaling from 1 to 4, assuming dead weight**

Solo core, about 4 hours: vendor simulator with floors and validator (45), negotiator with three rounds, tactics and escalation (75), event log plus minimal view (30), inbound IMAP poll and outbound SMTP on a Gmail app password (30), decisions by email reply instead of SMS (same plumbing), video and write-up (60). The reveal and ticker fall out of the event log. That's a complete story you can ship alone.

Add-ons are additive and isolated behind file or JSON interfaces, and the core never depends on them:

Person 2: demo production. Storyboard, screen capture, narration, description, social post. Highest value per competence unit, and a non-engineer can do it well. If they vanish, you do it in the last hour as planned.

Person 3: vendor content. Three personalities, the unit trap, the overstock leak, reply style. Pure prompt work behind the vendor interface. Can't break anything.

Person 4: one stretch feature owned end to end: Twilio SMS, PDF POs, Exa market grounding, or the voice vendor if they've done Realtime before.

Triage rule: 45-minute checkpoint on the first task. Nothing by noon, they move to testing, B-roll and writing. You hold the critical path.

**3. The Ambiguous path**

The negotiator becomes an Ambiguous coworker. Contractor @mentions it in a comment on the takeoff Sheet or emails it in Ambiguous Mail; it sends RFQs from its own identity, tracks vendors in CRM, escalates in Chat, writes the final Sheet. That's their pitch verbatim, and it would use four of their apps.

The important framing: it isn't an extra feature, it's a swap of the human-facing plumbing. If their MCP works, it replaces Gmail and Twilio and saves time. If it doesn't, it kills your afternoon. So it's a tonight decision: sign up, connect the MCP, test read sheet, write sheet, send mail, read inbox, post chat. Three of five working in 45 minutes: adopt it. Otherwise drop it without regret. Check the portal in the morning for a sponsor rep or credits.

**4. Parallelism and tokens**

Tokens aren't the constraint. One run is roughly 40 to 60 calls, maybe 100k tokens; fifty dev runs is a few dollars. Rate limits are the real constraint on a fresh org, so route overflow through OpenRouter and use a mini model for vendor replies, frontier only for the negotiator. Rounds should take seconds; put a timeout with a default policy on human decisions so the demo never stalls.

Runtime parallelism worth doing: vendors negotiated concurrently per round, and the tournament. Since the simulator is seeded, run three negotiator strategies against five seeds each, fifteen negotiations in parallel, and show the surplus distribution: "aggressive wins 12 of 15 and loses badly when B walks." Two million tokens, one chart, and it turns a demo into an experiment.

Build-time parallelism is the bigger lever and it's your own thesis in miniature: you plus three or four coding agents in separate worktrees, one per module (vendor_sim, negotiator, award_solver, channels, dashboard), each with a contract and a fixture test, you integrating. This works only if the contracts exist before the clock starts. Tonight: module specs and schemas as design docs, which the rules explicitly allow. Code tomorrow.

**5. Register a team today**

Yes. It costs nothing, nothing is binding, and it fixes half of the stranger problem: people who join a listed team self-select for the idea. It also gives you a page to point to at 10:00 and signals initiative, which draws stronger people. Post the same pitch on the portal message board. Blurb: the one-sentence idea, "Christoph holds the core, add-ons are separable," and the three roles you want: demo owner, vendor-persona writer, one stretch feature owner.


## HUMAN 5

yeah, i meant build time parallelism. please go for the big scope you outlined above. how much of that can we parallelize. assume we use something like hermes as a backend with telegram integration (also gives us voice transcription and tts, we just need to enter keys) and we spec everything well before we get started. how parallel can the build be?


## ASSISTANT 5

Hermes changes the shape in your favor: it already is the contractor-facing agent. Hermes runs as a Telegram bot that takes text, voice memos (auto-transcribed), images and file attachments, and can reply with voice bubbles, and it's extended by dropping Python files with custom tools into its plugins directory. Add its persistent memory and you get the "playbook that persists" nearly free. So the architecture that maximizes parallelism is: Hermes is the thin channel layer, the negotiation engine is a separate service Hermes calls as a tool, and every impressive feature lives in the engine behind a frozen contract.

**Architecture in one line**

Telegram photo or file → Hermes (vision → BoM, calls `start_negotiation`) → engine runs vendors, rounds, solver, event log → escalations and final sheet pushed back to Telegram via Hermes's outbound send → dashboard subscribes to the engine's event stream for the audience.

**Modules and dependencies**

M0 Contracts: pydantic schemas (LineItem, VendorState with floors/stock/lead/personality/bundle rules, Message with structured quote lines, Event union, Decision, Award, RunConfig with seed), fixtures (one BoM, three vendors, a recorded event log), an in-memory bus, and a harness (`make e2e`). Everything compiles against this. Fully specified tonight, coded in 15 minutes tomorrow, then frozen.

Wave 1, all depend only on M0, fully parallel:
- M1 Vendor simulator: `reply(thread_state) → Message`, validator against floors, personas, the unit trap and overstock leak. Mini model.
- M2 Negotiator: round scheduler, tactics, leverage, walk-away, best-and-final, escalation hooks, playbook writer. Tested against scripted vendor replies from fixtures, so it never waits on M1.
- M3 Award solver: quotes + constraints + bundle rules → allocation and the credible split-threat number. With 3 vendors and 8 items it's 6,561 combinations; brute force, no solver library.
- M5 Engine API: FastAPI, five endpoints plus SSE event stream, run registry, decision queue with timeout defaults.
- M6 Dashboard: built entirely against the recorded event fixture, zero backend needed. Threads, ticker, trajectory chart, reveal, tournament view.
- M7 Market grounding: Exa → per-item price notes injected into negotiator prompts.
- M8 PO generator: Award → three PDFs. Pure function.

Wave 2, needs a live engine:
- M4 Hermes plugin: tools `start_negotiation`, `status`, `answer_decision`; photo-to-BoM via vision; outbound delivery of escalations and results; TTS summaries as voice bubbles; write the playbook into Hermes memory at the end.
- M9 Tournament runner: N strategies × seeds concurrently, aggregate to chart data.
- Integration: M1+M2+M3+M5 end to end in the harness, then M6 on live SSE.

Wave 3: trap tuning, demo seed locked for determinism, polish. Stretch: a human vendor over a second Telegram chat (same gateway), voice-flavored vendor.

M12 Demo production is human-only and can start at 11:15 with the storyboard.

**How parallel**

Dependency width after M0 is eight independent streams. The binding constraint isn't agents or tokens, it's your review and integration bandwidth. One person can supervise about six agent sessions if each has a one-page spec, fixture tests, and a definition of done, at roughly ten minutes of review per checkpoint. Beyond six you accumulate integration debt faster than you retire it. With one competent human as second integrator, eight to ten.

Timeline: 11:15 M0 coded and frozen (15 min). 11:30 to 12:45 Wave 1, six agents in separate worktrees, one module per directory, PRs into main. 12:45 to 13:45 integration plus Wave 2. 13:45 to 14:30 Wave 3. 14:30 to 15:30 recording and write-up. Critical path: M0 → M2 → integration → recording. The negotiator is the hardest module; give it the best model and your own attention, and start it first.

**Human roles in this plan**

Agents take plumbing; humans take the tactile parts, which is also where the fun is: M4 (Hermes and Telegram, tested live on a phone), vendor personas and traps (writing, not code), and demo production. A strong stranger owns M4 end to end. A weak one writes vendor personas from your template and can't break anything.

**Tonight is the project**

Two to three hours: M0 schemas and fixtures on paper, the engine API (endpoints and event types), the tactics list and round structure, three vendor sheets with numeric floors, per-module one-page specs with "done when" tests, the storyboard, model per role, repo layout, and the agent prompt template ("implement M2 against contracts/, fixtures in tests/, done when `make test-m2` passes, don't touch other dirs"). These are design docs and prompts, which the rules allow.

Also tonight, setup only: install Hermes, create the Telegram bot, confirm a hello-world plugin tool registers and that an external process can push a message to your chat through Hermes. If either fails, fall back to a plain python-telegram-bot script for M4; the engine is unaffected.

Two things to keep in mind. Coding-agent tokens come from your own subscription, not event credits; event credits go to runtime. And lock the demo seed early: vendors at temperature 0 where possible, so the recording matches the rehearsal.
