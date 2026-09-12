"""Record sync with real commercial state and mocked supplier workspace API."""

import json

import httpx

from takeoff_suppliers.channels import AmbiguousClient, VendorConnection
from takeoff_suppliers.core import Market
from takeoff_suppliers.runtime import TransportState
from takeoff_suppliers.sync import SupplierRecordsSync


def setup(tmp_path, fail_tasks=False):
    requests = []
    def handler(request):
        requests.append(request)
        if fail_tasks and request.url.path == "/api/tasks":
            raise httpx.ReadTimeout("secret diagnostic", request=request)
        payload = json.loads(request.content)
        return httpx.Response(201, json={"id": f"artifact-{len(requests)}",
                                       "title": payload["title"], "type": payload.get("type", "sheet")})
    connections = {}
    for vendor in ("general", "local"):
        channel = AmbiguousClient(VendorConnection(vendor, "token", workspace_id="workspace", user_id=vendor),
                                  client=httpx.Client(transport=httpx.MockTransport(handler)))
        channel.identity = {"id": vendor, "workspace_id": "workspace"}
        connections[vendor] = channel
    market = Market(tmp_path / "market.db")
    run = market.create_run("buyer")
    state = TransportState(tmp_path / "transport.db")
    return SupplierRecordsSync(market, state, connections), market, run, state, requests


def accepted(market, run):
    catalog = market.catalog(run["id"], "general")
    quantities = {r["id"]: r["quantity"] for r in run["requirements"]}
    offer = market.issue_offer(run["id"], "general", "buyer", {
        "delivery_slot": catalog["delivery_slots"][0]["id"],
        "lines": [{"product_id": p["id"], "quantity": quantities[p["requirement_id"]], "unit": p["unit"]}
                  for p in catalog["products"] if p["requirement_id"] in quantities and not p.get("substitution_for")]})
    return market.accept_offer(run["id"], offer["quote_id"], "buyer")


def test_sync_publishes_configured_vendors_and_commitment_once(tmp_path):
    sync, market, run, state, requests = setup(tmp_path)
    offer = accepted(market, run)
    result = sync.sync(run["id"])
    assert result["ok"]
    assert set(result["vendors"]) == {"general", "local"}
    assert len(requests) == 6  # two catalogs, two sheets, accepted doc, task
    task = result["vendors"]["general"]["tasks"][0]["task"]
    assert state.get(f'fulfillment:{run["id"]}:general:{offer["quote_id"]}') == task
    task_payload = next(json.loads(r.content) for r in requests if r.url.path == "/api/tasks")
    assert "simulated_commitment" in task_payload["description"]
    assert "unit_cost" not in task_payload["description"]
    assert sync.sync(run["id"])["ok"]
    assert len(requests) == 6


def test_existing_worker_task_is_reused(tmp_path):
    sync, market, run, state, requests = setup(tmp_path)
    offer = accepted(market, run)
    task = {"id": "task-made-by-worker"}
    state.put(f'fulfillment:{run["id"]}:general:{offer["quote_id"]}', task)
    result = sync.sync(run["id"])
    assert result["vendors"]["general"]["tasks"][0]["task"] == task
    assert all(r.url.path != "/api/tasks" for r in requests)


def test_uncertain_task_blocks_only_that_artifact_and_never_reposts(tmp_path):
    sync, market, run, state, requests = setup(tmp_path, fail_tasks=True)
    offer = accepted(market, run)
    result = sync.sync(run["id"])
    assert not result["ok"]
    assert result["vendors"]["local"]["catalog"]
    error = result["vendors"]["general"]["errors"][0]
    assert error["operation"] == "fulfillment_task" and error["recovery_required"]
    assert "secret" not in json.dumps(result)
    assert state.get(f'fulfillment:{run["id"]}:general:{offer["quote_id"]}') == {"pending": True}
    sync.sync(run["id"])
    assert sum(r.url.path == "/api/tasks" for r in requests) == 1


def test_worker_pending_task_remains_pending(tmp_path):
    sync, market, run, state, requests = setup(tmp_path)
    offer = accepted(market, run)
    state.put(f'fulfillment:{run["id"]}:general:{offer["quote_id"]}', {"pending": True})
    assert not sync.sync(run["id"])["ok"]
    assert all(r.url.path != "/api/tasks" for r in requests)
