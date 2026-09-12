"""Supplier-owned, transactional simulation. Only explicit projections leave it."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any


class MarketError(ValueError):
    """An error that is safe to return to a buyer or negotiating agent."""

    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False)


def _money(value: Any) -> Decimal:
    try:
        number = Decimal(str(value))
        if not number.is_finite() or number < 0 or number > Decimal("1000000000"):
            raise InvalidOperation
        return number.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError, TypeError):
        raise MarketError("invalid_amount", "Use a finite, nonnegative monetary amount.") from None


def _amount(value: Any) -> str:
    return format(_money(value), ".2f")


def _integer(value: Any, name: str, minimum: int = 1) -> int:
    if isinstance(value, bool):
        raise MarketError("invalid_quantity", f"{name} must be an integer of at least {minimum}.")
    try:
        number = int(value)
        if Decimal(str(value)) != number or number < minimum or number > 1000000:
            raise ValueError
        return number
    except (ValueError, TypeError, InvalidOperation, OverflowError):
        raise MarketError("invalid_quantity", f"{name} must be an integer of at least {minimum}.") from None


def _text(value: Any, name: str, limit: int = 500) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise MarketError("invalid_input", f"{name} must be nonempty text, at most {limit} characters.")
    return value.strip()


def _coverage(value: Any) -> Decimal:
    """Exact positive conversion/coverage, separate from two-decimal currency."""
    try:
        number = Decimal(str(value))
        if not number.is_finite() or not 0 < number <= Decimal("1000000000"):
            raise InvalidOperation
        return number
    except (InvalidOperation, ValueError, TypeError):
        raise MarketError("invalid_conversion", "Coverage must be a finite positive decimal.") from None


def _decimal_text(value: Decimal) -> str:
    return format(value, "f")


class Market:
    """A frozen scenario per run, with separate public and private records.

    Every mutation uses BEGIN IMMEDIATE so acceptances across web/mail/processes
    cannot oversell stock or delivery capacity. Reset creates a new run and never
    deletes the evidence from an earlier trial.
    """

    def __init__(self, db_path: str | Path, scenario_path: str | Path | None = None):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        path = Path(scenario_path) if scenario_path else Path(__file__).parent / "fixtures/demo.json"
        self.scenario = json.loads(path.read_text())
        self._validate_scenario(self.scenario)
        with self._db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS market_runs (
                    id TEXT PRIMARY KEY, buyer_id TEXT NOT NULL, buyer_type TEXT NOT NULL,
                    policy TEXT NOT NULL, scenario_version TEXT NOT NULL,
                    created_at TEXT NOT NULL, snapshot TEXT NOT NULL, parent_run_id TEXT
                );
                CREATE TABLE IF NOT EXISTS market_stock (
                    run_id TEXT NOT NULL, vendor_id TEXT NOT NULL, product_id TEXT NOT NULL,
                    available INTEGER NOT NULL CHECK(available >= 0),
                    PRIMARY KEY(run_id, vendor_id, product_id)
                );
                CREATE TABLE IF NOT EXISTS market_capacity (
                    run_id TEXT NOT NULL, vendor_id TEXT NOT NULL, slot_id TEXT NOT NULL,
                    available INTEGER NOT NULL CHECK(available >= 0),
                    PRIMARY KEY(run_id, vendor_id, slot_id)
                );
                CREATE TABLE IF NOT EXISTS market_offers (
                    id TEXT PRIMARY KEY, run_id TEXT NOT NULL, vendor_id TEXT NOT NULL,
                    buyer_id TEXT NOT NULL, request_id TEXT NOT NULL, revision INTEGER NOT NULL,
                    status TEXT NOT NULL, expires_at TEXT NOT NULL, body TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS market_approvals (
                    id TEXT PRIMARY KEY, run_id TEXT NOT NULL, buyer_id TEXT NOT NULL,
                    requirement_id TEXT NOT NULL, product_id TEXT NOT NULL, body TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS market_events (
                    id TEXT PRIMARY KEY, run_id TEXT NOT NULL, kind TEXT NOT NULL,
                    created_at TEXT NOT NULL, public_body TEXT NOT NULL, private_body TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS market_pauses (
                    run_id TEXT NOT NULL, vendor_id TEXT NOT NULL, paused INTEGER NOT NULL,
                    PRIMARY KEY(run_id, vendor_id)
                );
                CREATE INDEX IF NOT EXISTS market_offer_run ON market_offers(run_id);
                CREATE INDEX IF NOT EXISTS market_event_run ON market_events(run_id);
            """)
        self.db_path.chmod(0o600)

    @contextmanager
    def _db(self, write: bool = False):
        db = sqlite3.connect(self.db_path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            if write:
                db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def _validate_scenario(scenario: dict) -> None:
        if scenario.get("simulated") is not True or scenario.get("currency") != "USD":
            raise ValueError("Scenarios must explicitly be simulated and use USD.")
        _text(scenario.get("id"), "scenario id")
        _text(scenario.get("version"), "scenario version")
        _integer(scenario.get("quote_ttl_seconds"), "quote TTL")
        requirements = {r["id"]: r for r in scenario["requirements"]}
        if len(requirements) != len(scenario["requirements"]) or not requirements:
            raise ValueError("Requirements must have unique identifiers.")
        for req in requirements.values():
            _integer(req["quantity"], "requirement quantity")
            _text(req["unit"], "requirement unit")
            variants = req.get("required_variants", {})
            if not isinstance(variants, dict):
                raise ValueError("Required variants must map variant names to required coverage.")
            for variant, quantity in variants.items():
                _text(variant, "variant")
                _coverage(quantity)
            if sum((_coverage(v) for v in variants.values()), Decimal(0)) > req["quantity"]:
                raise ValueError("Variant quantities cannot exceed the total requirement.")
        vendors = set()
        product_ids = set()
        for vendor in scenario["vendors"]:
            if vendor["id"] in vendors:
                raise ValueError("Vendor identifiers must be unique.")
            vendors.add(vendor["id"])
            rules = vendor["private"]
            if not 0 <= _money(rules["max_discount_percent"]) <= 100:
                raise ValueError("Invalid discount bound.")
            _money(rules["min_margin_percent"])
            _money(rules["delivery_cost"])
            slots = set()
            for slot in vendor["slots"]:
                if slot["id"] in slots:
                    raise ValueError("Duplicate delivery slot.")
                slots.add(slot["id"])
                _integer(slot["days"], "delivery days", 0)
                _integer(slot["capacity"], "delivery capacity", 0)
                _money(slot["fee"])
            if not slots:
                raise ValueError("A supplier needs at least one delivery option.")
            for product in vendor["products"]:
                if product["id"] in product_ids:
                    raise ValueError("Product identifiers must be globally unique.")
                product_ids.add(product["id"])
                if product["requirement_id"] not in requirements:
                    raise ValueError("Unknown requirement for product.")
                if product.get("substitution_for") not in (None, product["requirement_id"]):
                    raise ValueError("Substitution must reference the product's requirement.")
                req = requirements[product["requirement_id"]]
                if product["unit"] != req["unit"] and "units_per_sale_unit" not in product:
                    raise ValueError("Different selling units require an explicit coverage conversion.")
                _coverage(product.get("units_per_sale_unit", "1"))
                if product.get("requirement_unit", req["unit"]) != req["unit"]:
                    raise ValueError("Product conversion must target the requirement unit.")
                if req.get("required_variants") and product.get("variant") not in req["required_variants"]:
                    raise ValueError("Products must identify a required variant.")
                if not product.get("substitution_for") and any(
                    product["specifications"].get(k) != v for k, v in req["specifications"].items()
                ):
                    raise ValueError("A nonmatching specification must be labeled as a substitution.")
                _integer(product["stock"], "stock", 0)
                _integer(product["minimum_quantity"], "minimum quantity")
                _integer(product["pack_size"], "pack size")
                _money(product["list_price"])
                _money(product["private"]["unit_cost"])
            local_ids = {p["id"] for p in vendor["products"]}
            codes = set()
            for discount in vendor.get("discounts", []):
                if discount["code"] in codes:
                    raise ValueError("Duplicate discount code.")
                codes.add(discount["code"])
                if not set(discount["required_products"]) <= local_ids:
                    raise ValueError("Discount references an unknown product.")
                if discount.get("delivery_slot") and discount["delivery_slot"] not in slots:
                    raise ValueError("Discount references an unknown delivery slot.")
                _integer(discount["min_units"], "discount minimum", 0)
                if not 0 <= _money(discount["percent"]) <= 100:
                    raise ValueError("Invalid discount percentage.")

    @staticmethod
    def _run(db, run_id: str, buyer_id: str | None = None) -> sqlite3.Row:
        run_id = _text(run_id, "run id")
        run = db.execute("SELECT * FROM market_runs WHERE id=?", (run_id,)).fetchone()
        if run is None or (buyer_id is not None and run["buyer_id"] != buyer_id):
            raise MarketError("not_found", "Run not found.", 404)
        return run

    @staticmethod
    def _vendor(snapshot: dict, vendor_id: str) -> dict:
        for vendor in snapshot["vendors"]:
            if vendor["id"] == vendor_id:
                return vendor
        raise MarketError("not_found", "Supplier not found.", 404)

    @staticmethod
    def _vendor_public(vendor: dict) -> dict:
        return {k: vendor[k] for k in ("id", "name", "channel", "description")}

    @staticmethod
    def _event(db, run_id: str, kind: str, public: dict, private: dict | None = None) -> str:
        event_id = _id("event")
        db.execute("INSERT INTO market_events VALUES(?,?,?,?,?,?)", (
            event_id, run_id, kind, _now().isoformat(), _json(public), _json(private or {}),
        ))
        return event_id

    def list_vendors(self) -> list[dict]:
        return [self._vendor_public(v) for v in self.scenario["vendors"]]

    def create_run(self, buyer_id: str, buyer_type: str = "agent", policy: str = "baseline") -> dict:
        return self._create_run(self.scenario, buyer_id, buyer_type, policy)

    def _create_run(self, snapshot, buyer_id, buyer_type, policy, parent_run_id=None) -> dict:
        buyer_id = _text(buyer_id, "buyer id")
        if buyer_type not in {"agent", "human", "opening-baseline", "development"}:
            raise MarketError("invalid_input", "Unknown buyer type.")
        if policy not in {"baseline", "collaboration"}:
            raise MarketError("invalid_input", "Unknown supplier policy.")
        frozen = _json(snapshot)
        version = snapshot["version"] + ":" + hashlib.sha256(frozen.encode()).hexdigest()[:16]
        run_id = _id("run")
        with self._db(True) as db:
            db.execute("INSERT INTO market_runs VALUES(?,?,?,?,?,?,?,?)", (
                run_id, buyer_id, buyer_type, policy, version, _now().isoformat(), frozen, parent_run_id,
            ))
            for vendor in snapshot["vendors"]:
                db.executemany("INSERT INTO market_stock VALUES(?,?,?,?)", [
                    (run_id, vendor["id"], p["id"], p["stock"]) for p in vendor["products"]
                ])
                db.executemany("INSERT INTO market_capacity VALUES(?,?,?,?)", [
                    (run_id, vendor["id"], slot["id"], slot["capacity"]) for slot in vendor["slots"]
                ])
            self._event(db, run_id, "run_started", {"scenario_version": version, "simulated": True})
        return self.get_run(run_id)

    def get_run(self, run_id: str) -> dict:
        with self._db() as db:
            run = self._run(db, run_id)
            public = {key: run[key] for key in (
                "id", "buyer_id", "buyer_type", "policy", "scenario_version", "created_at", "parent_run_id"
            )}
            snapshot = json.loads(run["snapshot"])
            public.update(simulated=True, scenario_label=snapshot["label"],
                          tax_treatment=snapshot.get("tax_treatment", "unknown/not_modeled"),
                          requirements=snapshot["requirements"],
                          vendors=[self._vendor_public(v) for v in snapshot["vendors"]])
            return public

    def reset_run(self, run_id: str) -> dict:
        with self._db() as db:
            row = dict(self._run(db, run_id))
        return self._create_run(json.loads(row["snapshot"]), row["buyer_id"], row["buyer_type"],
                                row["policy"], parent_run_id=run_id)

    def catalog(self, run_id: str, vendor_id: str, query: str = "") -> dict:
        if not isinstance(query, str) or len(query) > 500:
            raise MarketError("invalid_input", "Search must be text of at most 500 characters.")
        with self._db() as db:
            run = self._run(db, run_id)
            snapshot = json.loads(run["snapshot"])
            vendor = self._vendor(snapshot, vendor_id)
            requirements = {r["id"]: r for r in snapshot["requirements"]}
            products = []
            for product in vendor["products"]:
                public = {k: product.get(k) for k in (
                    "id", "name", "requirement_id", "specifications", "unit", "pack_size",
                    "list_price", "minimum_quantity", "substitution_for", "alternatives"
                )}
                public.update(
                    units_per_sale_unit=_decimal_text(_coverage(product.get("units_per_sale_unit", "1"))),
                    requirement_unit=requirements[product["requirement_id"]]["unit"],
                    variant=product.get("variant"),
                )
                for field in ("product_info_ref", "evidence_kind", "eligibility",
                              "unresolved_clarifications", "related_requirements", "substitution_difference"):
                    if field in product:
                        public[field] = product[field]
                public["stock"] = db.execute(
                    "SELECT available FROM market_stock WHERE run_id=? AND vendor_id=? AND product_id=?",
                    (run_id, vendor_id, product["id"]),
                ).fetchone()[0]
                public["source"] = f"catalog:{vendor_id}:{product['id']}:{run['scenario_version']}"
                if not query or query.casefold() in _json(public).casefold():
                    products.append(public)
            slots = []
            for slot in vendor["slots"]:
                public = {k: slot[k] for k in ("id", "label", "days", "fee")}
                for field in ("delivery_date", "delivery_zone", "quote_basis", "needs_deadline_approval"):
                    if field in slot:
                        public[field] = slot[field]
                public["capacity"] = db.execute(
                    "SELECT available FROM market_capacity WHERE run_id=? AND vendor_id=? AND slot_id=?",
                    (run_id, vendor_id, slot["id"]),
                ).fetchone()[0]
                slots.append(public)
            discounts = [{k: d[k] for k in (
                "code", "description", "required_products", "min_units", "delivery_slot"
            ) if k in d} for d in vendor.get("discounts", [])]
            return {"vendor": self._vendor_public(vendor), "products": products,
                    "delivery_slots": slots, "discounts": discounts,
                    "currency": snapshot["currency"], "simulated": True,
                    "tax_treatment": snapshot.get("tax_treatment", "unknown/not_modeled")}

    def inquire(self, run_id: str, vendor_id: str, buyer_id: str, message: str,
                channel: str = "website", request_id: str | None = None) -> dict:
        _text(message, "message", 20000)
        with self._db() as db:
            self._run(db, run_id, buyer_id)
        catalog = self.catalog(run_id, vendor_id)
        request_id = _text(request_id, "request id") if request_id else _id("request")
        # Facts are rendered from the public catalog, never from model prose or rules.
        lines = [f"{catalog['vendor']['name']} — simulated catalog and terms."]
        for product in catalog["products"]:
            lines.append(f"{product['id']}: {product['name']}; {_json(product['specifications'])}; "
                         f"USD {product['list_price']} per {product['unit']}; "
                         f"stock {product['stock']}; minimum {product['minimum_quantity']}."
                         f" Each selling unit covers {product['units_per_sale_unit']} {product['requirement_unit']}."
                         + (" Buyer approval required for substitution." if product["substitution_for"] else ""))
        for slot in catalog["delivery_slots"]:
            lines.append(f"Delivery {slot['id']}: {slot['label']}, {slot['days']} days, USD {slot['fee']} fee.")
        lines.extend(d["description"] for d in catalog["discounts"])
        result = {**catalog, "request_id": request_id, "message": "\n".join(lines)}
        with self._db(True) as db:
            evidence = self._event(db, run_id, "inquiry", {
                "vendor_id": vendor_id, "buyer_id": buyer_id, "request_id": request_id,
                "channel": channel, "question": message, "response": result["message"],
            })
        result["evidence_id"] = evidence
        return result

    def issue_offer(self, run_id: str, vendor_id: str, buyer_id: str, proposal: dict) -> dict:
        try:
            return self._issue_offer(run_id, vendor_id, buyer_id, proposal)
        except MarketError as exc:
            with self._db(True) as db:
                self._run(db, run_id, buyer_id)
                self._event(db, run_id, "proposal_rejected", {"vendor_id": vendor_id, "code": exc.code,
                            "message": exc.message})
            raise

    def _issue_offer(self, run_id, vendor_id, buyer_id, proposal) -> dict:
        if not isinstance(proposal, dict):
            raise MarketError("invalid_input", "An offer proposal must be an object.")
        allowed = {"request_id", "lines", "delivery_slot", "discount_code", "requested_total", "previous_quote_id"}
        if proposal.keys() - allowed:
            raise MarketError("invalid_input", "Unknown proposal fields.")
        for key in ("request_id", "previous_quote_id", "delivery_slot", "discount_code"):
            if key in proposal and proposal[key] is not None:
                _text(proposal[key], key)
        with self._db(True) as db:
            run = self._run(db, run_id, buyer_id)
            snapshot = json.loads(run["snapshot"])
            vendor = self._vendor(snapshot, vendor_id)
            raw_lines = proposal.get("lines")
            if not isinstance(raw_lines, list) or not 1 <= len(raw_lines) <= 100:
                raise MarketError("invalid_input", "Specify between 1 and 100 product lines.")
            product_map = {p["id"]: p for p in vendor["products"]}
            requirements = {r["id"]: r for r in snapshot["requirements"]}
            used = set()
            lines = []
            subtotal = Decimal(0)
            private_cost = Decimal(0)
            total_units = 0
            for line in raw_lines:
                if not isinstance(line, dict) or line.keys() - {
                    "product_id", "quantity", "unit", "requirement_id", "substitution_for", "approval_ref"
                }:
                    raise MarketError("invalid_input", "Invalid product line.")
                product_id = line.get("product_id")
                if not isinstance(product_id, str) or product_id not in product_map:
                    raise MarketError("unknown_product", "The product is not in this supplier's catalog.")
                if product_id in used:
                    raise MarketError("duplicate_product", "Combine repeated products into one line.")
                used.add(product_id)
                product = product_map[product_id]
                quantity = _integer(line.get("quantity"), "quantity")
                if line.get("unit") != product["unit"]:
                    raise MarketError("unit_mismatch", f"{product_id} is sold by {product['unit']}.")
                if quantity < product["minimum_quantity"]:
                    raise MarketError("minimum_quantity", f"{product_id} requires at least {product['minimum_quantity']} units.")
                if quantity % product["pack_size"]:
                    raise MarketError("pack_size", f"Order {product_id} in multiples of {product['pack_size']} {product['unit']}.")
                for key in ("requirement_id", "substitution_for"):
                    if key in line and line[key] != product.get(key):
                        raise MarketError("incompatible_product", "Product compatibility must match the catalog.")
                available = db.execute(
                    "SELECT available FROM market_stock WHERE run_id=? AND vendor_id=? AND product_id=?",
                    (run_id, vendor_id, product_id),
                ).fetchone()[0]
                if quantity > available:
                    raise MarketError("unavailable_stock", f"Only {available} {product['unit']} of {product_id} remain.", 409)
                unit_price = _money(product["list_price"])
                line_total = unit_price * quantity
                subtotal += line_total
                private_cost += _money(product["private"]["unit_cost"]) * quantity
                total_units += quantity
                lines.append({"product_id": product_id, "name": product["name"], "quantity": quantity,
                              "unit": product["unit"], "unit_price": _amount(unit_price),
                              "line_total": _amount(line_total), "requirement_id": product["requirement_id"],
                              "units_per_sale_unit": _decimal_text(_coverage(product.get("units_per_sale_unit", "1"))),
                              "covered_quantity": _decimal_text(quantity * _coverage(product.get("units_per_sale_unit", "1"))),
                              "requirement_unit": requirements[product["requirement_id"]]["unit"],
                              "variant": product.get("variant"),
                              "substitution_for": product.get("substitution_for")})
            slot_id = proposal.get("delivery_slot")
            slot = next((s for s in vendor["slots"] if s["id"] == slot_id), None)
            if slot is None:
                raise MarketError("invalid_delivery", "Choose a published delivery slot.")
            capacity = db.execute(
                "SELECT available FROM market_capacity WHERE run_id=? AND vendor_id=? AND slot_id=?",
                (run_id, vendor_id, slot_id),
            ).fetchone()[0]
            if total_units > capacity:
                raise MarketError("delivery_capacity", "That delivery slot cannot carry this package.", 409)
            fee = _money(slot["fee"])
            total = subtotal + fee
            discounts = []
            code = proposal.get("discount_code")
            if code:
                discount = next((d for d in vendor.get("discounts", []) if d["code"] == code), None)
                if discount is None:
                    raise MarketError("invalid_discount", "Unknown package discount.")
                if (not set(discount["required_products"]) <= used or total_units < discount["min_units"]
                        or (discount.get("delivery_slot") and discount["delivery_slot"] != slot_id)):
                    raise MarketError("discount_conditions", "The package does not meet the published discount conditions.")
                savings = _money(subtotal * _money(discount["percent"]) / 100)
                total -= savings
                discounts.append({"code": code, "amount": _amount(savings), "description": discount["description"]})
            if proposal.get("requested_total") is not None:
                target = _money(proposal["requested_total"])
                if target > total:
                    raise MarketError("invalid_total", "Requested total exceeds the published package total.")
                savings = total - target
                if savings:
                    discounts.append({"code": "negotiated", "amount": _amount(savings),
                                      "description": "Negotiated reduction on this complete package."})
                total = target
            rules = vendor["private"]
            floor = max(
                _money(subtotal * (1 - _money(rules["max_discount_percent"]) / 100) + fee),
                _money((private_cost + _money(rules["delivery_cost"])) * (1 + _money(rules["min_margin_percent"]) / 100)),
            )
            if total < floor:
                # Never expose numeric thresholds, costs, or owner strategy.
                raise MarketError("commercial_terms", "These terms are not available. Revise the package, price, or delivery choice.", 409)
            request_id = proposal.get("request_id") or _id("request")
            request_id = _text(request_id, "request id")
            previous_id = proposal.get("previous_quote_id")
            revision = 1
            if previous_id:
                previous = self._offer(db, run_id, previous_id, buyer_id)
                if previous["vendor_id"] != vendor_id or previous["status"] != "issued":
                    raise MarketError("invalid_counter", "Only an active offer from this supplier can be countered.", 409)
                if proposal.get("request_id") and previous["request_id"] != request_id:
                    raise MarketError("invalid_counter", "A counter must reference the same request.")
                request_id = previous["request_id"]
                revision = previous["revision"] + 1
                db.execute("UPDATE market_offers SET status='countered' WHERE id=?", (previous_id,))
            now = _now()
            quote_id = _id("quote")
            conditions = ["Simulated offer; no real purchase is made.",
                          "Stock and delivery capacity are reserved only after acceptance and a final availability check.",
                          "Discounts apply only to this complete package; amounts are USD."]
            if any(line["substitution_for"] for line in lines):
                conditions.append("Substitutions require an explicit recorded buyer approval before acceptance.")
            offer = {"id": quote_id, "quote_id": quote_id, "run_id": run_id, "vendor_id": vendor_id,
                     "supplier_id": vendor_id, "buyer_id": buyer_id, "request_id": request_id,
                     "revision": revision, "previous_quote_id": previous_id, "status": "issued",
                     "lines": lines, "subtotal": _amount(subtotal), "discounts": discounts,
                     "fees": [{"name": "delivery", "amount": _amount(fee)}], "total": _amount(total),
                     "currency": snapshot["currency"], "delivery_slot": slot_id,
                     "tax_treatment": snapshot.get("tax_treatment", "unknown/not_modeled"),
                     "delivery": {"slot_id": slot_id, "label": slot["label"], "days": slot["days"]},
                     "created_at": now.isoformat(),
                     "expires_at": (now + timedelta(seconds=snapshot["quote_ttl_seconds"])).isoformat(),
                     "conditions": conditions, "simulated": True}
            event_id = self._event(db, run_id, "offer_issued", {"quote_id": quote_id, "vendor_id": vendor_id},
                                  {"cost": _amount(private_cost), "minimum_total": _amount(floor)})
            offer["evidence_refs"] = [event_id]
            db.execute("INSERT INTO market_offers VALUES(?,?,?,?,?,?,?,?,?)", (
                quote_id, run_id, vendor_id, buyer_id, request_id, revision, "issued", offer["expires_at"], _json(offer),
            ))
            return offer

    @staticmethod
    def _offer(db, run_id: str, quote_id: str, buyer_id: str) -> dict:
        quote_id = _text(quote_id, "quote id")
        row = db.execute("SELECT * FROM market_offers WHERE id=? AND run_id=? AND buyer_id=?",
                         (quote_id, run_id, buyer_id)).fetchone()
        if row is None:
            raise MarketError("not_found", "Offer not found.", 404)
        offer = json.loads(row["body"])
        offer["status"] = row["status"]
        if offer["status"] == "issued" and datetime.fromisoformat(row["expires_at"]) <= _now():
            offer["status"] = "expired"
        return offer

    def get_offer(self, run_id: str, quote_id: str, buyer_id: str) -> dict:
        with self._db() as db:
            self._run(db, run_id, buyer_id)
            return self._offer(db, run_id, quote_id, buyer_id)

    def record_approval(self, run_id: str, buyer_id: str, requirement_id: str,
                        product_id: str, source_ref: str) -> dict:
        source_ref = _text(source_ref, "decision source reference", 2000)
        with self._db(True) as db:
            run = self._run(db, run_id, buyer_id)
            snapshot = json.loads(run["snapshot"])
            product = next((p for v in snapshot["vendors"] for p in v["products"] if p["id"] == product_id), None)
            if product is None or product.get("substitution_for") != requirement_id:
                raise MarketError("invalid_approval", "This is not a proposed substitution for that requirement.")
            approval = {"id": _id("approval"), "run_id": run_id, "buyer_id": buyer_id,
                        "requirement_id": requirement_id, "product_id": product_id,
                        "decision": "approved", "source_ref": source_ref, "created_at": _now().isoformat()}
            db.execute("INSERT INTO market_approvals VALUES(?,?,?,?,?,?)", (
                approval["id"], run_id, buyer_id, requirement_id, product_id, _json(approval),
            ))
            self._event(db, run_id, "substitution_approved", approval)
            return approval

    def reject_offer(self, run_id: str, quote_id: str, buyer_id: str) -> dict:
        with self._db(True) as db:
            self._run(db, run_id, buyer_id)
            offer = self._offer(db, run_id, quote_id, buyer_id)
            if offer["status"] == "rejected":
                return offer
            if offer["status"] != "issued":
                raise MarketError("inactive_offer", "Only a current offer can be rejected.", 409)
            db.execute("UPDATE market_offers SET status='rejected' WHERE id=?", (quote_id,))
            self._event(db, run_id, "offer_rejected", {"quote_id": quote_id})
            offer["status"] = "rejected"
            return offer

    def accept_offer(self, run_id: str, quote_id: str, buyer_id: str,
                     approval_refs: list[str] | None = None) -> dict:
        if approval_refs is not None and (not isinstance(approval_refs, list) or
                                         not all(isinstance(ref, str) for ref in approval_refs)):
            raise MarketError("invalid_approval", "Approval references must be a list of decision identifiers.")
        with self._db(True) as db:
            self._run(db, run_id, buyer_id)
            offer = self._offer(db, run_id, quote_id, buyer_id)
            if offer["status"] == "accepted":
                return offer
            if offer["status"] != "issued":
                raise MarketError("inactive_offer", "Only a current, unexpired offer can be accepted.", 409)
            for line in offer["lines"]:
                if line["substitution_for"]:
                    valid = False
                    for ref in approval_refs or []:
                        valid = valid or db.execute(
                            "SELECT 1 FROM market_approvals WHERE id=? AND run_id=? AND buyer_id=? "
                            "AND requirement_id=? AND product_id=?",
                            (ref, run_id, buyer_id, line["substitution_for"], line["product_id"]),
                        ).fetchone() is not None
                    if not valid:
                        raise MarketError("approval_required", "Record explicit buyer approval of the proposed substitution.", 409)
                update = db.execute(
                    "UPDATE market_stock SET available=available-? WHERE run_id=? AND vendor_id=? "
                    "AND product_id=? AND available>=?", (line["quantity"], run_id, offer["vendor_id"],
                                                           line["product_id"], line["quantity"]),
                )
                if update.rowcount != 1:
                    raise MarketError("unavailable_stock", "Stock changed; request a revised offer.", 409)
            units = sum(line["quantity"] for line in offer["lines"])
            update = db.execute("UPDATE market_capacity SET available=available-? "
                                "WHERE run_id=? AND vendor_id=? AND slot_id=? AND available>=?",
                                (units, run_id, offer["vendor_id"], offer["delivery_slot"], units))
            if update.rowcount != 1:
                raise MarketError("delivery_capacity", "Delivery capacity changed; request a revised offer.", 409)
            commitment_id = _id("commitment")
            offer.update(status="accepted", accepted_at=_now().isoformat(), commitment_id=commitment_id,
                         approval_refs=approval_refs or [])
            offer["draft_order"] = {"id": commitment_id, "quote_id": quote_id, "revision": offer["revision"],
                                    "supplier_id": offer["vendor_id"], "lines": offer["lines"],
                                    "total": offer["total"], "currency": offer["currency"],
                                    "tax_treatment": offer.get("tax_treatment", "unknown/not_modeled"),
                                    "delivery": offer["delivery"], "status": "simulated_commitment"}
            offer["tasks"] = [{"id": commitment_id + "_fulfill", "title": "Prepare simulated material package",
                               "quote_id": quote_id, "status": "pending", "simulated": True}]
            evidence = self._event(db, run_id, "offer_accepted", {
                "quote_id": quote_id, "commitment_id": commitment_id, "total": offer["total"],
                "approval_refs": approval_refs or [],
            })
            offer["evidence_refs"].append(evidence)
            db.execute("UPDATE market_offers SET status='accepted',body=? WHERE id=?", (_json(offer), quote_id))
            return offer

    def set_paused(self, run_id: str, vendor_id: str, paused: bool) -> dict:
        if not isinstance(paused, bool):
            raise MarketError("invalid_input", "paused must be a boolean.")
        with self._db(True) as db:
            run = self._run(db, run_id)
            self._vendor(json.loads(run["snapshot"]), vendor_id)
            db.execute("INSERT INTO market_pauses VALUES(?,?,?) ON CONFLICT(run_id,vendor_id) "
                       "DO UPDATE SET paused=excluded.paused", (run_id, vendor_id, int(paused)))
            self._event(db, run_id, "supplier_paused" if paused else "supplier_resumed", {"vendor_id": vendor_id})
        return {"run_id": run_id, "vendor_id": vendor_id, "paused": paused}

    def is_paused(self, run_id: str, vendor_id: str) -> bool:
        with self._db() as db:
            self._run(db, run_id)
            row = db.execute("SELECT paused FROM market_pauses WHERE run_id=? AND vendor_id=?",
                             (run_id, vendor_id)).fetchone()
            return bool(row and row[0])

    def export_run(self, run_id: str, private: bool = False) -> dict:
        run = self.get_run(run_id)
        with self._db() as db:
            ids = db.execute("SELECT id FROM market_offers WHERE run_id=? ORDER BY rowid", (run_id,)).fetchall()
            offers = [self._offer(db, run_id, row[0], run["buyer_id"]) for row in ids]
            events = []
            for event in db.execute("SELECT * FROM market_events WHERE run_id=? ORDER BY rowid", (run_id,)):
                public = {"id": event["id"], "kind": event["kind"], "created_at": event["created_at"],
                          "data": json.loads(event["public_body"])}
                if private:
                    public["private"] = json.loads(event["private_body"])
                events.append(public)
            approvals = [json.loads(row[0]) for row in db.execute(
                "SELECT body FROM market_approvals WHERE run_id=?", (run_id,))]
            result = {"run": run, "offers": offers, "approvals": approvals, "events": events,
                      "evidence_kind": "simulated_business_records", "live_transport_verified": False}
            if private:
                result["private_scenario"] = json.loads(self._run(db, run_id)["snapshot"])
            return result

    def score_plan(self, run_id: str, buyer_id: str, quote_ids: list[str],
                   max_delivery_days: int | None = None) -> dict:
        """Validate a submitted plan against issued evidence, not secret floors.

        A plan can contain issued or simulated-accepted offers. Historical terms
        are assessed at the submitted run's evidence; expired offers are invalid.
        Human attention and elapsed time are evaluator inputs, never invented.
        """
        if not isinstance(quote_ids, list) or not all(isinstance(q, str) for q in quote_ids):
            raise MarketError("invalid_input", "quote_ids must be a list of identifiers.")
        if max_delivery_days is not None:
            max_delivery_days = _integer(max_delivery_days, "maximum delivery days", 0)
        run = self.get_run(run_id)
        if run["buyer_id"] != buyer_id:
            raise MarketError("not_found", "Run not found.", 404)
        failures = []
        totals = {r["id"]: Decimal(0) for r in run["requirements"]}
        variant_totals: dict[tuple[str, str], Decimal] = {}
        cost = Decimal(0)
        seen = set()
        stock_needed: dict[tuple[str, str], int] = {}
        capacity_needed: dict[tuple[str, str], int] = {}
        with self._db() as db:
            # Score a consistent snapshot while other workers may accept offers.
            db.execute("BEGIN")
            for quote_id in quote_ids:
                if quote_id in seen:
                    failures.append("duplicate_quote")
                    continue
                seen.add(quote_id)
                try:
                    offer = self._offer(db, run_id, quote_id, buyer_id)
                except MarketError:
                    failures.append("unknown_quote")
                    continue
                if offer["status"] not in {"issued", "accepted"}:
                    failures.append("inactive_offer")
                if max_delivery_days is not None and offer["delivery"]["days"] > max_delivery_days:
                    failures.append("late_delivery")
                cost += _money(offer["total"])
                for line in offer["lines"]:
                    covered = _coverage(line.get("covered_quantity", line["quantity"]))
                    totals[line["requirement_id"]] += covered
                    if line.get("variant"):
                        variant_key = (line["requirement_id"], line["variant"])
                        variant_totals[variant_key] = variant_totals.get(variant_key, Decimal(0)) + covered
                    if offer["status"] == "issued":
                        stock_key = (offer["vendor_id"], line["product_id"])
                        stock_needed[stock_key] = stock_needed.get(stock_key, 0) + line["quantity"]
                        slot_key = (offer["vendor_id"], offer["delivery_slot"])
                        capacity_needed[slot_key] = capacity_needed.get(slot_key, 0) + line["quantity"]
                    if line["substitution_for"] and not db.execute(
                        "SELECT 1 FROM market_approvals WHERE run_id=? AND buyer_id=? AND requirement_id=? AND product_id=?",
                        (run_id, buyer_id, line["substitution_for"], line["product_id"]),
                    ).fetchone():
                        failures.append("unapproved_substitution")
            for (vendor_id, product_id), quantity in stock_needed.items():
                available = db.execute(
                    "SELECT available FROM market_stock WHERE run_id=? AND vendor_id=? AND product_id=?",
                    (run_id, vendor_id, product_id),
                ).fetchone()[0]
                if quantity > available:
                    failures.append("unavailable_stock:" + product_id)
            for (vendor_id, slot_id), quantity in capacity_needed.items():
                available = db.execute(
                    "SELECT available FROM market_capacity WHERE run_id=? AND vendor_id=? AND slot_id=?",
                    (run_id, vendor_id, slot_id),
                ).fetchone()[0]
                if quantity > available:
                    failures.append("delivery_capacity:" + vendor_id + ":" + slot_id)
            for requirement in run["requirements"]:
                if totals[requirement["id"]] < requirement["quantity"]:
                    failures.append("missing_quantity:" + requirement["id"])
                for variant, required in requirement.get("required_variants", {}).items():
                    if variant_totals.get((requirement["id"], variant), Decimal(0)) < _coverage(required):
                        failures.append("missing_variant:" + requirement["id"] + ":" + variant)
        result = {"run_id": run_id, "quote_ids": quote_ids, "valid": not failures,
                  "validation_scope": "commercial_terms_and_material_coverage",
                  "contractor_clarifications": [dict(c, requirement_id=r["id"])
                      for r in run["requirements"] for c in r.get("unresolved_clarifications", [])
                      if c.get("status") == "unresolved"],
                  "failures": sorted(set(failures)), "delivered_cost": _amount(cost), "currency": "USD",
                  "quantities": {key: int(value) if value == value.to_integral_value() else _decimal_text(value)
                                 for key, value in totals.items()},
                  "variant_quantities": {r["id"]: {variant: _decimal_text(variant_totals.get((r["id"], variant), Decimal(0)))
                                                   for variant in r["required_variants"]}
                                         for r in run["requirements"] if r.get("required_variants")},
                  "tax_treatment": run["tax_treatment"],
                  "scored_at": _now().isoformat(), "simulated": True}
        with self._db(True) as db:
            self._event(db, run_id, "plan_scored", result)
        return result
