"""Buyer HTTP boundaries and the actual browser request-to-agreement journey."""
import re

import pytest
from fastapi.testclient import TestClient

from takeoff_suppliers.core import Market
from takeoff_suppliers.web import create_app


@pytest.fixture
def setup(tmp_path):
    market = Market(tmp_path / "market.sqlite")
    run = market.create_run("demo-buyer")
    app = create_app(market, "operator-secret", "buyer-secret")
    client = TestClient(app, raise_server_exceptions=False)
    return market, run, client


def csrf(text):
    return re.search("name='csrf' value='([^']+)'", text).group(1)


def selection(market, run):
    vendor = market.list_vendors()[0]["id"]
    catalog = market.catalog(run["id"], vendor)
    lines = [{"product_id": p["id"], "quantity": max(p["minimum_quantity"], p["pack_size"]), "unit": p["unit"]}
             for p in catalog["products"] if not p.get("substitution_for")]
    return vendor, catalog, {"request_id": "browser-trial", "lines": lines, "delivery_slot": catalog["delivery_slots"][0]["id"]}


def test_auth_and_run_isolation(setup):
    market, run, client = setup
    path = f"/v1/runs/{run['id']}/vendors"
    assert client.get(path).status_code == 401
    headers = {"Authorization": "Bearer buyer-secret"}
    assert client.get(path, headers=headers).status_code == 200
    other = market.create_run("different-buyer")
    assert client.get(f"/v1/runs/{other['id']}/vendors", headers=headers).status_code == 404
    assert client.get(f"/v1/runs/{run['id']}/export?private=true", headers=headers).status_code == 401
    assert client.post("/v1/runs", json={}, headers=headers).status_code == 401
    assert client.post("/v1/runs", json={"buyer_id": "spoof"}, headers={"Authorization": "Bearer operator-secret"}).status_code == 422


def test_public_catalog_and_quote_acceptance(setup):
    market, run, client = setup
    vendor, catalog, proposal = selection(market, run)
    base = f"/v1/runs/{run['id']}"
    headers = {"Authorization": "Bearer buyer-secret"}
    response = client.get(f"{base}/vendors/{vendor}/catalog", headers=headers)
    assert response.status_code == 200
    for private in ("floor_price", "cost_price", "reservation_price", "private_rules"):
        assert private not in response.text
    offer = client.post(f"{base}/vendors/{vendor}/offers", json=proposal, headers=headers)
    assert offer.status_code == 201, offer.text
    qid = offer.json()["quote_id"]
    accepted = client.post(f"{base}/offers/{qid}/accept", json={}, headers=headers)
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["status"] == "accepted"
    assert accepted.json()["total"] == offer.json()["total"]


def test_browser_shopping_and_csrf(setup):
    market, run, client = setup
    vendor, catalog, proposal = selection(market, run)
    assert client.get("/").status_code == 200
    login = client.post("/login", data={"token": "buyer-secret", "run_id": run["id"]})
    assert login.status_code == 200, login.text
    assert "buyer-secret" not in login.text
    path = f"/runs/{run['id']}/vendors/{vendor}"
    page = client.get(path)
    assert page.status_code == 200
    assert "Request an offer" in page.text
    assert "HttpOnly" in client.post("/login", data={"token": "buyer-secret", "run_id": run["id"]}, follow_redirects=False).headers["set-cookie"]
    page = client.get(path)
    assert client.post(path + "/inquiries", data={"message": "Delivery?"}).status_code == 403
    response = client.post(path + "/inquiries", data={"csrf": csrf(page.text), "message": "What delivery choices are available?"})
    assert response.status_code == 200, response.text
    values = {"csrf": csrf(page.text), "request_id": "human-trial", "delivery_slot": proposal["delivery_slot"]}
    values.update({"quantity:" + line["product_id"]: str(line["quantity"]) for line in proposal["lines"]})
    quoted = client.post(path + "/offers", data=values)
    assert quoted.status_code == 200, quoted.text
    assert "Inspect offer" in quoted.text
    accepted = client.post(str(quoted.url) + "/accept", data={"csrf": csrf(quoted.text)})
    assert accepted.status_code == 200, accepted.text
    assert "Recorded agreement" in accepted.text


def test_browser_substitution_needs_explicit_decision(setup):
    market, run, client = setup
    catalog = market.catalog(run["id"], "local")
    product = next(p for p in catalog["products"] if p.get("substitution_for"))
    offer = market.issue_offer(run["id"], "local", "demo-buyer", {
        "request_id": "substitution", "delivery_slot": catalog["delivery_slots"][0]["id"],
        "lines": [{"product_id": product["id"], "quantity": max(product["minimum_quantity"], product["pack_size"]), "unit": product["unit"]}],
    })
    client.post("/login", data={"token": "buyer-secret", "run_id": run["id"]})
    path = f"/runs/{run['id']}/offers/{offer['quote_id']}"
    page = client.get(path)
    assert "I explicitly approve" in page.text
    assert client.post(path + "/accept", data={"csrf": csrf(page.text)}).status_code in (400, 409, 422)
    result = client.post(path + "/accept", data={"csrf": csrf(page.text), "approve:" + product["id"]: "yes"})
    assert result.status_code == 200, result.text
    assert "Recorded agreement" in result.text


def test_malformed_browser_inputs_are_client_errors(setup):
    _, run, client = setup
    assert client.post("/login", data={"token": "🔑", "run_id": run["id"]}).status_code == 401
    assert client.post("/login", content=b"token=\xff").status_code == 400
    assert client.post("/login", content=b"", headers={"Content-Length": "bad"}).status_code == 400
    client.post("/login", data={"token": "buyer-secret", "run_id": run["id"]})
    path = f"/runs/{run['id']}/vendors/general/inquiries"
    assert client.post(path, data={"csrf": "🔑", "message": "Delivery?"}).status_code == 403


@pytest.mark.parametrize("overrides", [
    {"previous_quote_id": {"id": "unexpected"}},
    {"previous_quote_id": ["unexpected"]},
    {"lines": [{"product_id": ["general-stud"], "quantity": 1, "unit": "each"}]},
    {"lines": [{"product_id": "general-stud", "quantity": {}, "unit": "each"}]},
    {"requested_total": {"amount": "1"}},
    {"delivery_slot": ["standard"]},
])
def test_malformed_commercial_structures_are_client_errors(setup, overrides):
    market, run, client = setup
    vendor, _, proposal = selection(market, run)
    proposal.update(overrides)
    response = client.post(f"/v1/runs/{run['id']}/vendors/{vendor}/offers", json=proposal,
                           headers={"Authorization": "Bearer buyer-secret"})
    assert 400 <= response.status_code < 500, response.text


def test_duplicate_accept_does_not_reserve_twice(setup):
    market, run, client = setup
    vendor, _, proposal = selection(market, run)
    headers = {"Authorization": "Bearer buyer-secret"}
    base = f"/v1/runs/{run['id']}"
    quoted = client.post(f"{base}/vendors/{vendor}/offers", json=proposal, headers=headers).json()
    path = f"{base}/offers/{quoted['quote_id']}/accept"
    first = client.post(path, json={}, headers=headers)
    stock_once = market.catalog(run["id"], vendor)
    second = client.post(path, json={}, headers=headers)
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert stock_once == market.catalog(run["id"], vendor)


def test_vendor_discovery_uses_frozen_trial(setup):
    market, run, client = setup
    market.scenario["vendors"][0]["name"] = "Changed after trial creation"
    response = client.get(f"/v1/runs/{run['id']}/vendors", headers={"Authorization": "Bearer buyer-secret"})
    assert response.status_code == 200
    assert response.json()["vendors"] == run["vendors"]
    client.post("/login", data={"token": "buyer-secret", "run_id": run["id"]})
    assert "Changed after trial creation" not in client.get(f"/runs/{run['id']}").text


@pytest.mark.parametrize("path", ["/docs", "/redoc"])
def test_documentation_csp_allows_its_actual_assets(setup, path):
    _, _, client = setup
    response = client.get(path)
    assert response.status_code == 200
    policy = response.headers["content-security-policy"]
    assert "script-src 'unsafe-inline' https://cdn.jsdelivr.net" in policy
    assert "connect-src 'self'" in policy
    assert "https://cdn.jsdelivr.net" in response.text
    # Catalog pages retain their original script-free restriction.
    assert "script-src" not in client.get("/").headers["content-security-policy"]


def test_market_errors_are_handled_without_server_exception_reraise(setup):
    market, run, _ = setup
    client = TestClient(create_app(market, "operator-secret", "buyer-secret"))
    response = client.post(f"/v1/runs/{run['id']}/vendors/general/offers",
                           json={"lines": []}, headers={"Authorization": "Bearer buyer-secret"})
    assert response.status_code == 400
    assert response.json()["error"] == "invalid_input"
    assert response.headers["cache-control"] == "no-store"


def test_public_discovery_requires_explicit_opt_in(setup):
    _, _, client = setup
    for path in ('/public', '/public/manifest', '/public/vendors', '/public/vendors/general/catalog'):
        assert client.get(path).status_code == 404


def test_public_discovery_is_run_scoped_readonly_and_redacts_contacts(tmp_path):
    market = Market(tmp_path / 'public.sqlite')
    run = market.create_run('demo-buyer')
    other = market.create_run('another-buyer')
    app = create_app(market, 'operator-secret', 'buyer-secret', public_run_id=run['id'],
                     public_vendor_contacts={'general': {'email': 'supplier@example.test',
                                                        'token_env': 'PRIVATE_TOKEN_NAME',
                                                        'api_key': 'DO_NOT_EXPOSE',
                                                        'user_id': 'PRIVATE_USER_ID'}})
    client = TestClient(app)
    manifest = client.get('/public/manifest')
    assert manifest.status_code == 200
    assert manifest.json()['run_id'] == run['id']
    assert manifest.json()['vendors'][0]['contact'] == {'email': 'supplier@example.test'}
    for private in ('DO_NOT_EXPOSE', 'PRIVATE_USER_ID', 'PRIVATE_TOKEN_NAME', 'floor_price', 'cost_price'):
        assert private not in manifest.text
    catalog = client.get('/public/vendors/general/catalog', params={'run_id': other['id']})
    assert catalog.status_code == 200
    assert catalog.json()['run_id'] == run['id']
    assert other['id'] not in catalog.text
    for private in ('floor_price', 'cost_price', 'reservation_price', 'private_rules'):
        assert private not in catalog.text
    product = catalog.json()['products'][0]
    filtered = client.get('/public/vendors/general/catalog', params={'query': product['id']})
    assert [p['id'] for p in filtered.json()['products']] == [product['id']]
    assert client.post('/public/vendors/general/catalog', json={}).status_code == 405
    assert client.post(f"/v1/runs/{run['id']}/vendors/general/offers", json={}).status_code == 401
    assert client.post(f"/v1/runs/{run['id']}/vendors/general/inquiries", json={'message':'Quote please'}).status_code == 401
    assert client.get(f"/v1/runs/{other['id']}/vendors/general/catalog").status_code == 401
    assert client.get('/public').status_code == 200
    page = client.get('/public/vendors/general')
    assert page.status_code == 200
    assert 'supplier@example.test' in page.text
    assert 'Request validated offer' not in page.text
    assert client.get('/public/vendors/general/products/' + product['id']).status_code == 200
    assert client.get('/public/vendors/general/products/not-a-product').status_code == 404


def test_public_run_must_belong_to_configured_buyer(tmp_path):
    market = Market(tmp_path / 'public.sqlite')
    run = market.create_run('another-buyer')
    with pytest.raises(ValueError, match='configured buyer'):
        create_app(market, 'operator', 'buyer', public_run_id=run['id'])
