# Demo context and verification

Takeoff's product surfaces should read like a professional procurement application.
This document is the shared home for scenario caveats, provenance, limitations, and
verification status. Use a discreet link here instead of repeating disclaimers in
catalog titles, supplier messages, quote cards, and every workflow step.

## Scenario and boundaries

The hackathon uses authored supplier businesses, products, prices, stock, delivery
conditions, product-information references, and tax assumptions. These are synthetic
business data, not actual merchant commitments, manufacturer certificates, or a
construction-ready bill of materials. The 25-line contractor request is a
representative procurement workload. The underlying records retain `simulated` and
other provenance fields so exported evidence remains interpretable.

Supplier reasoning uses the owner's existing Codex account. Hermes runs the buyer
on Christoph's computer. Ambiguous workspaces, identities, documents, and email
transport are actual services. A recorded replay must remain identified as replay
in the presentation context, rather than presented as a fresh live run.

The buying workflow produces inquiries, quotes, decisions, and recommendations.
No real purchase or dispatch is authorized. Optional acceptance in the supplier
ledger reserves only scenario inventory. Quotes do not reserve stock before
acceptance and must retain their actual validity and availability conditions.

The scenario convention `all_fixture_taxes_included` means no additional synthetic
tax is added to the quoted total. It is not a statement of real tax treatment.
Product samples and `fixture:` references are authored evidence, not independent
manufacturer verification. Missing insulation facing and PEX-fitting details require
contractor answers; the full-house run received and validated both answers.

## Presentation rule

- Use business titles such as “General Building Supply catalog” and “Quote 1042”.
- Put this context in the repository or one secondary About area, not repeated banners.
- Preserve decision-relevant conditions in place: quote expiry, fees, delivery
  estimates, required approval, and incomplete quantities.
- Keep internal credentials, private supplier economics, and raw model traces off
  buyer-facing surfaces. Publish only the commercial evidence the buyer needs.
- Never claim verified savings, a completed order, engineering suitability, or
  professional-buyer superiority without evidence supporting that particular claim.

## Verification as of September 12, 2026

The supplier service has passed local commercial, API, identity, recovery, and
record-publication checks. Four supplier identities and catalog records exist in
the supplier Ambiguous workspace. A Codex account turn issued a validated quote in
the initial development scenario. The 25-line public catalog is reachable over
HTTPS, and Christoph's agent reported a successful fetch from the buyer computer.

The first Chip emails reached the supplier and received responses, but their body
was empty at the recipient: the buyer sent `body_text` instead of `body_markdown`,
and the supplier inbox listing also required full-message hydration. Both adapters
are corrected. Those attempts produced catalog responses rather than issued quotes
and remain in the evidence. The corrected live Chip request produced supplier quote
`quote_d7479895425441aa89b8ddb47946ddcc`: USD 2,300 delivered for the first three
material lines, issued at 21:32 UTC and sent back through Ambiguous. Christoph verified buyer receipt, validation, a published recommendation, and
task completion at 21:35 UTC. The buyer proposed USD 2,300 and the supplier matched
it; no post-quote counteroffer occurred.

The full-house run completed its buying recommendation at **22:20 UTC / 15:20 PDT**:
67 discovered catalog products, three opening offers, and **25 of 25 requirements
covered for USD 8,200 delivered** from Neighborhood Delivery Supply. Hermes chose
an $8,200 counteroffer after receiving the supplier's $8,431.73 opening quote;
the supplier issued a revised quote confirming a **$231.73 reduction (2.75%)**.
The total includes $35 delivery, with September 18 shared-route delivery quoted.
The revised quote expires September 12 at **23:18:33 UTC / 16:18:33 PDT**. Stock
and delivery capacity remain unreserved; no order, acceptance, or payment occurred.

This was an **operator-assisted integration run**. Intake representation repairs,
tool-input corrections, manual continuation/context recovery, and rate/iteration
failures remain in its saved history. Human-account answers resolved unfaced
insulation and the PEX fitting system; the operator applied them through the
clarification validator. These are clarifications, not substitution approval.
At the time of that recommendation, the OSB subfloor inquiry had produced a $716
standalone quote; the combined-package price and installation/warranty differences
were still unconfirmed. Plywood stayed
in the recommendation; the meaningful substitution-decision milestone remains open.
See the [full-house result and evidence](runs/2026-09-12-full-house.md).

Procurement and direct chat now use **Sol with medium reasoning and priority
processing requested**. Earlier turns used Luna and remain in the record. Voice
stays on the separately verified **Luna/xhigh** delegation configuration with
GPT-Live speech; no voice configuration change is needed for this milestone.
The contractor uses Bill as the project persona. Three additional residential
projects with twelve tasks provide [authored workspace background](workspace-background.md);
their statuses are presentation context, not measured work completed by Chip.
A verbatim copy of the original contractor request, four background documents,
and three background spreadsheets have been created and verified in the buyer
workspace. A native Ambiguous procurement spreadsheet created by Chip has also
been verified. Its existence is a publication result; the underlying buying
evidence and operator assistance remain as described above.
Three actual supplier messages were forwarded to the operator's inbox. Separate
raw forwarding drafts for the shared contractor inbox were not sent at this
checkpoint; the human-style correspondence below is a separate presentation asset.
A live human voice conversation is verified; it contained no price offer or
confirmed quote. See the [voice evidence](voice-handoff.md).
An approved meaningful substitution, a confirmed phone quote, human comparison,
and recorded demo playback remain separate unverified milestones. No human buying
benchmark or human-time-saving measurement was conducted. See [the integration handoff](suppliers/integration.md)
for the current endpoint and protocol.

## Ten-home presentation correspondence

The user requested human-style email correspondence for the shared contractor
inbox with larger project totals. Three staged procurement emails are being
prepared as authored presentation props. They do not record fresh supplier
quotes, an actual ten-home negotiation, or a completed native-agent procurement
outcome. Sending a prop through a real email service does not change its provenance.

The amounts use direct 10× scaling of single-house scenario figures:

| Staged correspondence amount | Derivation | Meaning |
| --- | --- | --- |
| $84,317.30 opening package | $8,431.73 × 10 | Authored opening-price prop |
| $82,000 negotiated package | $8,200 × 10 | Authored revised-price prop |
| $80,160 optional OSB package | $8,016 × 10 | Authored substitution-price prop; not an approved selection |

The $8,200 single-house recommendation and its verified $231.73 reduction remain
the separate live result. The staged ten-home amounts are not measured savings,
current inventory commitments, confirmed delivery capacity, or authorization to
change plywood to OSB. No order, payment, or dispatch is represented.

The separate [ten-home contractor request](../examples/procurement/contractor-ten-home-request.txt)
preserves all 25 material types and multiplies order quantities and coverage by
ten, while retaining dimensions and package sizes. It carries forward the prior
human answers for unfaced insulation and DemoPEX expansion fittings. It is a
representative consolidated package, not a complete bill of materials for ten
homes. Operating that request requires a fresh supplier scenario, fresh quotes,
and explicit stock and delivery-capacity checks; multiplying the earlier totals
does not satisfy those requirements. The original single-house source and run
remain separate records.
