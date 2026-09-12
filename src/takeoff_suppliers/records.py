"""Publish public supplier records to Ambiguous with durable creation recovery.

Document POST does not advertise an idempotency key. A pending creation is never
retried automatically: reconcile its marker with Ambiguous before resuming.
Reference: https://app.ambiguous.ai/api/openapi.json
"""

import hashlib
import json
import threading

from .runtime import RecoveryRequired


def pick(record, fields):
    return {key: record[key] for key in fields if key in record}


def markdown_table(headers, rows):
    def cell(value):
        if value is None:
            return "Unknown"
        if isinstance(value, (dict, list)):
            value = json.dumps(value, ensure_ascii=False, sort_keys=True)
        return str(value).replace("|", "\\|").replace("\n", " ")
    return "\n".join(["| " + " | ".join(headers) + " |",
                      "| " + " | ".join("---" for _ in headers) + " |",
                      *("| " + " | ".join(cell(v) for v in row) + " |" for row in rows)])


def public_offer(offer):
    """Project the commercial record; private extension fields never propagate."""
    result = pick(offer, (
        "id", "quote_id", "run_id", "vendor_id", "supplier_id", "buyer_id", "request_id",
        "revision", "previous_quote_id", "status", "subtotal", "total", "currency",
        "delivery_slot", "created_at", "expires_at", "conditions", "simulated",
        "evidence_refs", "accepted_at", "commitment_id", "approval_refs", "tax_treatment",
    ))
    result["lines"] = [pick(line, ("product_id", "name", "quantity", "unit", "unit_price",
                                  "line_total", "requirement_id", "substitution_for",
                                  "units_per_sale_unit", "requirement_unit", "covered_quantity", "variant"))
                       for line in offer.get("lines", [])]
    result["fees"] = [pick(fee, ("name", "amount")) for fee in offer.get("fees", [])]
    result["discounts"] = [pick(discount, ("code", "description", "amount"))
                           for discount in offer.get("discounts", [])]
    result["delivery"] = pick(offer.get("delivery", {}), ("slot_id", "label", "days"))
    if "draft_order" in offer:
        result["draft_order"] = pick(offer["draft_order"],
                                    ("id", "quote_id", "revision", "supplier_id", "total",
                                     "currency", "status", "tax_treatment"))
        result["draft_order"].update(lines=result["lines"], delivery=result["delivery"])
    return result


class AmbiguousRecords:
    """One publisher per vendor worker, using its existing transport state."""

    def __init__(self, channel, state):
        self.channel = channel
        self.state = state
        # Prevent concurrent calls on this publisher racing their first POST.
        self._lock = threading.RLock()

    def _vendor(self, vendor_id):
        if vendor_id != self.channel.config.vendor_id:
            raise ValueError("Record belongs to another supplier identity")
        if self.channel.identity is None:
            self.channel.verify_identity(require_buyer=False)

    def _create(self, kind, identity, payload, path="/api/documents"):
        config = self.channel.config
        scope = [config.workspace_id, config.user_id, config.vendor_id, kind, *identity]
        marker = "takeoff-record-" + hashlib.sha256(json.dumps(scope).encode()).hexdigest()[:24]
        key = f"record:{marker}"
        with self._lock:
            saved = self.state.get(key)
            if saved is not None:
                if saved.get("pending"):
                    raise RecoveryRequired(f"Ambiguous creation needs reconciliation: {marker}")
                return saved["record"]
            payload = dict(payload, labels=["takeoff", "simulated", marker])
            # Persist the identity before sending a non-idempotent remote POST.
            self.state.put(key, {"pending": True, "marker": marker, "kind": kind})
            try:
                response = self.channel.request("POST", path, json=payload)
                document_id = response.get("id")
                if not isinstance(document_id, str) or not document_id:
                    raise ValueError("Ambiguous create returned no document ID")
                record = {"id": document_id, "type": response.get("type", payload.get("type", "sheet")),
                          "title": response.get("title", payload["title"]), "marker": marker,
                          "visibility": response.get("visibility", payload["visibility"])}
                self.state.put(key, {"pending": False, "record": record})
            except Exception as exc:
                # Do not store provider error bodies or retry an ambiguous outcome.
                raise RecoveryRequired(f"Ambiguous creation needs reconciliation: {marker}") from exc
            return record

    def publish_catalog(self, market, run_id, vendor_id):
        """Create one readable public catalog snapshot for a supplier/trial."""
        self._vendor(vendor_id)
        run = market.get_run(run_id)
        catalog = market.catalog(run_id, vendor_id)
        title = f"[Simulated] {catalog['vendor']['name']} catalog — {run_id}"
        rows = [[p.get(key) for key in ("id", "name", "unit", "pack_size", "list_price", "stock",
                                      "minimum_quantity", "substitution_for", "source")]
                for p in catalog["products"]]
        content = (f"# {title}\n\n"
                   "Simulated supplier business. This is a publication-time catalog snapshot, not an issued quote. "
                   "Stock and delivery capacity must be checked when ordering.\n\n"
                   f"Scenario: {run['scenario_label']}\n\nVersion: {run['scenario_version']}\n\n"
                   f"Currency: {catalog['currency']}\n\n"
                   f"Tax treatment: {catalog.get('tax_treatment', 'unknown/not_modeled')}\n\n"
                   + markdown_table(["Product", "Name", "Unit", "Pack", "List price", "Stock",
                                     "Minimum", "Substitution for", "Source"], rows))
        content += "\n\n## Delivery\n\n" + markdown_table(
            ["Slot", "Description", "Days", "Fee", "Capacity"],
            [[slot.get(key) for key in ("id", "label", "days", "fee", "capacity")]
             for slot in catalog.get("delivery_slots", [])])
        content += "\n\n## Package opportunities\n\n" + markdown_table(
            ["Code", "Conditions", "Required products", "Minimum units", "Delivery slot"],
            [[discount.get(key) for key in ("code", "description", "required_products", "min_units", "delivery_slot")]
             for discount in catalog.get("discounts", [])])
        # Specifications come exclusively from Market.catalog's public projection.
        content += "\n\n## Product specifications\n\n"
        for product in catalog["products"]:
            content += (f"### {product['id']}\n\n"
                        f"One {product['unit']} supplies {product.get('units_per_sale_unit', '1')} "
                        f"{product.get('requirement_unit', product['unit'])}.\n\n```json\n") + json.dumps(
                product.get("specifications"), indent=2, ensure_ascii=False) + "\n```\n\n"
        return self._create("catalog", [run_id, vendor_id],
                            {"type": "doc", "title": title, "content": content, "visibility": "workspace"})

    def publish_offer(self, offer):
        """Create an issued-offer or accepted-commitment snapshot, never a task."""
        self._vendor(offer["vendor_id"])
        if offer.get("status") not in ("issued", "accepted"):
            raise ValueError("Only issued offers and accepted commitments are publishable")
        public = public_offer(offer)
        quote_id = public["quote_id"]
        status = public["status"]
        title = f"[Simulated] {status.title()} quote {quote_id} revision {public['revision']}"
        content = (f"# {title}\n\nSimulated business record; no real purchase or dispatch.\n\n"
                   f"Supplier: {public['vendor_id']}\n\nRun: {public['run_id']}\n\n"
                   f"Total payable: {public['currency']} {public['total']}\n\n"
                   + markdown_table(["Product", "Quantity", "Unit", "Unit price", "Line total", "Substitution for"],
                                     [[line.get(key) for key in ("product_id", "quantity", "unit", "unit_price",
                                                                "line_total", "substitution_for")]
                                      for line in public["lines"]]))
        content += "\n\n## Complete quoted terms and evidence\n\n```json\n"
        content += json.dumps(public, indent=2, ensure_ascii=False) + "\n```\n"
        return self._create("offer", [public["run_id"], quote_id, public["revision"], status],
                            {"type": "doc", "title": title, "content": content, "visibility": "workspace"})

    def publish_catalog_sheet(self, market, run_id, vendor_id):
        """Optional static catalog table using the documented SheetData format."""
        self._vendor(vendor_id)
        catalog = market.catalog(run_id, vendor_id)
        fields = (("id", "Product"), ("name", "Name"), ("unit", "Selling unit"),
                  ("units_per_sale_unit", "Coverage per selling unit"), ("requirement_unit", "Coverage unit"),
                  ("pack_size", "Pack size"), ("list_price", "List price"),
                  ("stock", "Stock"), ("minimum_quantity", "Minimum quantity"), ("source", "Source"))
        # Text cells retain exact decimal amounts and keep unknown values explicit.
        columns = [{"id": key, "name": label, "type": "text"} for key, label in fields]
        rows = [{key: str(product[key]) if product.get(key) is not None else "Unknown"
                 for key, _ in fields} for product in catalog["products"]]
        payload = {"title": f"[Simulated snapshot] {catalog['vendor']['name']} catalog — {run_id}",
                   "content": {"tabs": [{"name": "Catalog", "columns": columns, "rows": rows}]},
                   "visibility": "workspace"}
        return self._create("catalog_sheet", [run_id, vendor_id], payload, "/api/sheets")
