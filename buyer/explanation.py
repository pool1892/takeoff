"""Contractor-facing rendering of evaluated evidence; never executes an order."""
from datetime import datetime
from decimal import Decimal, InvalidOperation


CONTEXT_URL = "https://github.com/pool1892/takeoff/blob/main/docs/demo-context.md"


def _cell(value):
    return str(value if value is not None else "unknown").replace("|", "\\|").replace("\n", " ")


def _refs(values):
    return ", ".join(_cell(v) for v in values) or "none recorded"


def _money(value, currency):
    if value is None:
        return "unknown"
    try:
        amount = format(Decimal(str(value)), ",.2f")
    except (InvalidOperation, ValueError):
        amount = _cell(value)
    return f"{currency} {amount}"


def _date(value):
    if not value:
        return "not confirmed"
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return _cell(value)
    date = f"{parsed.strftime('%b')} {parsed.day}, {parsed.year}"
    if len(str(value)) <= 10:
        return date
    clock = f"{parsed.hour % 12 or 12}:{parsed.minute:02d} {'AM' if parsed.hour < 12 else 'PM'}"
    offset = parsed.strftime("%z")
    zone = f" (UTC{offset[:3]}:{offset[3:]})" if offset else ""
    return f"{date}, {clock}{zone}"


def _quantity(value, unit):
    units = {"linear_ft": "ft", "sq_ft": "sq ft", "us_gal": "US gal"}
    label = units.get(unit, unit)
    if unit in ("sheet", "pack", "coil", "roll", "bag", "pail", "bundle", "board", "can"):
        try:
            if Decimal(str(value)) != 1:
                label += "s"
        except InvalidOperation:
            pass
    if unit == "box" and str(value) != "1":
        label = "boxes"
    return f"{value} {label}"


def explain_plan(plan):
    """Render names and commercial facts first, with exact references kept below."""
    counts, currency = plan["coverage"], plan["currency"]
    lines = ["Buying plan", "",
             f"{counts['covered_count']} of {counts['required_count']} material requirements covered. "
             + ("Ready for your review." if plan["complete"] else "There are outstanding items; this plan is not ready to buy."),
             "", f"**Total payable: {_money(plan['total_payable'], currency)}**"]
    if plan["total_payable"] is None:
        lines += [f"Quoted amounts so far: {_money(plan['known_quoted_total'], currency)}. Outstanding terms still need confirmation."]
    if plan.get("total_basis") == "agreed tax-exclusive":
        lines += ["Amounts use the agreed tax-exclusive basis."]
    if plan.get("selection_reason"):
        lines += ["", "Why this package: " + str(plan["selection_reason"])]

    references, product_labels, requirement_labels = [], {}, {}
    if plan["selected_offers"]:
        lines += ["", "| Material | Purchase quantity | Supplier | Line cost |", "| --- | --- | --- | --- |"]
    for number, offer in enumerate(plan["selected_offers"], 1):
        supplier = offer.get("supplier_name") or offer["vendor_id"]
        for item in offer["lines"]:
            product = item.get("product_name") or item.get("name") or item.get("product_id")
            product_labels[item.get("product_id")] = product
            requirement_labels[item.get("requirement_id")] = item.get("requirement_name") or item.get("requirement_id")
            if item.get("variant_id"):
                product = f"{product} ({item['variant_id']})"
            lines.append("| " + " | ".join(_cell(v) for v in [
                product, _quantity(item.get('quantity'), item.get('unit')),
                f"{supplier} [{number}]", _money(item.get("line_total"), currency)]) + " |")
        references.append(f"[{number}] {_cell(supplier)} — quote {_cell(offer['quote_id'])}, revision {_cell(offer['revision'])}; "
                          f"sources: {_refs(offer.get('evidence_refs', []))}.")
    for number, offer in enumerate(plan["selected_offers"], 1):
        supplier = offer.get("supplier_name") or offer["vendor_id"]
        lines += ["", f"**{_cell(supplier)}** — package total {_money(offer.get('total'), currency)}; "
                  f"delivery {_date(offer.get('delivery_at'))}. [{number}]"]
        if offer.get("expires_at"):
            lines.append(f"Quote valid until {_date(offer['expires_at'])}.")
        terms = []
        for kind in ("fees", "discounts"):
            for term in offer.get(kind, []):
                terms.append(f"{kind.capitalize()}: {_cell(term.get('name', term.get('code', 'term')))} {_money(term.get('amount'), currency)}.")
                if term.get("conditions"):
                    terms.append(f"Conditions: {_cell(term['conditions'])}")
        conditions = offer.get("conditions", [])
        terms.extend(_cell(condition) for condition in (conditions if isinstance(conditions, list) else [conditions]) if condition)
        if terms:
            lines += ["", *["- " + term for term in terms]]

    if plan["approvals_used"]:
        lines += ["", "Approved changes:"]
        for number, approval in enumerate(plan["approvals_used"], 1):
            product = product_labels.get(approval.get("product_id"), approval.get("product_id"))
            requirement = requirement_labels.get(approval.get("requirement_id"), approval.get("requirement_id"))
            lines.append(f"- {_cell(product)} for {_cell(requirement)}. [A{number}]")
            references.append(f"[A{number}] Approval {_cell(approval.get('id'))}; sources: {_refs(approval.get('evidence_refs', []))}.")
    if plan["blockers"]:
        lines += ["", "What still needs resolution:", *["- " + _cell(b) for b in plan["blockers"]]]
    if plan["rejected_offers"]:
        lines += ["", "Other offers:"]
        for number, rejected in enumerate(plan["rejected_offers"], 1):
            reason = rejected["reason"]
            if reason == "Not selected in the model-proposed package; no further rejection reason recorded.":
                reason = "Not selected; no further rejection reason recorded."
            lines.append(f"- {_cell(rejected.get('supplier_name') or rejected['quote_id'])}: {_cell(reason)} [O{number}]")
            references.append(f"[O{number}] Quote {_cell(rejected['quote_id'])}; sources: {_refs(rejected.get('evidence_refs', []))}.")
    comparison = plan.get("opening_comparison", {})
    if comparison.get("comparable"):
        lines += ["", f"Opening-offer package: {_money(comparison['opening_total'], currency)}. "
                  f"Price difference under the same requirements: {_money(comparison['savings'], currency)}."]
    elif comparison.get("reason") and comparison["reason"] != "No comparable complete opening package supplied.":
        lines += ["", "Opening-offer comparison unavailable: " + comparison["reason"]]
    if references:
        lines += ["", "Quote and approval references:", "", *["- " + ref for ref in references]]
    lines += ["", f"Draft purchase plan; no order placed. [Demo context]({CONTEXT_URL})"]
    return "\n".join(lines)
