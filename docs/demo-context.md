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
manufacturer verification. Missing insulation facing and PEX-fitting details remain
contractor questions; available stock cannot answer them.

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
and remain in the evidence. The full task →
remote quote → contractor decision → recommendation path is still under verification.
Full 25-line completion, live phone operation, human comparison, and recorded demo
playback are separate milestones. See [the integration handoff](suppliers/integration.md)
for the current endpoint and protocol.
