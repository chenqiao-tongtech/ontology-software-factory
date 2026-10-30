from __future__ import annotations
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from ontology_software_factory.task_runtime import (  # noqa: E402
    EvidenceContractError, IdempotencyConflict, LeaseLost, SQLiteTaskStore, TaskWorker,
    TransientTaskError, enqueue_workflow_step, echo_handler, sample_evidence_handler,
)


def evidence(typ="test-report"):
    body = b"real-ish sample evidence"
    return {"type": typ, "uri": "artifact://test/report.json", "sha256": hashlib.sha256(body).hexdigest(),
            "createdAt": "2026-01-01T00:00:00+00:00"}


class TaskRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = SQLiteTaskStore(Path(self.temp.name) / "tasks.sqlite3")

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def enqueue(self, **kwargs):
        args = {"task_type": "demo.generate-evidence", "payload": {"message": "run"},
                "idempotency_key": "unit:key:1", "required_evidence": ["test-report"],
                "backoff_base_seconds": 0, "backoff_max_seconds": 0}
        args.update(kwargs)
        return self.store.enqueue(**args)

    def test_same_idempotency_key_same_payload_reuses_task(self):
        first, reused1 = self.enqueue()
        second, reused2 = self.enqueue()
        self.assertFalse(reused1)
        self.assertTrue(reused2)
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(len(self.store.list_tasks()), 1)

    def test_same_key_different_payload_is_conflict(self):
        self.enqueue()
        with self.assertRaises(IdempotencyConflict):
            self.enqueue(payload={"message": "different"})

    def test_same_key_different_task_type_is_conflict(self):
        self.enqueue()
        with self.assertRaises(IdempotencyConflict):
            self.enqueue(task_type="demo.echo")

    def test_claim_increments_attempt_and_sets_lease(self):
        task, _ = self.enqueue()
        claimed = self.store.claim("worker-A", lease_seconds=30)
        self.assertEqual(claimed["id"], task["id"])
        self.assertEqual(claimed["attempts"], 1)
        self.assertEqual(claimed["leaseOwner"], "worker-A")
        self.assertIsNotNone(claimed["leaseExpiresAt"])
        self.assertIsNone(self.store.claim("worker-B", lease_seconds=30))

    def test_wrong_worker_cannot_complete(self):
        task, _ = self.enqueue()
        self.store.claim("worker-A", lease_seconds=30)
        with self.assertRaises(LeaseLost):
            self.store.complete(task["id"], "worker-B", output={}, evidence=[evidence()])

    def test_success_requires_evidence_and_is_persisted(self):
        task, _ = self.enqueue()
        self.store.claim("worker-A", lease_seconds=30)
        done = self.store.complete(task["id"], "worker-A", output={"ok": True}, evidence=[evidence()])
        self.assertEqual(done["status"], "succeeded")
        self.assertEqual(done["output"], {"ok": True})
        events = self.store.get_events(task["id"])
        self.assertEqual(events[-1]["action"], "task.succeeded")

    def test_missing_required_evidence_is_rejected(self):
        task, _ = self.enqueue()
        self.store.claim("worker-A", lease_seconds=30)
        with self.assertRaises(EvidenceContractError):
            self.store.complete(task["id"], "worker-A", output={}, evidence=[])

    def test_invalid_evidence_hash_is_rejected(self):
        task, _ = self.enqueue()
        self.store.claim("worker-A", lease_seconds=30)
        bad = {"type": "test-report", "uri": "artifact://report", "sha256": "oops"}
        with self.assertRaises(EvidenceContractError):
            self.store.complete(task["id"], "worker-A", output={}, evidence=[bad])

    def test_retryable_error_schedules_retry(self):
        task, _ = self.enqueue(max_attempts=3)
        claimed = self.store.claim("worker-A", lease_seconds=30)
        after = self.store.fail(task["id"], "worker-A", error_class="transient", error_message="temporary", now=time.time())
        self.assertEqual(after["status"], "retry_wait")
        self.assertEqual(after["attempts"], 1)
        self.assertTrue(any(e["action"] == "task.retry_scheduled" for e in self.store.get_events(task["id"])))

    def test_retryable_failure_exhaustion_goes_to_dead_letter(self):
        task, _ = self.enqueue(max_attempts=1)
        self.store.claim("worker-A", lease_seconds=30)
        after = self.store.fail(task["id"], "worker-A", error_class="transient", error_message="unavailable")
        self.assertEqual(after["status"], "dead_letter")

    def test_non_retryable_error_fails_closed(self):
        task, _ = self.enqueue()
        self.store.claim("worker-A", lease_seconds=30)
        after = self.store.fail(task["id"], "worker-A", error_class="permission_denied", error_message="not allowed")
        self.assertEqual(after["status"], "failed")

    def test_expired_lease_is_recovered_and_old_worker_fenced(self):
        task, _ = self.enqueue(max_attempts=3)
        first = self.store.claim("worker-A", lease_seconds=1)
        future = first["leaseExpiresAtEpoch"] + 2
        with self.assertRaises(LeaseLost):
            self.store.complete(task["id"], "worker-A", output={}, evidence=[evidence()], now=future)
        # Since backoff is zero, a new poll recovers the expired lease and claims it.
        second = self.store.claim("worker-B", lease_seconds=30, now=future)
        self.assertEqual(second["id"], task["id"])
        self.assertEqual(second["attempts"], 2)
        self.assertEqual(second["leaseOwner"], "worker-B")

    def test_worker_runs_registered_handler_and_records_demo_evidence(self):
        task, _ = self.store.enqueue(task_type="demo.generate-evidence", payload={"message": "hello"},
            idempotency_key="worker:demo:1", required_evidence=["test-report"], backoff_base_seconds=0, backoff_max_seconds=0)
        worker = TaskWorker(self.store, {"demo.generate-evidence": sample_evidence_handler}, worker_id="demo-worker")
        result = worker.run_once()
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(result["task"]["id"], task["id"])
        self.assertEqual(result["task"]["evidence"][0]["uri"].startswith("demo://"), True)

    def test_worker_renews_lease_during_long_running_handler(self):
        self.store.enqueue(task_type="slow", payload={}, idempotency_key="worker:slow:1",
            timeout_seconds=5, required_evidence=[], backoff_base_seconds=0, backoff_max_seconds=0)
        def slow_handler(payload, context):
            time.sleep(1.3)  # longer than the initial 1-second lease
            context.check_deadline()
            return {"output": {"ok": True}, "evidence": []}
        worker = TaskWorker(self.store, {"slow": slow_handler}, worker_id="heartbeat-worker", lease_seconds=1)
        result = worker.run_once()
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(result["task"]["attempts"], 1)

    def test_handler_timeout_is_classified_as_retryable(self):
        self.store.enqueue(task_type="slow", payload={}, idempotency_key="worker:timeout:1",
            timeout_seconds=0.1, max_attempts=2, required_evidence=[], backoff_base_seconds=0, backoff_max_seconds=0)
        def too_slow(payload, context):
            time.sleep(0.15)
            return {"output": {}, "evidence": []}
        worker = TaskWorker(self.store, {"slow": too_slow}, worker_id="timeout-worker", lease_seconds=1)
        result = worker.run_once()
        self.assertEqual(result["status"], "retry_wait")
        self.assertEqual(result["task"]["errorClass"], "timeout")

    def test_unknown_handler_does_not_retry_by_default(self):
        task, _ = self.store.enqueue(task_type="unregistered", payload={}, idempotency_key="missing-handler")
        worker = TaskWorker(self.store, {}, worker_id="demo-worker")
        result = worker.run_once()
        self.assertEqual(result["status"], "failed")
        self.assertEqual(self.store.get_task(task["id"])["errorClass"], "unknown_handler")

    def test_workflow_step_translates_to_task_contract(self):
        run = {"id": "RUN-1", "workflowId": "software-delivery", "workflowVersion": "1.0.0", "status": "running"}
        step = {"id": "implementation", "status": "running", "attempt": 2, "maxAttempts": 3,
                "timeoutSeconds": 300, "retryableErrorClasses": ["transient"], "requiredEvidence": ["commit-reference"]}
        task, duplicate = enqueue_workflow_step(self.store, run, step, {"changeRequest": "add endpoint"})
        self.assertFalse(duplicate)
        self.assertEqual(task["idempotencyKey"], "workflow:RUN-1:implementation:attempt:2")
        self.assertEqual(task["payload"]["businessOperationId"], "RUN-1:implementation")
        again, duplicate = enqueue_workflow_step(self.store, run, step, {"changeRequest": "add endpoint"})
        self.assertTrue(duplicate)
        self.assertEqual(task["id"], again["id"])

    def test_workflow_dispatch_requires_running_step(self):
        run = {"id": "RUN-1", "status": "paused"}
        step = {"id": "test", "status": "running"}
        with self.assertRaises(ValueError):
            enqueue_workflow_step(self.store, run, step, {})

    def test_event_ledger_records_claim_and_finish(self):
        task, _ = self.enqueue()
        self.store.claim("worker-A", lease_seconds=30)
        self.store.complete(task["id"], "worker-A", output={}, evidence=[evidence()])
        actions = [e["action"] for e in self.store.get_events(task["id"])]
        self.assertEqual(actions, ["task.enqueued", "task.claimed", "task.succeeded"])

if __name__ == "__main__":
    unittest.main()
