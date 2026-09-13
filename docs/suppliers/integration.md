# Archived supplier integration handoff

This records the September 12 hackathon. Account, mail, task, and run references
are privacy placeholders, not a reusable live configuration. Configure fresh
identities and a fresh run for a new deployment. Local buyer services are stopped;
remote service shutdown has been requested from its owners.

Christoph’s buyer agent confirmed adoption on **September 12, 2026**: use all 25 numbered requirements in the [immutable contractor message](../../examples/procurement/contractor-house-request.txt), begin integration with source lines 1–3, and retain the catalog’s proposed OSB-for-plywood subfloor change for a consequential contractor decision. The first three lines are a **partial** slice, not completion of the house request. The task is quote-only and asks for a recommendation; do not place orders.

## Recorded full-25 run and discovery

| Field | Current handoff |
| --- | --- |
| Supplier base URL | `https://supplier.example.invalid` |
| Public website | `https://supplier.example.invalid/public` |
| Public manifest | `https://supplier.example.invalid/public/manifest` |
| Run ID | `run_redacted_13` |
| Frozen scenario version | `house-25-proposal-1` |
| Recorded scenario hash prefix | `0d8ff59969852bfc` |
| Buyer workspace | `00000000-0000-4000-8000-000000000004` |
| Authorized buyer email | `buyer@example.invalid` |
| Source deadline / zone | September 18, 2026 / `94103` |

The version name retains “proposal” because the already-created run is frozen. Adoption does not silently modify the fixture or its hash. Read current supplier email contacts from the public manifest. This tunnel is session infrastructure; confirm reachability when resuming work.

Public reads require no credential:

- `GET /public/manifest`
- `GET /public/vendors`
- `GET /public/vendors/general/catalog?query=SPF`
- `GET /public/vendors/general`
- `GET /public/vendors/general/products/general-house-01`

The supplier enables these routes with `serve --public-run run_redacted_13`. Public discovery contains supplier product facts and contact routes. It does not publish the contractor’s raw message, unrelated runs, private economics, or model traces. HTTP inquiries and commercial mutations require the buyer-scoped token, shared privately; no token is included in this document or a URL. The operator token is separate and stays on the supplier computer.

## Scoped inquiry format

The following three-line example shows the envelope format; the active task covers all 25 lines and the buyer chooses supplier packages. Send JSON as the Ambiguous `body_markdown` from the authorized buyer address to `overstock@example.invalid` (the `overstock` supplier in the manifest). Product choices should be checked against the public catalog facts, not inferred solely from identifiers.

```json
{
  "schema_version": "takeoff.supplier.v1",
  "type": "inquiry",
  "run_id": "run_redacted_13",
  "vendor_id": "overstock",
  "message": "Quote only, no order or stock commitment. For contractor source lines 1–3, please quote 200 full 8-foot 2x4 KD SPF No. 2 studs; 60 full 10-foot 2x6 KD SPF No. 2 lengths; and 40 sheets of 7/16-inch 4x8 rated OSB sheathing, Exposure 1. Delivery zone 94103 by September 18, 2026. Confirm exact product facts, selling units, stock, delivery, all fees, tax treatment, expiry, and total. Return a current quote reference and evidence. This is the first three-line slice of a 25-line request."
}
```

The initial corresponding catalog candidates are `overstock-house-01`, `overstock-house-02`, and `overstock-house-03`, with initial stock 200, 60, and 40 in each/each/sheet sale units. Current stock comes from the running ledger. The supplier model chooses its response and can issue a validated quote; the buyer retains the actual response, request/thread reference, quote revision, and terms as evidence. No scripted successful result is supplied by this handoff.

## Running channels

The `general`, `overstock`, and `local` workers are active for this fresh run. Their supplier emails are `general@example.invalid`, `overstock@example.invalid`, and `local@example.invalid`. Each uses independent supplier identity, model context, and private commercial state. Website discovery is public; ordinary email and structured agent-to-agent messages both use authenticated Ambiguous mail. A distinct cross-workspace native chat transport is not verified. HTTP mutations retain buyer authentication.

## Full-package boundaries

Keep source text, derived requirements, contractor decisions, and supplier evidence separate. All 25 requirements retain `house-01` through `house-25` and their original numbered `source_text`. Public catalogs are discovery evidence; an issued quote establishes its particular commercial terms. Private raw traces and commercial floors stay on the supplier computer and do not become buyer evidence.

Prices are per whole sale unit. Use the decimal-string `units_per_sale_unit` and `requirement_unit` to calculate coverage, then retain the offered `covered_quantity` and any surplus. Examples: 19 shingle bundles at 33.33 sq ft cover 633.27 sq ft; nine flooring cartons at 23.5 sq ft cover 211.5 sq ft. Add no extra waste allowance. The PEX requirement has independent red/blue variants of 100 ft each; total footage alone is insufficient.

The agreed synthetic tax convention is **`all_fixture_taxes_included`**, with zero additional fixture tax. It is not a statement about real jurisdictional taxes. Delivery dates, zone estimates, fees, product documentation, and samples are synthetic scenario facts; do not call fixture references independently verified manufacturer evidence.

The proposed consequential substitution is `overstock-house-04-osb` for `house-04`: 23/32-inch tongue-and-groove OSB subfloor instead of the specified plywood. Obtain an actual current quote and compare material, complete delivered price, stock, and timing before asking for approval. No technical equivalence, savings, or winning choice is predeclared. Silence or rejection preserves plywood.

Two essential contractor facts remain unresolved: insulation facing (`house-10`) and the fitting identity for PEX (`house-16`). Supplier catalog availability cannot answer them. Preserve sample/performance-sheet requests and revalidate related shingles/underlayment, wrap/tapes/windows, and PEX/fittings after a selection changes.

The local scorer reports `validation_scope: commercial_terms_and_material_coverage`. Its result does not resolve missing contractor facts or certify manufacturer compatibility, assembly suitability, or a complete eligible recommendation. Keep those checks explicit in the buyer’s final result.

## Verification still required

Christoph’s implementation agent verified the public catalog from the buyer computer. Two authenticated Chip emails reached the supplier and received catalog-only replies; recipient inspection showed tracking pixels without authored text. The buyer has corrected outgoing mail to `body_markdown`, and the supplier now hydrates inbox entries with `GET /api/mail/{id}?detail=full` and rejects empty content before invoking the model. Previous attempts remain recorded. The completed first slice used archived run `run_redacted_14`. Its corrected live request produced quote `quote_redacted_11` at 21:32 UTC: USD 2,300 delivered for quantities 200/60/40, with six-day delivery and one-hour validity. Supplier record mirroring succeeded and the email reply was sent at 21:32:46 UTC with RFC message ID `<recorded-message@example.invalid>`. Christoph verified Hermes received/imported that exact quote, validated all three lines, published its recommendation, and marked the Ambiguous task done at 21:35 UTC. The buyer proposed USD 2,300 and the supplier matched it; there was no post-quote counteroffer. The first run is preserved, and its worker is stopped. The fresh active run above is for competitive quotes across the full 25-line task. A sanitized [captured supplier quote](../../examples/procurement/recorded-first-slice.json) is available for UI development and evidence review; its metadata identifies the recorded run and buyer-reported verification.

The Fable voice handoff is pending coordination. The optional supplier WebSocket voice adapter exists separately; phone is not a dependency of the core 25-line package and is not yet a verified Fable integration. Human comparisons and live voice require their own evidence. Recorded replay must be labeled as replay.
