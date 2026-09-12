"""Mirror public supplier records and accepted commitments into Ambiguous."""

from .records import AmbiguousRecords, public_offer
from .runtime import RecoveryRequired


class SupplierRecordsSync:
    """Run after worker processing, or explicitly while workers are stopped.

    connections maps vendor IDs to authenticated AmbiguousClient instances. The
    worker and synchronizer share a TransportState, including fulfillment keys.
    Do not run multiple processes against the same vendor state concurrently.
    """

    def __init__(self, market, state, connections):
        self.market = market
        self.state = state
        self.connections = connections
        if any(vendor != channel.config.vendor_id for vendor, channel in connections.items()):
            raise ValueError("Connection key does not match its supplier identity")
        self.publishers = {vendor: AmbiguousRecords(channel, state)
                           for vendor, channel in connections.items()}

    def _task(self, run_id, vendor_id, offer):
        channel = self.connections[vendor_id]
        if channel.identity is None:
            channel.verify_identity(require_buyer=False)
        key = f'fulfillment:{run_id}:{vendor_id}:{offer["quote_id"]}'
        task = self.state.get(key)
        if task is not None:
            if task.get("pending"):
                raise RecoveryRequired("Fulfillment task creation uncertain; inspect Ambiguous before retry")
            return task
        self.state.put(key, {"pending": True})
        try:
            task = channel.create_fulfillment_task(public_offer(offer))
            if not isinstance(task.get("id"), str) or not task["id"]:
                raise ValueError("Fulfillment creation returned no task ID")
            self.state.put(key, task)
        except Exception as exc:
            raise RecoveryRequired("Fulfillment task creation uncertain; inspect Ambiguous before retry") from exc
        return task

    def sync(self, run_id):
        exported = self.market.export_run(run_id, private=False)
        result = {"run_id": run_id, "ok": True, "vendors": {}}
        for vendor_id in self.connections:
            records = {"offers": [], "tasks": [], "errors": []}
            result["vendors"][vendor_id] = records
            publisher = self.publishers[vendor_id]

            def attempt(kind, operation, quote_id=None):
                try:
                    return operation()
                except Exception as exc:
                    # Continue independent records/vendors without leaking HTTP bodies.
                    error = {"operation": kind, "error": type(exc).__name__,
                             "recovery_required": isinstance(exc, RecoveryRequired)}
                    if quote_id:
                        error["quote_id"] = quote_id
                    records["errors"].append(error)
                    result["ok"] = False
                    return None

            records["catalog"] = attempt("catalog", lambda: publisher.publish_catalog(self.market, run_id, vendor_id))
            records["sheet"] = attempt("catalog_sheet", lambda: publisher.publish_catalog_sheet(self.market, run_id, vendor_id))
            for offer in exported["offers"]:
                if offer["vendor_id"] != vendor_id or offer["status"] not in ("issued", "accepted"):
                    continue
                artifact = attempt("offer", lambda: publisher.publish_offer(offer), offer["quote_id"])
                if artifact:
                    records["offers"].append({"quote_id": offer["quote_id"], "status": offer["status"],
                                               "document": artifact})
                if offer["status"] == "accepted":
                    task = attempt("fulfillment_task", lambda: self._task(run_id, vendor_id, offer), offer["quote_id"])
                    if task:
                        records["tasks"].append({"quote_id": offer["quote_id"], "task": task})
        self.state.put(f"records:{run_id}", result)
        return result
