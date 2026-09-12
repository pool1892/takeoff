"""Normalize supplier-issued JSON terms without filling unknown commercial facts."""
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from .discovery import _decimal


def _money(value):
    try:
        return _decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except InvalidOperation:
        raise ValueError("money exceeds supported precision") from None


def _time(value):
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp needs timezone")
    return parsed


def normalize_quote(raw, evidence=None, now=None):
    """Return a new dictionary with original terms, calculation, and explicit gaps.

    ``evidence`` is the actual received source record, not model confidence. If
    supplied its run_id/request_id/vendor_id bindings are verified. Taxes require
    {status: known, amount: ...}, {status: included}, or {status: excluded,
    agreed: true}; otherwise a delivered payable total remains unresolved.
    """
    result = deepcopy(raw)
    result["raw"] = deepcopy(raw)
    result.update(errors=[], unresolved=[], computed_total=None, valid=False)
    errors, unresolved = result["errors"], result["unresolved"]
    result["id"] = raw.get("id") or raw.get("quote_id")
    if raw.get("id") and raw.get("quote_id") and raw["id"] != raw["quote_id"]:
        errors.append("id and quote_id disagree")
    for key in ("id", "run_id", "request_id", "vendor_id", "revision", "currency", "expires_at"):
        if result.get(key) is None or result.get(key) == "":
            unresolved.append(key)
    if (raw.get("revision") is not None and
            (isinstance(raw["revision"], bool) or not isinstance(raw["revision"], int) or raw["revision"] < 1)):
        errors.append("revision must be a positive integer")
    if raw.get("status") != "issued":
        errors.append("quote is not supplier-issued")
    if raw.get("currency") not in (None, "USD"):
        errors.append("unsupported currency")
    refs = deepcopy(raw.get("evidence_refs") or [])
    if not isinstance(refs, list):
        errors.append("evidence_refs must be a list")
        refs = []
    if evidence is not None and not isinstance(evidence, dict):
        errors.append("source evidence must be an object")
    elif evidence is not None:
        result["source_evidence"] = deepcopy(evidence)
        if evidence.get("id") and evidence["id"] not in refs:
            refs.append(evidence["id"])
        for key in ("run_id", "request_id", "vendor_id"):
            if evidence.get(key) is not None and raw.get(key) != evidence[key]:
                errors.append(f"source {key} mismatch")
    result["evidence_refs"] = refs
    if not refs:
        unresolved.append("supplier source evidence")
    if raw.get("expires_at"):
        try:
            if _time(raw["expires_at"]) <= _time(now or datetime.now(timezone.utc)):
                errors.append("quote expired")
        except (TypeError, ValueError):
            errors.append("invalid expiry or current timestamp")
    subtotal = Decimal(0)
    lines = raw.get("lines")
    if not isinstance(lines, list) or not lines:
        unresolved.append("lines")
        lines = []
    normalized_lines = []
    for index, line in enumerate(lines):
        path = f"lines[{index}]"
        if not isinstance(line, dict):
            errors.append(f"{path} must be an object")
            continue
        normalized = deepcopy(line)
        for key in ("product_id", "requirement_id", "quantity", "unit", "unit_price", "line_total"):
            if line.get(key) is None or line.get(key) == "":
                unresolved.append(f"{path}.{key}")
        try:
            quantity, price = _decimal(line.get("quantity")), _decimal(line.get("unit_price"))
            if quantity <= 0 or price < 0:
                raise ValueError("invalid quantity or price")
            calculated = _money(quantity * price)
            subtotal += calculated
            normalized["computed_line_total"] = str(calculated)
            if line.get("line_total") is not None and _money(line["line_total"]) != calculated:
                errors.append(f"{path}.line_total arithmetic mismatch")
        except ValueError:
            errors.append(f"{path} invalid quantity or money")
        normalized_lines.append(normalized)
    result["lines"] = normalized_lines
    result["computed_subtotal"] = str(subtotal)
    def check_amount(key, calculated):
        if raw.get(key) is None:
            unresolved.append(key)
        else:
            try:
                if _money(raw[key]) != calculated:
                    errors.append(f"{key} arithmetic mismatch")
            except ValueError:
                errors.append(f"invalid {key}")
    check_amount("subtotal", subtotal)
    computed = subtotal
    for key, sign in (("fees", 1), ("discounts", -1)):
        if not isinstance(raw.get(key), list):
            unresolved.append(key)
            continue
        for index, term in enumerate(raw[key]):
            if not isinstance(term, dict):
                errors.append(f"{key}[{index}] must be an object")
                continue
            try:
                amount = _money(term.get("amount"))
                if amount < 0:
                    raise ValueError("negative amount")
                computed += sign * amount
            except ValueError:
                errors.append(f"{key}[{index}] invalid amount")
    taxes = deepcopy(raw.get("taxes") or {"status": "unknown", "amount": None})
    if raw.get("tax_treatment") == "all_fixture_taxes_included":
        fixture_taxes = {"status": "known", "amount": "0.00",
                         "treatment": "all_fixture_taxes_included", "scope": "synthetic supplier fixture"}
        if raw.get("taxes") and raw["taxes"] != fixture_taxes:
            supplied = raw["taxes"]
            if (not isinstance(supplied, dict) or supplied.get("status") not in ("known", "included")
                    or (supplied.get("status") == "known" and supplied.get("amount") not in (0, "0", "0.00"))):
                errors.append("taxes conflict with fixture tax treatment")
        taxes = fixture_taxes
    result["taxes"] = taxes
    if not isinstance(taxes, dict):
        errors.append("invalid taxes")
    elif taxes.get("status") == "known":
        result["total_basis"] = "tax-inclusive"
        try:
            amount = _money(taxes.get("amount"))
            if amount < 0:
                raise ValueError("negative tax")
            computed += amount
        except ValueError:
            errors.append("invalid tax amount")
    elif taxes.get("status") == "included":
        result["total_basis"] = "tax-inclusive"
    elif taxes.get("status") == "excluded" and taxes.get("agreed") is True:
        result["total_basis"] = "agreed tax-exclusive"
    else:
        unresolved.append("taxes")
    result["computed_total"] = str(computed)
    if computed < 0:
        errors.append("negative computed total")
    check_amount("total", computed)
    delivery = raw.get("delivery")
    if not isinstance(delivery, dict):
        unresolved.append("delivery")
    elif delivery.get("days") is None and not delivery.get("date"):
        unresolved.append("delivery.days or delivery.date")
    else:
        if delivery.get("days") is not None:
            try:
                if _decimal(delivery["days"]) < 0:
                    raise ValueError("negative delivery days")
            except ValueError:
                errors.append("invalid delivery.days")
    result["valid"] = not errors and not unresolved
    return result
