"""Authenticated supplier HTTP handoff and small human shopping interface."""
from __future__ import annotations

import html
import json
import secrets
import time
from typing import Any
from urllib.parse import parse_qs, quote

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, ConfigDict, Field

from .core import MarketError


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RunInput(Input):
    buyer_type: str = "agent"
    policy: str = "baseline"


class InquiryInput(Input):
    message: str = Field(min_length=1, max_length=20000)
    request_id: str | None = None


class AcceptanceInput(Input):
    approval_refs: list[str] = Field(default_factory=list)


class PauseInput(Input):
    paused: bool


class ApprovalInput(Input):
    requirement_id: str = Field(min_length=1)
    product_id: str = Field(min_length=1)
    source_ref: str = Field(min_length=1)


def create_app(market: Any, operator_token: str, buyer_token: str,
               buyer_id: str = "demo-buyer", *, public_run_id: str | None = None,
               public_vendor_contacts: dict[str, dict[str, str]] | None = None) -> FastAPI:
    """Create an app for one configured buyer; tokens must be distinct and nonempty."""
    if not operator_token or not buyer_token or operator_token == buyer_token:
        raise ValueError("Distinct nonempty operator and buyer tokens are required")
    app = FastAPI(title="Takeoff supplier market", version="1.0.0")
    sessions: dict[str, tuple[str, float]] = {}
    if public_run_id is not None and market.get_run(public_run_id)["buyer_id"] != buyer_id:
        raise ValueError("Public discovery run must belong to the configured buyer")
    contacts = public_vendor_contacts or {}

    def same_secret(left: str, right: str) -> bool:
        # compare_digest(str, str) rejects non-ASCII attacker-controlled inputs.
        return secrets.compare_digest(left.encode("utf-8"), right.encode("utf-8"))

    @app.middleware("http")
    async def headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'"
        if request.url.path in {"/docs", "/docs/oauth2-redirect", "/redoc"}:
            # FastAPI serves these HTML shells with pinned-major CDN assets and
            # an inline Swagger bootstrap. Keep business pages script-free.
            response.headers["Content-Security-Policy"] = (
                "default-src 'none'; script-src 'unsafe-inline' https://cdn.jsdelivr.net; "
                "style-src 'unsafe-inline' https://cdn.jsdelivr.net https://fonts.googleapis.com; "
                "font-src https://fonts.gstatic.com; img-src 'self' data: https://fastapi.tiangolo.com; "
                "connect-src 'self'; worker-src blob:; form-action 'self'; frame-ancestors 'none'"
            )
        return response

    def authorize(request: Request, operator: bool = False) -> None:
        wanted = operator_token if operator else buyer_token
        supplied = request.headers.get("authorization", "")
        if not same_secret(supplied, "Bearer " + wanted):
            raise HTTPException(401, "Valid bearer token required")

    def owns(run_id: str) -> dict:
        run = market.get_run(run_id)
        if run["buyer_id"] != buyer_id:
            raise HTTPException(404, "Run not found")
        return run

    def browser(request: Request, run_id: str | None = None) -> str:
        session = sessions.get(request.cookies.get("takeoff_session", ""))
        if not session or session[1] < time.time():
            raise HTTPException(401, "Sign in at / first")
        if run_id:
            owns(run_id)
        return session[0]

    async def form(request: Request, csrf: str | None = None) -> dict[str, str]:
        try:
            size = int(request.headers.get("content-length", "0"))
        except ValueError:
            raise HTTPException(400, "Invalid content length") from None
        if size < 0:
            raise HTTPException(400, "Invalid content length")
        if size > 100000:
            raise HTTPException(413, "Form too large")
        body = await request.body()
        if len(body) > 100000:
            raise HTTPException(413, "Form too large")
        try:
            values = {k: v[-1] for k, v in parse_qs(body.decode(), keep_blank_values=True).items()}
        except UnicodeDecodeError:
            raise HTTPException(400, "Form must use UTF-8") from None
        if csrf is not None and not same_secret(values.get("csrf", ""), csrf):
            raise HTTPException(403, "Invalid form token")
        return values

    def page(title: str, content: str) -> HTMLResponse:
        return HTMLResponse("<!doctype html><html lang='en'><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width, initial-scale=1'>"
            f"<title>{esc(title)} · Takeoff</title><style>"
            "body{font:16px system-ui;background:#f3f4ef;color:#18372c;margin:0 auto;padding:32px;max-width:960px}"
            "header{border-bottom:2px solid #18372c;margin-bottom:28px}h1{font-size:32px}"
            "article,form,pre{background:white;padding:20px;border-radius:8px;margin:16px 0}"
            "label{display:block;margin:12px 0}input,select,textarea,button{font:inherit;padding:8px;max-width:95%}"
            "textarea{width:90%;min-height:90px}button{background:#18372c;color:white;border:0;border-radius:4px;cursor:pointer}"
            "a{color:#176742}table{width:100%;border-collapse:collapse}td,th{text-align:left;padding:8px;border-bottom:1px solid #ddd}"
            "pre{white-space:pre-wrap;overflow-wrap:anywhere}.muted{color:#53665c}</style>"
            "<header><strong>TAKEOFF / SUPPLIER MARKET</strong><p class='muted'>Simulated businesses · inspectable terms · no real orders</p></header>"
            f"<h1>{esc(title)}</h1>{content}</html>")

    def esc(value: Any) -> str:
        return html.escape(str(value), quote=True)

    def evidence(value: Any) -> str:
        return "<pre>" + esc(json.dumps(value, indent=2, default=str)) + "</pre>"

    def hidden(csrf: str) -> str:
        return f"<input type='hidden' name='csrf' value='{esc(csrf)}'>"

    @app.exception_handler(MarketError)
    async def market_error_handler(request: Request, exc: MarketError):
        return JSONResponse({"error": exc.code, "message": exc.message}, status_code=exc.status)

    @app.exception_handler(Exception)
    async def error_handler(request: Request, exc: Exception):
        return JSONResponse({"error": "internal_error", "message": "Supplier service failed"}, status_code=500)

    def public_run() -> dict:
        if public_run_id is None:
            raise HTTPException(404, "Public discovery is not enabled")
        return owns(public_run_id)

    def discovery_vendors() -> list[dict]:
        vendors = []
        for vendor in public_run()["vendors"]:
            vid = vendor["id"]
            contact = {k: v for k, v in contacts.get(vid, {}).items()
                       if k in {"email", "website", "agent_email"} and isinstance(v, str) and v}
            vendors.append({**vendor, "contact": contact,
                            "catalog_url": f"/public/vendors/{quote(vid, safe='')}/catalog",
                            "website_url": f"/public/vendors/{quote(vid, safe='')}"})
        return vendors

    @app.get("/public/manifest")
    def public_manifest():
        run = public_run()
        return {"schema_version": "takeoff.public-discovery.v1", "run_id": run["id"],
                "scenario_version": run["scenario_version"], "simulated": True,
                "vendors": discovery_vendors(), "vendors_url": "/public/vendors",
                "website_url": "/public",
                "interaction": "Catalog discovery is public. Use the supplier email contacts to negotiate; "
                               "HTTP inquiries, offers, and acceptance require buyer authentication."}

    @app.get("/public/vendors")
    def public_vendors():
        return {"run_id": public_run()["id"], "simulated": True, "vendors": discovery_vendors()}

    @app.get("/public/vendors/{vendor_id}/catalog")
    def public_catalog(vendor_id: str, query: str = "", q: str | None = None):
        run = public_run()
        return {"run_id": run["id"], **market.catalog(run["id"], vendor_id, query=query or q or "")}

    @app.get("/public", response_class=HTMLResponse)
    def public_directory():
        content = "<p>Browse products and delivery terms, then contact the supplier to negotiate.</p>"
        for vendor in discovery_vendors():
            content += (f"<article><h2><a href='{vendor['website_url']}'>{esc(vendor['name'])}</a></h2>"
                        f"<p>{esc(vendor['description'])}</p><p>Channel: {esc(vendor['channel'])}</p>"
                        + evidence(vendor['contact']) + "</article>")
        return page("Supplier directory", content + "<a href='/public/manifest'>Machine-readable discovery manifest</a>")

    @app.get("/public/vendors/{vendor_id}", response_class=HTMLResponse)
    def public_vendor_page(vendor_id: str, query: str = ""):
        run = public_run()
        data = market.catalog(run["id"], vendor_id, query=query)
        vendor = next(v for v in discovery_vendors() if v["id"] == vendor_id)
        content = ("<a href='/public'>All suppliers</a>" + evidence(vendor['contact']) +
                   f"<form method='get'><label>Search products <input name='query' value='{esc(query)}'></label>"
                   "<button>Search</button></form>")
        for product in data['products']:
            path = f"/public/vendors/{quote(vendor_id, safe='')}/products/{quote(product['id'], safe='')}"
            content += (f"<article><h2><a href='{path}'>{esc(product['name'])}</a></h2>"
                        f"<p>{esc(product['id'])} · {esc(data['currency'])} {esc(product['list_price'])} "
                        f"per {esc(product['unit'])} · stock {esc(product['stock'])}</p>"
                        f"<p>Pack size {esc(product['pack_size'])}; minimum {esc(product['minimum_quantity'])}.</p>"
                        + evidence(product['specifications']) + "</article>")
        content += "<h2>Delivery and package conditions</h2>" + evidence({
            'delivery_slots': data['delivery_slots'], 'discounts': data['discounts']})
        return page(data['vendor']['name'], content)

    @app.get("/public/vendors/{vendor_id}/products/{product_id}", response_class=HTMLResponse)
    def public_product_page(vendor_id: str, product_id: str):
        data = market.catalog(public_run()["id"], vendor_id)
        product = next((p for p in data['products'] if p['id'] == product_id), None)
        if product is None:
            raise HTTPException(404, "Product not found")
        return page(product['name'], evidence(product) +
                    f"<a href='/public/vendors/{quote(vendor_id, safe='')}'>Supplier contact and delivery terms</a>")

    @app.get("/health")
    def health():
        return {"status": "ok", "businesses": "simulated"}

    @app.post("/v1/runs", status_code=201)
    def new_run(body: RunInput, request: Request):
        authorize(request, True)
        return market.create_run(buyer_id, buyer_type=body.buyer_type, policy=body.policy)

    @app.get("/v1/runs/{run_id}")
    def run_details(run_id: str, request: Request):
        authorize(request)
        return owns(run_id)

    @app.post("/v1/runs/{run_id}/reset", status_code=201)
    def reset(run_id: str, request: Request):
        authorize(request, True)
        owns(run_id)
        return market.reset_run(run_id)

    @app.get("/v1/runs/{run_id}/export")
    def export(run_id: str, request: Request, private: bool = False):
        authorize(request, True)
        owns(run_id)
        return market.export_run(run_id, private=private)

    @app.post("/v1/runs/{run_id}/vendors/{vendor_id}/pause")
    def pause(run_id: str, vendor_id: str, body: PauseInput, request: Request):
        authorize(request, True)
        owns(run_id)
        return market.set_paused(run_id, vendor_id, body.paused)

    @app.get("/v1/runs/{run_id}/vendors")
    def vendors(run_id: str, request: Request):
        authorize(request)
        return {"vendors": owns(run_id)["vendors"]}

    @app.get("/v1/runs/{run_id}/vendors/{vendor_id}/catalog")
    def catalog(run_id: str, vendor_id: str, request: Request, query: str = ""):
        authorize(request)
        owns(run_id)
        return market.catalog(run_id, vendor_id, query=query)

    @app.post("/v1/runs/{run_id}/vendors/{vendor_id}/inquiries")
    def inquiry(run_id: str, vendor_id: str, body: InquiryInput, request: Request):
        authorize(request)
        owns(run_id)
        return market.inquire(run_id, vendor_id, buyer_id, body.message, channel="website", request_id=body.request_id)

    @app.post("/v1/runs/{run_id}/vendors/{vendor_id}/offers", status_code=201)
    def offer(run_id: str, vendor_id: str, body: dict, request: Request):
        authorize(request)
        owns(run_id)
        return market.issue_offer(run_id, vendor_id, buyer_id, body)

    @app.get("/v1/runs/{run_id}/offers/{quote_id}")
    def get_offer(run_id: str, quote_id: str, request: Request):
        authorize(request)
        owns(run_id)
        return market.get_offer(run_id, quote_id, buyer_id)

    @app.post("/v1/runs/{run_id}/offers/{quote_id}/accept")
    def accept(run_id: str, quote_id: str, body: AcceptanceInput, request: Request):
        authorize(request)
        owns(run_id)
        return market.accept_offer(run_id, quote_id, buyer_id, approval_refs=body.approval_refs)

    @app.post("/v1/runs/{run_id}/approvals", status_code=201)
    def approval(run_id: str, body: ApprovalInput, request: Request):
        authorize(request)
        owns(run_id)
        return market.record_approval(run_id, buyer_id, body.requirement_id, body.product_id, body.source_ref)

    @app.post("/v1/runs/{run_id}/offers/{quote_id}/reject")
    def reject(run_id: str, quote_id: str, request: Request):
        authorize(request)
        owns(run_id)
        return market.reject_offer(run_id, quote_id, buyer_id)

    @app.get("/", response_class=HTMLResponse)
    def login_page():
        return page("Supplier access", "<p>Enter the buyer access token and trial reference supplied by the operator.</p>"
            "<form action='/login' method='post'><label>Access token <input name='token' type='password' required></label>"
            "<label>Trial reference <input name='run_id' required></label><button>Browse suppliers</button></form>")

    @app.post("/login")
    async def login(request: Request):
        values = await form(request)
        if not same_secret(values.get("token", ""), buyer_token):
            raise HTTPException(401, "Invalid buyer token")
        run_id = values.get("run_id", "")
        owns(run_id)
        session_id, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        now = time.time()
        for key, value in list(sessions.items()):
            if value[1] < now:
                del sessions[key]
        sessions[session_id] = (csrf, now + 28800)
        response = RedirectResponse(f"/runs/{quote(run_id, safe='')}", status_code=303)
        response.set_cookie("takeoff_session", session_id, httponly=True, samesite="strict", secure=request.url.scheme == "https", max_age=28800)
        return response

    @app.get("/runs/{run_id}", response_class=HTMLResponse)
    def storefront(run_id: str, request: Request):
        browser(request, run_id)
        cards = ""
        for vendor in owns(run_id)["vendors"]:
            vid = vendor.get("id", vendor.get("vendor_id"))
            cards += f"<article><h2><a href='/runs/{quote(run_id)}/vendors/{quote(vid)}'>{esc(vendor.get('name', vid))}</a></h2>{evidence(vendor)}</article>"
        return page("Discover suppliers", cards)

    @app.get("/runs/{run_id}/vendors/{vendor_id}", response_class=HTMLResponse)
    def vendor_page(run_id: str, vendor_id: str, request: Request, query: str = ""):
        csrf = browser(request, run_id)
        data = market.catalog(run_id, vendor_id, query=query)
        base = f"/runs/{quote(run_id)}/vendors/{quote(vendor_id)}"
        content = f"<a href='/runs/{quote(run_id)}'>All suppliers</a><form method='get'><label>Find a product <input name='query' value='{esc(query)}'></label><button>Search</button></form>"
        content += "<table><thead><tr><th>Product</th><th>Selling terms</th><th>Stock</th></tr></thead><tbody>"
        for product in data.get("products", []):
            pid = product["id"]
            content += f"<tr><td><a href='{base}/products/{quote(pid, safe='')}'>{esc(product.get('name', pid))}</a><br><small>{esc(pid)}</small></td><td>${esc(product.get('list_price', 'unknown'))} / {esc(product['unit'])}<br>Pack size: {esc(product.get('pack_size', 'unknown'))}; minimum: {esc(product.get('minimum_quantity', 'unknown'))}</td><td>{esc(product.get('stock', 'unknown'))}</td></tr>"
        content += "</tbody></table><details><summary>Catalog evidence, delivery and discount conditions</summary>" + evidence(data) + "</details>"
        content += f"<form method='post' action='{base}/inquiries'>{hidden(csrf)}<h2>Ask the supplier</h2><textarea name='message' required placeholder='Ask about compatibility, stock, delivery or package conditions'></textarea><button>Send inquiry</button></form>"
        content += f"<form method='post' action='{base}/offers'>{hidden(csrf)}<h2>Request an offer or counter</h2><p>Enter quantities in the catalog selling units. Leave unwanted products at zero.</p>"
        for product in data.get("products", []):
            pid = product.get("id", product.get("product_id"))
            content += f"<label>{esc(product.get('name', pid))} ({esc(product.get('unit', ''))}) <input type='number' min='0' step='any' value='0' name='quantity:{esc(pid)}'></label>"
        content += "<label>Delivery <select name='delivery_slot' required>" + "".join(f"<option value='{esc(slot['id'])}'>{esc(slot['label'])} · {esc(slot['fee'])} delivery</option>" for slot in data.get("delivery_slots", [])) + "</select></label>"
        content += "<label>Request reference <input name='request_id' required></label><label>Discount code <input name='discount_code'></label><label>Counter target, total payable <input name='requested_total' type='number' min='0' step='0.01'></label><label>Previous quote reference (for counter) <input name='previous_quote_id'></label><button>Request validated offer</button></form>"
        return page(vendor_id, content)

    @app.get("/runs/{run_id}/vendors/{vendor_id}/products/{product_id}", response_class=HTMLResponse)
    def product_page(run_id: str, vendor_id: str, product_id: str, request: Request):
        browser(request, run_id)
        data = market.catalog(run_id, vendor_id)
        product = next((p for p in data.get("products", []) if p["id"] == product_id), None)
        if product is None:
            raise HTTPException(404, "Product not found")
        return page(product.get("name", product_id), evidence(product) + f"<a href='/runs/{quote(run_id)}/vendors/{quote(vendor_id)}'>Ask a question or request an offer</a>")

    @app.post("/runs/{run_id}/vendors/{vendor_id}/inquiries")
    async def browser_inquiry(run_id: str, vendor_id: str, request: Request):
        values = await form(request, browser(request, run_id))
        message = values.get("message", "").strip()
        if not message or len(message) > 20000:
            raise HTTPException(422, "Supply an inquiry of 1–20000 characters")
        result = market.inquire(run_id, vendor_id, buyer_id, message, channel="website")
        return page("Supplier response", evidence(result) + f"<a href='/runs/{quote(run_id)}/vendors/{quote(vendor_id)}'>Back to catalog and offers</a>")

    @app.post("/runs/{run_id}/vendors/{vendor_id}/offers")
    async def browser_offer(run_id: str, vendor_id: str, request: Request):
        values = await form(request, browser(request, run_id))
        data = market.catalog(run_id, vendor_id)
        lines = []
        for product in data.get("products", []):
            pid = product.get("id", product.get("product_id"))
            quantity = values.get("quantity:" + pid, "0")
            if quantity not in ("", "0", "0.0"):
                line = {"product_id": pid, "quantity": quantity, "unit": product["unit"]}
                if values.get("substitution_for"):
                    line["substitution_for"] = values["substitution_for"]
                lines.append(line)
        proposal = {"lines": lines, "request_id": values.get("request_id"), "delivery_slot": values.get("delivery_slot")}
        for field in ("discount_code", "requested_total", "previous_quote_id"):
            if values.get(field):
                proposal[field] = values[field]
        result = market.issue_offer(run_id, vendor_id, buyer_id, proposal)
        qid = result.get("quote_id", result.get("id"))
        return RedirectResponse(f"/runs/{quote(run_id)}/offers/{quote(qid)}", status_code=303)

    @app.get("/runs/{run_id}/offers/{quote_id}", response_class=HTMLResponse)
    def browser_quote(run_id: str, quote_id: str, request: Request):
        csrf = browser(request, run_id)
        result = market.get_offer(run_id, quote_id, buyer_id)
        decisions = ""
        for line in result.get("lines", []):
            if line.get("substitution_for"):
                decisions += f"<label><input type='checkbox' name='approve:{esc(line['product_id'])}' value='yes'> I explicitly approve {esc(line['product_id'])} instead of requirement {esc(line['substitution_for'])}.</label>"
        actions = ""
        if result["status"] == "issued":
            actions = f"<form method='post' action='/runs/{quote(run_id)}/offers/{quote(quote_id)}/accept'>{hidden(csrf)}{decisions}<button>Accept these exact terms (simulated)</button></form><form method='post' action='/runs/{quote(run_id)}/offers/{quote(quote_id)}/reject'>{hidden(csrf)}<button>Reject this offer</button></form>"
        return page("Inspect offer", evidence(result) + actions + f"<a href='/runs/{quote(run_id)}'>Continue comparing suppliers</a>")

    @app.post("/runs/{run_id}/offers/{quote_id}/accept")
    async def browser_accept(run_id: str, quote_id: str, request: Request):
        values = await form(request, browser(request, run_id))
        result = market.get_offer(run_id, quote_id, buyer_id)
        refs = []
        for line in result.get("lines", []):
            if line.get("substitution_for") and values.get("approve:" + line["product_id"]) == "yes":
                approval = market.record_approval(run_id, buyer_id, line["substitution_for"], line["product_id"], "website:" + quote_id)
                refs.append(approval["id"])
        result = market.accept_offer(run_id, quote_id, buyer_id, approval_refs=refs)
        return page("Recorded agreement", evidence(result) + f"<a href='/runs/{quote(run_id)}'>Continue shopping</a>")

    @app.post("/runs/{run_id}/offers/{quote_id}/reject")
    async def browser_reject(run_id: str, quote_id: str, request: Request):
        await form(request, browser(request, run_id))
        result = market.reject_offer(run_id, quote_id, buyer_id)
        return page("Offer rejected", evidence(result) + f"<a href='/runs/{quote(run_id)}'>Continue comparing suppliers</a>")

    return app
