"""Validate model-proposed packages. No strategy, winner, or supplier floor is encoded."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import json


def _decimal(value):
    if isinstance(value, bool) or value is None:
        raise ValueError("missing numeric value")
    try:
        number = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError("invalid numeric value") from exc
    if not number.is_finite() or number < 0:
        raise ValueError("invalid nonnegative value")
    return number


def _time(value):
    if isinstance(value, datetime):
        result = value
    else:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("timestamp needs timezone")
    return result


def _qid(quote):
    return quote.get("quote_id", quote.get("id"))


def _records(value):
    return list(value.values()) if isinstance(value, dict) else list(value or [])


def _terms(value):
    return [term for term in value if isinstance(term, dict)] if isinstance(value, list) else []


def _condition_issues(value):
    """Textual issued terms accompany the atomic quote; explicit unresolved states block."""
    issues = []
    if isinstance(value, list):
        for condition in value:
            issues.extend(_condition_issues(condition))
    elif isinstance(value, dict):
        label = value.get("description", value.get("name", value.get("code", "package condition")))
        if "satisfied" in value and value["satisfied"] is not True:
            issues.append(f"{label}: condition is unsatisfied or unknown.")
        if value.get("status") in ("unsatisfied", "unmet", "unknown", "pending", "needs_approval", "requires_approval"):
            issues.append(f"{label}: condition status is {value['status']}.")
        if ((value.get("requires_approval") is True or value.get("approval_required") is True)
                and value.get("approved") is not True and value.get("approval_status") != "approved"):
            issues.append(f"{label}: required approval is unresolved.")
        if "conditions" in value:
            issues.extend(_condition_issues(value["conditions"]))
    return issues


def _requirements(run):
    return _records(run.get("requirements", run.get("request", {}).get("requirements", [])))


def _scope(run, approvals=None):
    return json.dumps({"requirements": _requirements(run), "authority": run.get("authority", {}),
                       "constraints": run.get("constraints", {}),
                       "request_revision": run.get("request_revision", run.get("request", {}).get("revision")),
                       "approvals": approvals if approvals is not None else run.get("approvals", [])}, sort_keys=True, default=str)


def _product(candidates, requirement_id, product_id, vendor_id, current_products=()):
    # run.products is the latest public catalog snapshot, while candidates retain
    # the facts used when they were assessed. Never revive old stock/specifications
    # or order opaque revision hashes to decide which observation is current.
    current = [p for p in current_products if p.get("id", p.get("product_id")) == product_id]
    if current:
        matches = [p for p in current if p.get("vendor_id", vendor_id) == vendor_id]
        return matches[0] if len(matches) == 1 else None
    matches = []
    for candidate in candidates:
        product = candidate.get("product", candidate)
        if (product.get("id", product.get("product_id")) == product_id
                and candidate.get("requirement_id", requirement_id) == requirement_id
                and product.get("vendor_id", candidate.get("vendor_id", vendor_id)) == vendor_id):
            matches.append(product)
    return max(enumerate(matches), key=lambda pair: (pair[1].get("revision", 0), pair[0]))[1] if matches else None


def _approval_matches(approval, run, requirement, quote, product):
    return (approval.get("validated") is True and approval.get("decision") in ("approved", "rejected")
            and approval.get("run_id") == run.get("id", run.get("run_id"))
            and approval.get("request_revision") == run.get("request_revision", run.get("request", {}).get("revision", 1))
            and approval.get("requirement_id") == requirement.get("id")
            and approval.get("requirement_revision") == requirement.get("revision", 1)
            and approval.get("product_id") == product.get("id", product.get("product_id"))
            and (not approval.get("quote_id") or
                 (approval["quote_id"] == _qid(quote) and approval.get("quote_revision") == quote.get("revision")))
            and (not approval.get("product_revision") or approval["product_revision"] == product.get("revision")))


def _effective_approvals(records):
    """A later refusal overrides prior permission; ambiguous ordering is unresolved."""
    accepted = []
    rejections = [a for a in records if a.get("decision") == "rejected"]
    for approval in records:
        if approval.get("decision") != "approved":
            continue
        try:
            superseded = any(_time(r.get("source", {}).get("created_at")) >=
                             _time(approval.get("source", {}).get("created_at")) for r in rejections)
        except (ValueError, TypeError):
            superseded = True
        if not superseded:
            accepted.append(approval)
    return accepted


def evaluate_plan(run, selected_quotes, candidates=None, approvals=None, now=None):
    """Validate whole issued quotes proposed by the model and return JSON-safe evidence.

    selected_quotes contains quote dictionaries or IDs from run.quotes. Product
    snapshots in candidates (or run.candidates) are reassessed on every call. No
    mutation, supplier contact, purchase, or combinatorial search occurs here.
    """
    from .discovery import assess_candidate, quantity_for_requirement
    from .quotes import normalize_quote

    evaluated_at = _time(now) if now is not None else datetime.now(timezone.utc)
    requirements = _requirements(run)
    requirement_map = {r["id"]: r for r in requirements}
    catalog = _records(candidates if candidates is not None else run.get("candidates", []))
    current_products = _records(run.get("products", []))
    approvals = _records(approvals if approvals is not None else run.get("approvals", []))
    available_quotes = _records(run.get("quotes", []))
    selected_quotes = list(selected_quotes)
    blockers, offers, used_approvals = [], [], []
    coverage = {r["id"]: Decimal(0) for r in requirements}
    variant_coverage = {r["id"]: {v.get("id"): Decimal(0) for v in _terms(r.get("variants"))}
                        for r in requirements if r.get("variants")}
    # Compatibility is evaluated against the package the model actually chose,
    # including every selected variant. Catalog presence alone is not selection.
    selected_products = {}
    for selection in selected_quotes:
        matching = [q for q in available_quotes if _qid(q) == selection] if isinstance(selection, str) else [selection]
        if not matching:
            continue
        selected = max(matching, key=lambda q: q.get("revision", 0))
        selected = selected.get("raw", selected)
        for line in _terms(selected.get("lines")):
            product = _product(catalog, line.get("requirement_id"), line.get("product_id"), selected.get("vendor_id"), current_products)
            if product is not None:
                selected_products.setdefault(line.get("requirement_id"), []).append(product)
    known_total = Decimal(0)
    total_known = True
    seen, vendors, stock_usage, tax_bases = set(), set(), {}, set()
    request = run.get("request", {})
    constraints = run.get("constraints", request.get("constraints", {}))
    authority = run.get("authority", {})
    deadline = constraints.get("delivery_deadline", request.get("delivery_deadline", run.get("delivery_deadline")))
    budget = authority.get("budget_cap", constraints.get("budget", request.get("budget")))
    if isinstance(budget, dict):
        budget = budget.get("amount", budget.get("maximum"))
    if not requirements:
        blockers.append("No material requirements recorded.")
    for selection in selected_quotes:
        if isinstance(selection, str):
            matches = [q for q in available_quotes if _qid(q) == selection]
            if not matches:
                blockers.append(f"Quote {selection}: no recorded offer.")
                continue
            raw = max(matches, key=lambda q: q.get("revision", 0))
        else:
            raw = selection
        source_evidence = raw.get("source_evidence")
        source_id = run.get("quote_sources", {}).get(_qid(raw))
        if source_id is not None:
            source_evidence = run.get("evidence", {}).get(source_id)
        raw = raw.get("raw", raw)
        quote = normalize_quote(raw, evidence=source_evidence, now=evaluated_at)
        qid, vendor = _qid(quote), quote.get("vendor_id")
        label = f"Quote {qid}"
        issues = list(quote.get("errors", [])) + list(quote.get("unresolved", []))
        tax_bases.add(quote.get("total_basis", "tax-inclusive"))
        recorded = [q.get("raw", q) for q in available_quotes
                    if _qid(q) == qid and q.get("revision") == quote.get("revision")]
        if recorded and raw not in recorded:
            issues.append("Selected terms differ from the recorded whole quote at this revision.")
        if qid in seen:
            blockers.append(f"{label}: selected more than once.")
            continue
        seen.add(qid)
        if vendor in vendors:
            issues.append("Multiple quotes from this supplier cannot be combined without a confirmed combined offer.")
        vendors.add(vendor)
        if quote.get("run_id") != run.get("supplier_run_id", run.get("id", run.get("run_id"))):
            issues.append("Offer belongs to a different run.")
        if any(_qid(q) == qid and q.get("revision", 0) > quote.get("revision", 0) for q in available_quotes):
            issues.append("A newer recorded quote revision exists.")
        if any(q.get("previous_quote_id") == qid and q.get("status") == "issued" for q in available_quotes):
            issues.append("A revised offer supersedes this quote.")
        if quote.get("currency") != "USD":
            issues.append("Only USD packages are supported; currency conversion is not inferred.")
        if quote.get("status") != "issued":
            issues.append("Offer is not an issued confirmed quote.")
        if not quote.get("evidence_refs"):
            issues.append("Offer evidence is missing.")
        # The supplier issued these exact complete terms. Full-package discount,
        # simulated-business, and reservation boilerplate need no invented extra
        # confirmation flag; explicit unresolved machine conditions still block.
        issues.extend(_condition_issues(quote.get("conditions")))
        for term in _terms(quote.get("fees")) + _terms(quote.get("discounts")):
            issues.extend(_condition_issues(term.get("conditions")))
        try:
            known_total += _decimal(quote.get("total"))
        except ValueError:
            total_known = False
        if quote.get("unresolved") or quote.get("errors"):
            total_known = False
        delivery_at = None
        delivery = quote.get("delivery") if isinstance(quote.get("delivery"), dict) else {}
        try:
            if delivery.get("arrives_at", delivery.get("date")):
                delivery_at = _time(delivery.get("arrives_at", delivery.get("date")))
            elif delivery.get("days") is not None:
                # A relative lead time requires a known date from which it runs.
                origin = quote.get("issued_at", quote.get("created_at", delivery.get("start_at")))
                if origin is None and delivery.get("lead_time_basis") == "run_started_at":
                    origin = run.get("started_at")
                if origin is None:
                    issues.append("Delivery lead time has no confirmed starting timestamp.")
                else:
                    delivery_at = _time(origin) + timedelta(days=float(_decimal(delivery["days"])))
            else:
                issues.append("Delivery is unknown.")
            if deadline and delivery_at and delivery_at > _time(deadline):
                issues.append("Delivery misses the approved deadline.")
        except (ValueError, TypeError, OverflowError):
            issues.append("Delivery date or approved deadline is invalid.")
        line_results = []
        for line in quote.get("lines", []):
            result = deepcopy(line)
            rid, pid = line.get("requirement_id"), line.get("product_id")
            req = requirement_map.get(rid)
            line_issues = []
            if req is None:
                line_issues.append("Quoted requirement is not in the current request.")
            product = _product(catalog, rid, pid, vendor, current_products)
            if product is None:
                line_issues.append("Public product facts are missing.")
            if req and product:
                applicable = _effective_approvals([a for a in approvals if _approval_matches(a, run, req, quote, product)])
                if req.get("variants"):
                    from .discovery import requirement_for_product
                    variant = requirement_for_product(req, product)
                else:
                    variant = {"requirement": deepcopy(req), "variant_id": None}
                allocated_requirement = deepcopy(variant["requirement"])
                line_issues.extend(str(issue) for issue in variant.get("errors", []) + variant.get("unresolved", []))
                line_issues.extend("Variant mismatch: " + str(issue) for issue in variant.get("mismatches", []))
                result["variant_id"] = variant.get("variant_id")
                # Assess the allocation, so several suppliers can cover a line
                # without each needing stock for the entire requirement.
                conversion = quantity_for_requirement(allocated_requirement, product)
                try:
                    per_sale = _decimal(conversion["coverage_quantity"]) / _decimal(conversion["selling_quantity"])
                    allocated_requirement["quantity"] = str(min(_decimal(allocated_requirement["quantity"]), _decimal(line.get("quantity")) * per_sale))
                except (ValueError, TypeError, ZeroDivisionError):
                    pass
                compatibility_context = {"selected_products": selected_products} if (
                    req.get("compatibility") or product.get("related_requirements")) else {}
                assessment = assess_candidate(allocated_requirement, product, approvals=applicable, **compatibility_context)
                result["assessment"] = assessment
                if assessment.get("status") not in ("suitable", "approved_substitution"):
                    line_issues.append("Product is " + str(assessment.get("status")) + ".")
                else:
                    if assessment.get("status") == "approved_substitution":
                        used_approvals.extend(applicable)
                    quantity = assessment.get("quantity", {})
                    line_issues.extend(str(x) for x in quantity.get("errors", []) + quantity.get("unresolved", []))
                    try:
                        bought = _decimal(line.get("quantity"))
                        selling = _decimal(quantity.get("selling_quantity"))
                        covered = _decimal(quantity.get("coverage_quantity"))
                        if selling <= 0 or bought <= 0:
                            raise ValueError("empty quantity")
                        if line.get("unit") != quantity.get("unit"):
                            line_issues.append("Quote unit differs from the product's selling unit.")
                        increment = _decimal(product.get("pack_size", product.get("order_increment", product.get("pack_increment"))))
                        if increment <= 0 or bought % increment:
                            line_issues.append("Quantity does not purchase whole sale increments.")
                        minimum = product.get("minimum_order", product.get("minimum_quantity", 0))
                        if bought < _decimal(minimum):
                            line_issues.append("Quantity is below the supplier minimum.")
                        result["coverage_quantity"] = str(bought * covered / selling)
                        result["coverage_unit"] = quantity.get("coverage_unit", req.get("unit"))
                        if result["coverage_unit"] != req.get("unit"):
                            line_issues.append("Coverage unit does not match the requirement.")
                        key = (vendor, pid)
                        stock_usage[key] = stock_usage.get(key, Decimal(0)) + bought
                        stock = product.get("stock", product.get("stock_quantity"))
                        if isinstance(stock, dict):
                            stock = stock.get("quantity", stock.get("available"))
                        if stock is None:
                            line_issues.append("Current product stock is unknown.")
                        elif stock_usage[key] > _decimal(stock):
                            line_issues.append("Selected quantity exceeds current product stock.")
                        if not line_issues:
                            coverage[rid] += bought * covered / selling
                            if rid in variant_coverage:
                                variant_id = result["variant_id"]
                                if variant_id not in variant_coverage[rid]:
                                    line_issues.append("Selected product does not identify a required variant.")
                                else:
                                    variant_coverage[rid][variant_id] += bought * covered / selling
                    except (ValueError, TypeError, KeyError, ZeroDivisionError):
                        line_issues.append("Quantity, pack conversion, or stock is not established.")
            result["blockers"] = line_issues
            issues.extend(f"{rid}/{pid}: {issue}" for issue in line_issues)
            line_results.append(result)
        blockers.extend(f"{label}: {issue}" for issue in issues)
        offers.append({"quote_id": qid, "vendor_id": vendor, "revision": quote.get("revision"),
                       "total": quote.get("total"), "lines": line_results,
                       "fees": _terms(quote.get("fees")), "discounts": _terms(quote.get("discounts")),
                       "conditions": deepcopy(quote.get("conditions", [])),
                       "total_basis": quote.get("total_basis", "tax-inclusive"),
                       "delivery_at": delivery_at.isoformat() if delivery_at else None,
                       "evidence_refs": quote.get("evidence_refs", []), "blockers": issues})
    covered_ids = []
    for req in requirements:
        try:
            required = _decimal(req.get("quantity"))
            variants_complete = True
            if req.get("variants"):
                variants = _terms(req["variants"])
                variant_ids = [v.get("id") for v in variants]
                if (not variants or len(set(variant_ids)) != len(variant_ids) or any(not v for v in variant_ids)
                        or any(v.get("unit") != req.get("unit") for v in variants)
                        or sum((_decimal(v.get("quantity")) for v in variants), Decimal(0)) != required):
                    variants_complete = False
                    blockers.append(f"Requirement {req['id']}: variants must have unique IDs and quantities summing to the parent in the same unit.")
                for variant in variants:
                    variant_required = _decimal(variant.get("quantity"))
                    variant_actual = variant_coverage[req["id"]][variant.get("id")]
                    if variant_required <= 0 or variant_actual < variant_required:
                        variants_complete = False
                        blockers.append(f"Requirement {req['id']} variant {variant.get('id')}: {variant_actual} of {variant_required} {variant.get('unit')} covered.")
            if coverage[req["id"]] >= required and required > 0 and variants_complete:
                covered_ids.append(req["id"])
            else:
                blockers.append(f"Requirement {req['id']}: {coverage[req['id']]} of {required} {req.get('unit')} covered.")
        except ValueError:
            blockers.append(f"Requirement {req['id']}: required quantity is unresolved.")
    if budget is not None:
        try:
            if known_total > _decimal(budget):
                blockers.append("Quoted package exceeds the approved budget.")
        except ValueError:
            blockers.append("Approved budget is invalid.")
    if len(tax_bases) > 1:
        blockers.append("Selected quotes have different tax bases; establish comparable payable amounts.")
        total_known = False
    rejected = []
    for quote in available_quotes:
        if _qid(quote) not in seen:
            reasons = run.get("rejection_reasons", {})
            rejected.append({"quote_id": _qid(quote), "reason": reasons.get(_qid(quote), "Not selected in the model-proposed package; no further rejection reason recorded."),
                             "evidence_refs": quote.get("evidence_refs", [])})
    return {"run_id": run.get("id", run.get("run_id")), "evaluated_at": evaluated_at.isoformat(),
            "status": "complete" if not blockers else "partial", "complete": not blockers,
            "currency": "USD", "total_payable": str(known_total) if total_known else None,
            "known_quoted_total": str(known_total), "blockers": list(dict.fromkeys(blockers)),
            "coverage": {"required_count": len(requirements), "covered_count": len(covered_ids),
                         "covered_ids": covered_ids, "quantities": {k: str(v) for k, v in coverage.items()},
                         "variants": {rid: {vid: str(qty) for vid, qty in variants.items()}
                                      for rid, variants in variant_coverage.items()}},
            "selected_offers": offers, "rejected_offers": rejected,
            "approvals_used": list({a["id"]: a for a in used_approvals}.values()),
            "selection_reason": run.get("selection_reason"), "scope": _scope(run, approvals),
            "total_basis": next(iter(tax_bases)) if len(tax_bases) == 1 else "unknown",
            "opening_comparison": {"comparable": False, "reason": "No comparable complete opening package supplied."},
            "ordering_authorized": False}


def compare_opening(plan, opening_plan):
    """Return a copy with a like-for-like baseline, requiring two valid packages."""
    result = deepcopy(plan)
    if (not plan["complete"] or not opening_plan["complete"] or plan["scope"] != opening_plan["scope"]
            or plan.get("total_basis") != opening_plan.get("total_basis")):
        result["opening_comparison"] = {"comparable": False, "reason": "Plans are incomplete or their approved requirements differ."}
    else:
        result["opening_comparison"] = {"comparable": True, "opening_total": opening_plan["total_payable"],
                                        "savings": str(_decimal(opening_plan["total_payable"]) - _decimal(plan["total_payable"]))}
    return result


def rank_plans(plans):
    """Rank only supplied feasible plans; does not assert a global optimum."""
    feasible = [p for p in plans if p.get("complete")]
    bases = {(p.get("scope"), p.get("total_basis"), p.get("currency")) for p in feasible}
    if len(bases) > 1:
        raise ValueError("Cannot rank packages with different requirements or tax/currency bases")
    return sorted(feasible, key=lambda p: _decimal(p["total_payable"]))
