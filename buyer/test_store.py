"""Private atomic snapshot behavior, using only a temporary local directory."""
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

from buyer import store


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        env = patch.dict(os.environ, {"HERMES_HOME": self.temp.name})
        env.start()
        self.addCleanup(env.stop)

    def test_transaction_persists_private_snapshot_and_reloads(self):
        with store.transaction("task-1") as (state, persist):
            state.update(run_id="run-1", actions={"a": {"status": "sending"}})
            persist()
        path = Path(self.temp.name) / "procurement" / "runs" / "task-1.json"
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        with store.transaction("task-1") as (loaded, _):
            self.assertEqual(loaded["actions"]["a"]["status"], "sending")

    def test_failed_atomic_replace_preserves_last_confirmed_snapshot(self):
        with store.transaction("task-1") as (state, persist):
            state["revision"] = 1
            persist()
            state["revision"] = 2
            with patch.object(store.os, "replace", side_effect=OSError("synthetic disk failure")):
                with self.assertRaises(OSError):
                    persist()
        with store.transaction("task-1") as (loaded, _):
            self.assertEqual(loaded, {"revision": 1})

    def test_unpersisted_mutation_does_not_replace_durable_state(self):
        with store.transaction("task-1") as (state, persist):
            state["status"] = "pending"
            persist()
        with self.assertRaises(RuntimeError):
            with store.transaction("task-1") as (state, _):
                state["status"] = "sent"
                raise RuntimeError("synthetic interrupted operation")
        with store.transaction("task-1") as (loaded, _):
            self.assertEqual(loaded["status"], "pending")

    def test_invalid_json_value_cannot_corrupt_existing_snapshot(self):
        with store.transaction("task-1") as (state, persist):
            state["total"] = "12.30"
            persist()
            state["total"] = float("nan")
            with self.assertRaises(ValueError):
                persist()
        with store.transaction("task-1") as (loaded, _):
            self.assertEqual(loaded["total"], "12.30")

    def test_symlink_state_and_path_traversal_are_rejected(self):
        target = Path(self.temp.name) / "outside.json"
        target.write_text('{"untouched": true}')
        runs = store.home() / "runs"
        runs.mkdir()
        (runs / "task-1.json").symlink_to(target)
        with self.assertRaises(ValueError):
            with store.transaction("task-1"):
                self.fail("symlink accepted")
        for value in ("../outside", "a/b", "", "."):
            with self.assertRaises(ValueError):
                with store.transaction(value):
                    self.fail("invalid identifier accepted")
        self.assertEqual(json.loads(target.read_text()), {"untouched": True})


if __name__ == "__main__":
    unittest.main()
