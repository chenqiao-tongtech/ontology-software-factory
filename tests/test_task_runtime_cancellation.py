from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ontology_software_factory.task_runtime import (
    LeaseLost, SQLiteTaskStore, TaskRuntimeError,
)


class TaskCancellationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = SQLiteTaskStore(Path(self.temp.name) / "tasks.db")

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def test_cancel_queued_task_is_terminal_and_audited(self):
        task, _ = self.store.enqueue(
            task_type="noop", payload={"value": 1}, idempotency_key="cancel-queued-1",
        )
        cancelled = self.store.cancel(task["id"], actor="operator-1", reason="operator request")
        self.assertEqual(cancelled["status"], "cancelled")
        events = self.store.get_events(task["id"])
        self.assertEqual(events[-1]["action"], "task.cancelled")
        self.assertEqual(self.store.claim("worker-1"), None)

    def test_cancel_running_task_fences_late_completion(self):
        task, _ = self.store.enqueue(
            task_type="noop", payload={"value": 1}, idempotency_key="cancel-running-1",
        )
        claimed = self.store.claim("worker-1", lease_seconds=30)
        self.assertEqual(claimed["id"], task["id"])
        cancelled = self.store.cancel(task["id"], actor="operator-1")
        self.assertEqual(cancelled["status"], "cancelled")
        with self.assertRaises(LeaseLost):
            self.store.complete(
                task["id"], "worker-1", output={"ok": True}, evidence=[],
            )

    def test_cancel_unknown_task_fails_closed(self):
        with self.assertRaises(TaskRuntimeError):
            self.store.cancel("missing-task", actor="operator-1")


if __name__ == "__main__":
    unittest.main()
