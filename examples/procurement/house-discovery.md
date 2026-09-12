# Proposed representative house-material request

**Scenario proposal only.** The full-demo target is 25 distinct requirements across framing, sheet goods, roof/weatherproofing, insulation/wall finish, rough-in, doors/windows, and interior finish. These are invented contractor specifications and quantities for a procurement demonstration, not a complete house bill of materials, a takeoff from plans, or construction advice. They replace the old painting-only proposal and do not inherit any UX fixture scenario. Tapan owns actual catalogs, public product facts, stock, offers, and commercial opportunities; this document asserts no available product or price.

## Contractor input and scope

[`contractor-house-request.txt`](contractor-house-request.txt) is the unnormalized source message. Give Chip this message and the actual supplier surfaces without preassigning products, suppliers, or a winner. The table below is a design guide, not a cleaned requirement sheet supplied in place of the contractor message. Loading this fixture alone does not authorize supplier contact.

The buyer and vendor implementation agents jointly choose the exact adopted materials, the first live slice, and a catalog-supported product substitution. The 25 source lines are a concrete starting proposal for that joint work. Keep 25 representative requirements as the full-demo target; expand only if the catalog and remaining time support it. A smaller integration slice remains useful but must be labeled partial. The working-demo deadline is **September 12, 2026 at 16:00 America/Los_Angeles**, with submission at **16:30**; avoid expanding infrastructure to accommodate optional scenario complexity.

The delivery zone and Sept 18 material deadline are synthetic task constraints, separate from the hackathon deadlines. Request an address or other delivery detail only when needed for a firm quote; a zone-based estimate stays labeled as an estimate. Product samples and performance sheets are evidence to inspect, not automatic extra intake questions. Matching supplied product specifications does not establish project engineering, assembly suitability, or code compliance.

## What the buyer does with each line

| Line / intent | Ambiguity or mapping work | Supplier evidence needed | Action / contractor-question trigger |
|---|---|---|---|
| 1 — wall framing stock | Decode KD SPF No. 2; distinguish full 8-ft stock from pre-cut studs. | Size, listed length, species grouping, grade, drying designation, sale count. | Match all stated facts; a similar product title is insufficient. |
| 2 — larger framing stock | Different dimensions and length from line 1; separate requirement and quantity. | Same lumber facts, with 2x6 and 10-ft length. | Compare 60 pieces in whole sale units; do not pool quantities with line 1. |
| 3 — OSB sheathing | Sheet packs and ratings may be absent from the listing title. | Dimensions, thickness, panel designation, exposure classification, pack count. | Ask supplier for missing product facts; preserve 40-sheet need. |
| 4 — plywood subfloor | Nominal shorthand and tongue-and-groove details must match. | Listed thickness, dimensions, plywood construction, edge profile, subfloor designation, exposure class. | Verify the specified plywood rather than treating any wood panel as interchangeable. |
| 5 — shingles | Bundle prices and coverage vary; color names are not uniform. | Shingle type, documented bundle coverage, charcoal sample, whole-pack stock. | Cover 600 sq ft using the quoted product's facts; show surplus and sample. |
| 6 — roof underlayment | Installed coverage differs from an unsupported gross-roll assumption; related to line 5. | Synthetic material, stated installed coverage, documented use with the selected shingles and any relevant conditions. | Obtain sufficient full rolls and record product-use evidence; missing conditions trigger supplier follow-up. |
| 7 — housewrap | Category term must map to stated purpose and dimensions. | WRB product purpose, roll width/length, pack count. | Match 9x100 rolls; do not imply a certified complete wall assembly. |
| 8 — seam tape | A tape labeled for housewrap is not automatically approved for the selected wrap. | Dimensions, roll count, wrap-maker documentation for line 7. | Resolve from supplier/manufacturer facts and recheck if line 7 changes. |
| 9 — window flashing tape | Cross-product facts tie this line to wrap and vinyl windows. | Dimensions, self-adhered type, documented compatibility and applicable installation conditions. | Ask supplier for evidence relating to lines 7 and 21; do not invent compatibility. |
| 10 — fiberglass batts | Coverage maps to bags; **facing is unspecified**. | R-value, material, width, facing, coverage per bag, stock. | Check task records, then ask contractor for required facing if absent. Normalize bags after the answer. |
| 11 — drywall | “Half-inch” / “regular” must identify the actual board. | Board type, thickness, dimensions, sheets per sale unit. | Match 60 regular sheets; a different board type is a proposed change. |
| 12 — tile backer | Product category and use must be explicit, not inferred from sheet size. | Cement board construction, thickness, dimensions, manufacturer-described wall-tile use. | Match 12 boards from documented product facts. |
| 13 — joint compound | Pail prices can hide size or compound-type differences. | Premixed all-purpose designation, US-gallon volume, container count. | Compare enough whole containers for 18 US gal; retain original four-pail request and show alternate packing. |
| 14 — joint tape | Paper tape is a material constraint, not just a category synonym. | Paper construction, roll length and count. | Obtain 1,000 ft in whole sale packs; mesh is not an automatic match. |
| 15 — drywall screws | Box count can hide different weights or screw specifications. | Diameter designation, length, thread, coating, net package weight. | Obtain at least 10 lb meeting the stated facts and show permitted surplus. |
| 16 — water tubing | Coil/color needs are explicit; **“our fittings” names no system**. | Tubing identification, length/color, manufacturer-declared connection compatibility. | Check task records, then ask for fitting identity if missing; verify before recommending. |
| 17 — drain/waste/vent pipe | Listing must establish material, designation, ends and piece length. | PVC, Schedule 40 DWV designation, diameter, plain ends, 10-ft pieces and sale count. | Match eight lengths; 80 aggregate feet of arbitrary cut pieces is not the stated request. |
| 18 — cable | Conductor shorthand and roll quantity need exact matching. | Cable designation, copper conductors, size/count, ground, reel length. | Match one 250-ft roll; do not independently infer circuit suitability. |
| 19 — electrical boxes | Similar box titles can conceal volume or mounting differences. | Gang count, plastic material, new-work/nail-on configuration, volume, sale count. | Match 20 boxes using specifications rather than pictures alone. |
| 20 — interior doors | “Slab” excludes a bundled prehung unit; prep and dimensions matter. | Core, surface/primer, dimensions, absence of bores/mortises, unit count. | Match three stated slabs; no handing question is needed for these unprepared slabs. |
| 21 — fixed windows | Actual unit size is specified, so a nominal size label cannot settle the match. | Actual dimensions, fixed operation, frame/color, fin, glazing description, performance sheet. | Verify two units and retain performance evidence; no invented building-performance requirements. |
| 22 — baseboard | Linear-foot need must map to whole stock lengths; material/profile are constraints. | MDF, primer, square-edge profile, dimensions, available lengths and sale units. | Obtain at least 160 ft using lengths of 8 ft or more and show cuts-independent excess. |
| 23 — flooring | Carton coverage differs; finish names vary; overall thickness and wear layer are distinct. | Vinyl/click-lock facts, overall thickness, wear layer, carton coverage, light-oak sample. | Cover 200 sq ft in full cartons; show sample and surplus. Different stated attributes need approval. |
| 24 — wall paint | Compare volume across cans/pails; factory white is not an unfinished tint base. | Interior wall use, water-based type, eggshell sheen, factory color, container volume. | Compare allowed pack combinations totaling at least 15 US gal; show surplus. |
| 25 — trim enamel | Distinct finish-use requirement from line 24, not extra wall-paint volume. | Interior trim enamel use, water-based type, semi-gloss sheen, factory white, container volume. | Obtain two US gal in whole packs; do not merge into the eggshell wall-paint line. |

Package quantity changes preserve the specified product and each line's practical form constraints. For example, flooring cartons can cover more than the requested area, while pipe still needs the specified piece lengths. Use documented contents and charge for whole sale units. The source already includes the contractor's coverage allowance; add no invented waste factor.

## Clarifications and consequential product choice

1. **Missing contractor fact: insulation facing (line 10).** Resolve from existing task records first. If absent, ask one concise question while other searches continue. Stock cannot decide the wall requirement.
2. **Missing contractor fact: PEX fitting system (line 16).** Request the fitting identity or label if existing task context does not provide it. Validate product compatibility against evidence; avoid a broad plumbing interview. The plan stays partial if the essential fact remains unavailable.
3. **Required demonstration: meaningful product substitution.** The implementation agents jointly select a real catalog opportunity that changes a stated product attribute. The buyer must discover the alternative, establish its relevant facts, and present the concrete specification difference with actual price, availability and delivery consequences. Approval changes the allowed attribute only for the identified line and candidate scope. A brand change already permitted by the request, pack conversion, missing-fact clarification, or delivery-only choice does not satisfy this demonstration. The exact alternative and its terms remain open until vendor evidence exists; no technical equivalence or winning choice is predeclared.
4. **Optional delivery decision.** If an observed offer creates a material price/timing tradeoff, compare its actual delivered total and date with a conforming option. Acceptance changes the deadline only for the stated lines; rejection or silence preserves Sept 18. Do not manufacture a concession to force this branch.

The two missing-essential questions can be combined once, if still unresolved after reading the task context. Most lines require catalog inspection, supplier clarification, pack math or cross-product evidence, not 25 contractor questions. Supplier omissions go to the supplier first. Ask about an additional contractor change only when an actual candidate makes it necessary, and continue unaffected lines while waiting.

## Shared mapping boundary

Keep three separate records: the immutable contractor message, derived requirements with recorded decisions, and public supplier product/offer evidence. Each candidate links to its source facts and is marked eligible, needing supplier clarification, needing contractor clarification/approval, or unsuitable. A model's confidence does not turn an unsupported interpretation into a requirement.

Ask Tapan's implementation agent for public product references, distinguishing specifications, sale-unit contents, order increments/minimums, price basis, stock-or-unknown, and a clarification channel. Confirmed offers also need inquiry correlation, revisions, delivery, charges, validity and relevant conditions. Catalog presence alone is not a confirmed offer. Supplier commercial internals stay on the supplier side.

## Checks the implementation must pass

1. Preserve all 25 source requirements and stable references within the adopted request revision. A thin integration slice is explicitly partial.
2. Resolve shorthand from product facts; reject a similar title that contradicts a required fact. Product IDs or listing order cannot determine a match.
3. Compare equivalent quantities across pieces, sheets, coils, rolls, bags, bundles, cartons and containers using documented contents/coverage. Charge for whole sale units and show permitted surplus.
4. Ask suppliers for missing product/offer facts. Confirmation and contradiction must produce different candidate states; unknown stock, compatibility or fees cannot become favorable defaults.
5. Ask the contractor only when intent remains unresolved in supplied records. Stock cannot decide facing or compatibility with unidentified existing fittings.
6. Show at least one meaningful product-attribute substitution grounded in actual supplier evidence. Accept only a current, applicable contractor decision; rejection or silence retains the original requirement.
7. Revalidate related products if a selection changes, including shingles/underlayment, wrap/tapes/windows and tubing/fittings. Matching a procurement description is not an engineering certification.
8. Recompute totals and eligibility when quantities, stock, prices, fees, conditions or approvals change. No fixed winner; any uncovered requirement leaves the 25-line package incomplete.

The buyer model chooses discovery questions, candidates, counteroffer prices, bundles and negotiation tactics from observed facts. The vendor model chooses concessions and disclosures within its private commercial limits. Code guards enforce inventory, arithmetic and approved constraints; they do not script strategy, a winning supplier, or savings. Recorded runs can support reliable video playback while retaining these real decisions.

The same schema and helper tools can be developed before the suppliers finish implementation. The shared live scenario still needs Tapan's buyer-visible supply, actual channel references and an adopted contractor task. Exact component adoption and first-slice choices are delegated to the implementation agents jointly so they can complete the working journey within the deadline.
