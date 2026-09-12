"""Contractor-facing rendering of evaluated evidence; never executes an order."""


def _cell(value):
    return str(value if value is not None else "unknown").replace("|", "\\|").replace("\n", " ")


def _refs(values):
    return ", ".join(_cell(v) for v in values) or "none recorded"


def explain_plan(plan):
    """Render an evaluate_plan result without inventing a rationale or benchmark."""
    counts = plan["coverage"]
    lines = [
        "Draft buying plan — no order placed.",
        "",
        f"{counts['covered_count']} of {counts['required_count']} material requirements covered. "
        + ("The complete package passes the recorded checks." if plan["complete"] else
           "This plan is incomplete or has unresolved conditions; it is not ready to buy."),
        "",
        f"Total payable: {plan['currency']} {plan['total_payable']}" if plan["total_payable"] is not None
        else f"Total payable: unknown. Known quoted amount: {plan['currency']} {plan['known_quoted_total']}.",
    ]
    if plan.get("selection_reason"):
        lines += ["", "Buyer's stated selection rationale: " + str(plan["selection_reason"])]
    if plan.get("total_basis") == "agreed tax-exclusive":
        lines += ["", "Amounts use the explicitly agreed tax-exclusive basis."]
    lines += ["", "| Supplier / quote | Product | Requirement | Purchase quantity | Line cost | Evidence |",
              "| --- | --- | --- | --- | --- | --- |"]
    for offer in plan["selected_offers"]:
        for item in offer["lines"]:
            lines.append("| " + " | ".join(_cell(v) for v in [
                f"{offer['vendor_id']} / {offer['quote_id']} r{offer['revision']}",
                item.get("product_id"), str(item.get("requirement_id")) + (f" / {item['variant_id']}" if item.get("variant_id") else ""),
                f"{item.get('quantity')} {item.get('unit')}", item.get("line_total"),
                _refs(offer.get("evidence_refs", []))]) + " |")
    for offer in plan["selected_offers"]:
        lines += ["", f"{_cell(offer['vendor_id'])}: full quoted package {_cell(offer.get('total'))} {plan['currency']}; "
                  f"delivery {_cell(offer.get('delivery_at'))}; quote {_cell(offer['quote_id'])} r{offer['revision']}."]
        for kind in ("fees", "discounts"):
            for term in offer.get(kind, []):
                lines.append(f"- {kind.capitalize()}: {_cell(term.get('name', term.get('code', 'term')))} "
                             f"{_cell(term.get('amount'))}.")
                if term.get("conditions"):
                    lines.append(f"  Conditions: {_cell(term['conditions'])}")
        conditions = offer.get("conditions", [])
        for condition in conditions if isinstance(conditions, list) else [conditions]:
            if condition:
                lines.append(f"- Supplier condition: {_cell(condition)}")
    if plan["approvals_used"]:
        lines += ["", "Approved substitutions:"]
        for approval in plan["approvals_used"]:
            lines.append(f"- {_cell(approval.get('requirement_id'))}: {_cell(approval.get('product_id'))}; "
                         f"approval {_cell(approval.get('id'))}; evidence {_refs(approval.get('evidence_refs', []))}.")
    if plan["blockers"]:
        lines += ["", "What still needs resolution:"]
        lines += ["- " + _cell(b) for b in plan["blockers"]]
    if plan["rejected_offers"]:
        lines += ["", "Other recorded offers:"]
        for rejected in plan["rejected_offers"]:
            lines.append(f"- {_cell(rejected['quote_id'])}: {_cell(rejected['reason'])}; "
                         f"evidence {_refs(rejected.get('evidence_refs', []))}.")
    comparison = plan.get("opening_comparison", {})
    if comparison.get("comparable"):
        lines += ["", f"Against the supplied feasible opening-offer package under the same requirements: "
                  f"{plan['currency']} {comparison['opening_total']}; price difference "
                  f"{plan['currency']} {comparison['savings']}. This is an automated opening-offer baseline, not a human comparison."]
    elif comparison.get("reason"):
        lines += ["", "Opening-offer comparison unavailable: " + comparison["reason"]]
    lines += ["", "Only the supplied packages and recorded evidence were checked; global optimality and human time savings are not claimed."]
    return "\n".join(lines)
