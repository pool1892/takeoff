"""Public record payloads against the real market and mocked Ambiguous HTTP."""

from copy import deepcopy
import json

import httpx
import pytest

from takeoff_suppliers.channels import AmbiguousClient, VendorConnection
from takeoff_suppliers.core import Market
from takeoff_suppliers.records import AmbiguousRecords
from takeoff_suppliers.runtime import RecoveryRequired, TransportState


def setup(tmp_path, handler=None):
    sent = []
    def transport(request):
        sent.append(request)
        if handler:
            return handler(request)
        body = json.loads(request.content)
        return httpx.Response(201, json={"id": f"doc-{len(sent)}", "title": body["title"],
                                       "type": body.get("type", "sheet"), "visibility": "workspace"})
    channel = AmbiguousClient(VendorConnection("general", "secret", workspace_id="supplier-workspace",
                                               user_id="supplier-user"),
                              client=httpx.Client(transport=httpx.MockTransport(transport)))
    channel.identity = {"id": "supplier-user", "workspace_id": "supplier-workspace"}
    state = TransportState(tmp_path / "state.db")
    market = Market(tmp_path / "market.db")
    run = market.create_run("buyer")
    return AmbiguousRecords(channel, state), market, run, sent


def offer(market, run):
    catalog = market.catalog(run["id"], "general")
    quantities = {r["id"]: r["quantity"] for r in run["requirements"]}
    return market.issue_offer(run["id"], "general", "buyer", {
        "delivery_slot": catalog["delivery_slots"][0]["id"],
        "lines": [{"product_id": p["id"], "quantity": quantities[p["requirement_id"]], "unit": p["unit"]}
                  for p in catalog["products"] if p["requirement_id"] in quantities and not p.get("substitution_for")]})


def test_readable_catalog_and_sheet_match_documented_payload(tmp_path):
    publisher, market, run, sent = setup(tmp_path)
    record = publisher.publish_catalog(market, run["id"], "general")
    body = json.loads(sent[0].content)
    assert sent[0].url.path == "/api/documents"
    assert sent[0].headers["authorization"] == "Bearer secret"
    assert set(body) == {"type", "title", "content", "visibility", "labels"}
    assert body["type"] == "doc" and body["visibility"] == "workspace"
    assert "publication-time" in body["content"]
    assert "[Simulated]" not in body["title"]
    assert "demo-context.md" in body["content"]
    assert "Product specifications" in body["content"]
    assert "private" not in body["content"]
    assert "unit_cost" not in body["content"]
    assert record["marker"] in body["labels"]
    assert publisher.publish_catalog(market, run["id"], "general") == record
    sheet = publisher.publish_catalog_sheet(market, run["id"], "general")
    assert sheet["type"] == "sheet"
    assert sent[1].url.path == "/api/sheets"
    sheet_body = json.loads(sent[1].content)
    assert set(sheet_body) == {"title", "content", "visibility", "labels"}
    assert "Catalog snapshot" in sheet_body["title"]
    tab = sheet_body["content"]["tabs"][0]
    assert set(tab) == {"name", "columns", "rows"}
    assert all(column["type"] == "text" for column in tab["columns"])
    assert all(isinstance(row["list_price"], str) for row in tab["rows"])
    assert publisher.publish_catalog_sheet(market, run["id"], "general") == sheet
    assert len(sent) == 2


def test_issued_and_accepted_records_are_distinct_and_sanitized(tmp_path):
    publisher, market, run, sent = setup(tmp_path)
    quoted = offer(market, run)
    contaminated = deepcopy(quoted)
    contaminated["private"] = {"cost": "NEVER-PUBLISH"}
    contaminated["raw_trace"] = "NEVER-PUBLISH"
    contaminated["lines"][0]["unit_cost"] = "NEVER-PUBLISH"
    contaminated["delivery"]["private_capacity_plan"] = "NEVER-PUBLISH"
    issued = publisher.publish_offer(contaminated)
    assert "NEVER-PUBLISH" not in sent[0].content.decode()
    assert quoted["total"] in json.loads(sent[0].content)["content"]
    assert "[Simulated]" not in json.loads(sent[0].content)["title"]
    assert '"simulated": true' in json.loads(sent[0].content)["content"]
    accepted_offer = market.accept_offer(run["id"], quoted["quote_id"], "buyer")
    accepted = publisher.publish_offer(accepted_offer)
    assert accepted["id"] != issued["id"]
    assert "simulated_commitment" in json.loads(sent[1].content)["content"]
    assert publisher.publish_offer(accepted_offer) == accepted
    assert len(sent) == 2
    assert all(request.url.path == "/api/documents" for request in sent)


def test_artifact_identity_survives_state_reopen(tmp_path):
    publisher, market, run, sent = setup(tmp_path)
    record = publisher.publish_catalog(market, run["id"], "general")
    reopened = AmbiguousRecords(publisher.channel, TransportState(tmp_path / "state.db"))
    assert reopened.publish_catalog(market, run["id"], "general") == record
    assert len(sent) == 1


@pytest.mark.parametrize("failure", ["timeout", "server", "missing-id"])
def test_uncertain_creation_is_never_reposted(tmp_path, failure):
    def handler(request):
        if failure == "timeout":
            raise httpx.ReadTimeout("private-provider-detail", request=request)
        if failure == "server":
            return httpx.Response(500, text="private-provider-detail")
        return httpx.Response(201, json={"title": "missing id"})
    publisher, market, run, sent = setup(tmp_path, handler)
    with pytest.raises(RecoveryRequired):
        publisher.publish_catalog(market, run["id"], "general")
    reopened = AmbiguousRecords(publisher.channel, TransportState(tmp_path / "state.db"))
    with pytest.raises(RecoveryRequired):
        reopened.publish_catalog(market, run["id"], "general")
    assert len(sent) == 1
    stored = publisher.state.db.execute("SELECT value FROM transport_state").fetchall()
    assert "private-provider-detail" not in str(stored)
    assert json.loads(stored[0][0])["pending"] is True


def test_refuses_another_vendor_and_unissued_proposal(tmp_path):
    publisher, market, run, sent = setup(tmp_path)
    with pytest.raises(ValueError, match="another supplier"):
        publisher.publish_catalog(market, run["id"], "local")
    quoted = offer(market, run)
    with pytest.raises(ValueError, match="Only issued"):
        publisher.publish_offer({**quoted, "status": "rejected"})
    assert not sent
