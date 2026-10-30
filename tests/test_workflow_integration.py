from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from ontology_software_factory.integration import WorkflowOutboxRelay, demo_workflow_step_handler, enqueue_workflow_step  # noqa: E402
from ontology_software_factory.task_runtime import SQLiteTaskStore, TaskWorker, TransientTaskError  # noqa: E402
from ontology_software_factory.workflow_engine import WorkflowEngine  # noqa: E402
from ontology_software_factory.workflow_store import SQLiteWorkflowStore  # noqa: E402


class WorkflowIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        db = Path(self.tempdir.name) / "closed-loop.sqlite3"
        self.task_store = SQLiteTaskStore(db)
        self.workflow_store = SQLiteWorkflowStore(db)
        definition = json.loads((ROOT / "workflows/definitions/software-delivery-v1.json").read_text(encoding="utf-8"))
        self.engine = WorkflowEngine(self.workflow_store, definition)
        self.worker = TaskWorker(self.task_store, {"demo.workflow-step": demo_workflow_step_handler},
                                 worker_id="integration-test-worker", lease_seconds=2)
        self.relay = WorkflowOutboxRelay(self.task_store, self.engine, relay_id="integration-test-relay")

    def tearDown(self):
        self.task_store.close()
        self.workflow_store.close()
        self.tempdir.cleanup()

    def _create_and_dispatch(self, *, worker_max_attempts=3):
        run = self.engine.create_run("集成闭环测试", "test-suite", "test")
        step = next(step for step in run["steps"] if step["id"] == run["currentStepId"])
        task, duplicate = enqueue_workflow_step(self.task_store, run, step, {"example": "payload"},
                                                worker_max_attempts=worker_max_attempts,
                                                worker_backoff_base_seconds=0,
                                                worker_backoff_max_seconds=0)
        return run, task, duplicate

    def test_success_outbox_atomically_persists_and_advances_workflow(self):
        run, task, duplicate = self._create_and_dispatch()
        self.assertFalse(duplicate)
        result = self.worker.run_once()
        self.assertEqual(result["status"], "succeeded")
        outbox = self.task_store.list_outbox()
        self.assertEqual(len(outbox), 1)
        self.assertEqual(outbox[0]["status"], "pending")
        self.assertEqual(outbox[0]["payload"]["taskId"], task["id"])
        projected = self.relay.run_once()
        self.assertEqual(projected["delivered"], 1)
        restored = self.engine.get_run(run["id"])
        self.assertEqual(restored["steps"][0]["status"], "succeeded")
        self.assertEqual(restored["currentStepId"], "architecture-design")
        self.assertEqual(restored["steps"][0]["executionTaskId"], task["id"])
        self.assertEqual(restored["steps"][0]["executionResult"]["evidence"][0]["type"], "normalized-requirement")
        self.assertTrue(self.task_store.list_outbox()[0]["status"] == "delivered")

    def test_replayed_event_does_not_advance_or_increment_revision_twice(self):
        run, _, _ = self._create_and_dispatch()
        self.worker.run_once()
        event = self.task_store.list_outbox()[0]
        first = self.engine.apply_worker_event(event["payload"])
        revision_after_first = first["run"]["revision"]
        second = self.engine.apply_worker_event(event["payload"])
        self.assertTrue(second["deduplicated"])
        self.assertEqual(second["run"]["revision"], revision_after_first)
        self.assertEqual(self.engine.get_run(run["id"])["currentStepId"], "architecture-design")
        # Relay redelivers the same unacknowledged event; inbox prevents a second transition.
        relay_result = self.relay.run_once()
        self.assertEqual(relay_result["delivered"], 1)
        self.assertEqual(self.engine.get_run(run["id"])["revision"], revision_after_first)

    def test_terminal_task_failure_is_projected_as_retryable_workflow_failure(self):
        run, task, _ = self._create_and_dispatch(worker_max_attempts=1)
        def broken(payload, context):
            raise TransientTaskError("temporary upstream error")
        self.worker.handlers["demo.workflow-step"] = broken
        result = self.worker.run_once()
        self.assertEqual(result["status"], "dead_letter")
        self.assertEqual(len(self.task_store.list_outbox()), 1)
        relay = self.relay.run_once()
        self.assertEqual(relay["delivered"], 1)
        failed_run = self.engine.get_run(run["id"])
        self.assertEqual(failed_run["status"], "failed")
        self.assertEqual(failed_run["currentStepId"], "requirement-analysis")
        self.assertTrue(failed_run["steps"][0]["retryable"])
        self.assertEqual(failed_run["steps"][0]["executionTaskId"], task["id"])

    def test_cancelled_workflow_is_not_revived_by_late_worker_result(self):
        run, _, _ = self._create_and_dispatch()
        self.worker.run_once()
        self.engine.apply_action(run["id"], "cancel", actor="test-suite")
        projected = self.relay.run_once()
        self.assertEqual(projected["ignored"], 1)
        final = self.engine.get_run_detail(run["id"])
        self.assertEqual(final["run"]["status"], "cancelled")
        self.assertIn("worker.result_ignored", [item["action"] for item in final["events"]])

    def test_outbox_lease_expiration_allows_safe_redelivery(self):
        self._create_and_dispatch()
        self.worker.run_once()
        base = time.time() + 1
        first = self.task_store.claim_outbox("relay-A", lease_seconds=2, now=base)
        self.assertEqual(len(first), 1)
        self.assertEqual(first[0]["deliveryAttempts"], 1)
        second = self.task_store.claim_outbox("relay-B", lease_seconds=2, now=base + 3)
        self.assertEqual(len(second), 1)
        self.assertEqual(second[0]["eventId"], first[0]["eventId"])
        self.assertEqual(second[0]["deliveryAttempts"], 2)

    def test_step_dispatch_is_idempotent_for_same_workflow_attempt(self):
        run = self.engine.create_run("重复派发测试", "test-suite", "test")
        step = run["steps"][0]
        one, dup1 = enqueue_workflow_step(self.task_store, run, step, {"same": True},
                                           worker_backoff_base_seconds=0, worker_backoff_max_seconds=0)
        two, dup2 = enqueue_workflow_step(self.task_store, run, step, {"same": True},
                                           worker_backoff_base_seconds=0, worker_backoff_max_seconds=0)
        self.assertFalse(dup1)
        self.assertTrue(dup2)
        self.assertEqual(one["id"], two["id"])
        with self.assertRaises(Exception):
            enqueue_workflow_step(self.task_store, run, step, {"different": True},
                                  worker_backoff_base_seconds=0, worker_backoff_max_seconds=0)

    def test_intermediate_retry_wait_does_not_emit_terminal_workflow_event(self):
        self._create_and_dispatch(worker_max_attempts=3)
        def flaky(payload, context):
            raise TransientTaskError("retry me")
        self.worker.handlers["demo.workflow-step"] = flaky
        result = self.worker.run_once()
        self.assertEqual(result["status"], "retry_wait")
        self.assertEqual(self.task_store.list_outbox(), [])

    def test_paused_workflow_defers_event_without_dead_lettering(self):
        run, _, _ = self._create_and_dispatch()
        self.worker.run_once()
        self.engine.apply_action(run["id"], "pause", actor="test-suite")
        result = self.relay.run_once()
        self.assertEqual(result["deferred"], 1)
        event = self.task_store.list_outbox()[0]
        self.assertEqual(event["status"], "pending")
        self.assertEqual(event["deliveryAttempts"], 0, "operator pause must not consume delivery-failure budget")
        self.assertIn("workflow is paused", event["lastError"])

    def test_example_integration_events_match_json_schema(self):
        from jsonschema import Draft202012Validator
        schema_path = ROOT / "contracts/schemas/workflow-integration-event.schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        validator = Draft202012Validator(schema)
        for name in ("worker-success-event.json", "worker-failure-event.json"):
            example = json.loads((ROOT / "examples/workflow-integration" / name).read_text(encoding="utf-8"))
            with self.subTest(example=name):
                self.assertEqual(list(validator.iter_errors(example)), [])


if __name__ == "__main__":
    unittest.main()
