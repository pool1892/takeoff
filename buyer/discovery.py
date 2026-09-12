"""Evidence checks for model-selected products; no product search or strategy."""
from copy import deepcopy
from decimal import Decimal, InvalidOperation, ROUND_CEILING


def _decimal(value):
    if isinstance(value, bool) or value is None:
        raise ValueError("not a quantity")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError("not a quantity") from None
    if not result.is_finite():
        raise ValueError("not a finite quantity")
    return result


def quantity_for_requirement(requirement, product):
    """Round explicit coverage to selling increments, then MOQ; never infer units.

    Product ``unit`` is its quoted selling-quantity unit. ``pack_size`` is the
    permitted increment in that unit (e.g. 10 sheets). For a carton/roll priced
    per carton/roll, use pack_size=1 and explicit coverage_quantity/coverage_unit.
    Stock and minimum_quantity are measured in the same selling unit.
    """
    selected = requirement_for_product(requirement, product)
    requirement = selected["requirement"]
    result = {"selling_quantity": None, "unit": product.get("unit"),
              "coverage_quantity": None, "coverage_unit": requirement.get("unit"),
              "excess_quantity": None, "variant_id": selected["variant_id"],
              "errors": selected["errors"] + selected["mismatches"], "unresolved": selected["unresolved"]}
    if result["errors"] or result["unresolved"]:
        return result
    for obj, keys, label in ((requirement, ("quantity", "unit"), "requirement"),
                             (product, ("unit", "pack_size", "minimum_quantity"), "product")):
        for key in keys:
            if obj.get(key) is None:
                result["unresolved"].append(f"{label}.{key}")
    if result["unresolved"]:
        return result
    try:
        required = _decimal(requirement["quantity"])
        increment = _decimal(product["pack_size"])
        minimum = _decimal(product["minimum_quantity"])
        if required <= 0 or increment <= 0 or minimum < 0:
            raise ValueError("quantity and pack_size must be positive; minimum cannot be negative")
        if requirement["unit"] == product["unit"]:
            coverage = Decimal(1)
        elif (product.get("coverage_unit", product.get("requirement_unit")) == requirement["unit"]
              and product.get("coverage_quantity", product.get("units_per_sale_unit")) is not None):
            coverage = _decimal(product.get("coverage_quantity", product.get("units_per_sale_unit")))
            if coverage <= 0:
                raise ValueError("coverage_quantity must be positive")
        else:
            result["unresolved"].append("documented coverage conversion")
            return result
        selling = (max(required / coverage, minimum) / increment).to_integral_value(
            rounding=ROUND_CEILING) * increment
        result.update(selling_quantity=str(selling), coverage_quantity=str(selling * coverage),
                      excess_quantity=str(selling * coverage - required),
                      conversion={"per_selling_unit": str(coverage),
                                  "pack_size": str(increment), "minimum_quantity": str(minimum)})
        if (product.get("coverage_quantity") is not None and product.get("units_per_sale_unit") is not None
                and (_decimal(product["coverage_quantity"]) != _decimal(product["units_per_sale_unit"])
                     or product.get("coverage_unit") != product.get("requirement_unit"))):
            result["errors"].append("conflicting explicit coverage conversions")
    except ValueError as exc:
        result["errors"].append(str(exc))
    return result


def _matches(required, actual):
    """Exact facts or explicit allowed-values/numeric bounds; no synonyms inferred."""
    if isinstance(required, dict) and set(required) <= {"any_of", "min", "max"}:
        if "any_of" in required and actual not in required["any_of"]:
            return False
        try:
            if "min" in required and _decimal(actual) < _decimal(required["min"]):
                return False
            if "max" in required and _decimal(actual) > _decimal(required["max"]):
                return False
        except ValueError:
            return False
        return True
    return required == actual


def requirement_for_product(requirement, product):
    """Choose exactly one required variant using facts; preserve the source group.

    Variants carry id, quantity, unit and distinguishing specifications. They are
    quantity obligations, never interchangeable product alternatives. Selection
    does not use supplier IDs, catalog ordering, or the product's variant label.
    """
    result = {"requirement": deepcopy(requirement), "variant_id": requirement.get("variant_id"),
              "errors": [], "unresolved": [], "mismatches": []}
    if "variants" not in requirement:
        return result
    variants = requirement["variants"]
    if not isinstance(variants, list) or not variants:
        result["errors"].append("required variants must be a nonempty list")
        return result
    if any(not isinstance(v, dict) or not v.get("id") or not v.get("specifications") for v in variants):
        result["errors"].append("each variant needs id and distinguishing specifications")
        return result
    if len({v["id"] for v in variants}) != len(variants):
        result["errors"].append("variant IDs must be unique within their source requirement")
    try:
        quantities = [_decimal(v.get("quantity")) for v in variants]
        if any(q <= 0 for q in quantities) or any(v.get("unit") != requirement.get("unit") for v in variants):
            raise ValueError("variant quantities need positive values in the parent requirement unit")
        if sum(quantities) != _decimal(requirement.get("quantity")):
            raise ValueError("variant quantities must sum to the parent requirement quantity")
    except ValueError as exc:
        result["errors"].append(str(exc))
    facts = product.get("specifications") or {}
    matches, missing = [], False
    for variant in variants:
        needed = variant["specifications"]
        if any(value is None or facts.get(key) is None for key, value in needed.items()):
            missing = True
        elif all(_matches(value, facts[key]) for key, value in needed.items()):
            matches.append(variant)
    if len(matches) == 1:
        variant = matches[0]
        effective = result["requirement"]
        effective.pop("variants", None)
        effective.update(quantity=variant["quantity"], unit=variant["unit"], variant_id=variant["id"],
                         specifications={**effective.get("specifications", {}), **variant["specifications"]})
        result["variant_id"] = variant["id"]
    elif len(matches) > 1:
        result["unresolved"].append("product matches multiple required variants; specify distinguishing facts")
    elif missing:
        result["unresolved"].append("product facts needed to identify its required variant")
    else:
        result["mismatches"].append("product does not match any required variant")
    return result


def assess_compatibility(requirement, product, selected_products=None):
    """Recheck model-derived documented use constraints against chosen products.

    Rules either compare two named specification attributes or check explicit
    documented product/related specification values. Evidence attribute names
    refer to the source product specifications. This is a procurement evidence
    check; it does not certify construction or actual installation conditions.
    """
    result = {"checks": [], "mismatches": [], "missing_evidence": []}
    rules = requirement.get("compatibility") or []
    facts = product.get("specifications") or {}
    selected_products = selected_products or {}
    represented = {r.get("requirement_id") for r in rules if isinstance(r, dict)}
    for related in product.get("related_requirements") or []:
        if related not in represented:
            result["missing_evidence"].append(f"documented compatibility rule for {related}")
    for rule in rules:
        if not isinstance(rule, dict) or not rule.get("requirement_id"):
            result["missing_evidence"].append("invalid compatibility rule")
            continue
        rid = rule["requirement_id"]
        evidence_fields = rule.get("evidence_attributes") or []
        if not evidence_fields:
            result["missing_evidence"].append(f"{rid}: compatibility evidence attributes")
        for attribute in evidence_fields:
            if facts.get(attribute) in (None, "", []):
                result["missing_evidence"].append(f"{rid}: product.specifications.{attribute}")
        related_products = selected_products.get(rid) or []
        if not isinstance(related_products, list):
            related_products = [related_products]
        if not related_products:
            result["missing_evidence"].append(f"{rid}: selected related product")
        for related in related_products:
            related_facts = related.get("specifications") or {}
            check = {"requirement_id": rid, "product_id": product.get("id"),
                     "product_revision": product.get("revision"), "related_product_id": related.get("id"),
                     "related_product_revision": related.get("revision"),
                     "evidence": {key: deepcopy(facts.get(key)) for key in evidence_fields},
                     "related_source": deepcopy(related.get("source"))}
            result["checks"].append(check)
            if not related.get("source") and not related.get("evidence_refs"):
                result["missing_evidence"].append(f"{rid}: related product source")
            pairs = []
            if rule.get("product_attribute") and rule.get("related_attribute"):
                pairs.append((rule["product_attribute"], facts.get(rule["product_attribute"]),
                              related_facts.get(rule["related_attribute"])))
            else:
                if not rule.get("product_specifications") or not rule.get("related_specifications"):
                    result["missing_evidence"].append(f"{rid}: explicit documented compatibility predicate")
                pairs.extend((key, expected, facts.get(key)) for key, expected in rule.get("product_specifications", {}).items())
                pairs.extend((key, expected, related_facts.get(key)) for key, expected in rule.get("related_specifications", {}).items())
            for attribute, expected, actual in pairs:
                if expected is None or actual is None:
                    result["missing_evidence"].append(f"{rid}: compatibility fact {attribute}")
                elif not _matches(expected, actual):
                    result["mismatches"].append({"requirement_id": rid, "attribute": attribute,
                                                  "required": deepcopy(expected), "actual": deepcopy(actual),
                                                  "related_product_id": related.get("id")})
    return result


def assess_candidate(requirement, product, approvals=None, selected_products=None):
    """Check supplied facts. Missing evidence never becomes a specification match."""
    selected = requirement_for_product(requirement, product)
    requirement = selected["requirement"]
    quantity = quantity_for_requirement(requirement, product)
    compatibility = assess_compatibility(requirement, product, selected_products)
    result = {"requirement_id": requirement.get("id"),
              "id": f"{requirement.get('id')}@{requirement.get('revision')}:{product.get('vendor_id', 'unknown')}:{product.get('id')}@{product.get('revision', 'unknown')}",
              "run_id": requirement.get("run_id"),
              "request_revision": requirement.get("request_revision"),
              "requirement_revision": requirement.get("revision"),
              "product_id": product.get("id"), "product_revision": product.get("revision"),
              "vendor_id": product.get("vendor_id"), "source": deepcopy(product.get("source")),
              "product": deepcopy(product),
              "variant_id": selected["variant_id"], "compatibility": compatibility,
              "evidence_refs": deepcopy(product.get("evidence_refs", [])),
              "mismatches": [], "missing_evidence": [], "approval_refs": [],
              "quantity": quantity}
    missing = result["missing_evidence"]
    missing.extend(selected["errors"] + selected["unresolved"] + compatibility["missing_evidence"])
    for key in ("id", "revision"):
        if requirement.get(key) is None:
            missing.append(f"requirement.{key}")
    if not product.get("id"):
        missing.append("product.id")
    if not product.get("source") and not product.get("evidence_refs"):
        missing.append("product.source")
    missing.extend(f"requirement.{key}" for key in requirement.get("missing_essentials", []))
    facts = product.get("specifications") or {}
    evidence_attributes = requirement.get("evidence_attributes", [])
    if not isinstance(evidence_attributes, list):
        missing.append("requirement.evidence_attributes (expected attribute names)")
    else:
        for attribute in evidence_attributes:
            if not isinstance(attribute, str) or not attribute.strip():
                missing.append("requirement.evidence_attributes (invalid attribute name)")
            elif not facts.get(attribute) or (isinstance(facts[attribute], str)
                                               and not facts[attribute].strip()):
                missing.append(f"product.specifications.{attribute}")
    for clarification in product.get("unresolved_clarifications") or []:
        if clarification.get("required_before_recommendation") is not True:
            continue
        key = clarification.get("key")
        answer = (requirement.get("clarifications") or {}).get(key) or {}
        attribute = answer.get("specification_attribute")
        if (not key or answer.get("validated") is not True or not answer.get("source_id")
                or answer.get("value") is None or not attribute
                or (requirement.get("specifications") or {}).get(attribute) != answer["value"]):
            missing.append(f"requirement.clarifications.{key or 'unknown'}")
    if product.get("eligibility") == "needs_contractor_clarification" and not product.get("unresolved_clarifications"):
        missing.append("supplier must identify the required contractor clarification")
    for attribute, required in (requirement.get("specifications") or {}).items():
        if required is None:
            missing.append(f"requirement.specifications.{attribute}")
        elif facts.get(attribute) is None:
            missing.append(f"product.specifications.{attribute}")
        elif not _matches(required, facts[attribute]):
            result["mismatches"].append({"attribute": attribute, "required": deepcopy(required),
                                         "actual": deepcopy(facts[attribute])})
    missing.extend(quantity["unresolved"])
    missing.extend(quantity["errors"])
    unavailable = False
    if product.get("stock") is None:
        missing.append("product.stock")
    else:
        try:
            stock = _decimal(product["stock"])
            if stock < 0:
                raise ValueError("negative stock")
            unavailable = stock == 0 or (quantity["selling_quantity"] is not None
                and stock < _decimal(quantity["selling_quantity"]))
        except ValueError:
            missing.append("product.stock (invalid)")
    for approval in approvals or []:
        if (approval.get("decision") != "approved" or approval.get("validated") is not True
                or not approval.get("id")
                or not approval.get("evidence_refs")
                or approval.get("requirement_id") != requirement.get("id")
                or approval.get("requirement_revision") != requirement.get("revision")
                or approval.get("product_id") != product.get("id")):
            continue
        if (approval.get("product_revision") is not None
                and approval["product_revision"] != product.get("revision")):
            continue
        if any(requirement.get(key) is not None and approval.get(key) != requirement[key]
               for key in ("run_id", "request_revision")):
            continue
        approved = approval.get("approved_specifications", {})
        if result["mismatches"] and all(approved.get(m["attribute"]) == m["actual"]
                                           for m in result["mismatches"]):
            result["approval_refs"].append(approval["id"])
    if selected["mismatches"] or compatibility["mismatches"]:
        result["status"] = "incompatible"
        result["variant_mismatches"] = selected["mismatches"]
    elif unavailable:
        result["status"] = "unavailable"
    elif missing:
        result["status"] = "needs_evidence"
    elif result["mismatches"]:
        result["status"] = "approved_substitution" if result["approval_refs"] else "needs_approval"
    else:
        result["status"] = "suitable"
    result["eligible"] = result["status"] in ("suitable", "approved_substitution")
    return result
