from __future__ import annotations
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
import sys
sys.path.insert(0, str(ROOT / "src"))
from ontology_software_factory.workflow_engine import WorkflowEngine, WorkflowError  # noqa: E402
from ontology_software_factory.workflow_store import ConcurrentWorkflowUpdate, SQLiteWorkflowStore  # noqa: E402


class WorkflowEngineTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.store = SQLiteWorkflowStore(Path(self.tempdir.name) / "test.sqlite3")
        self.definition = json.loads((ROOT / "workflows/definitions/software-delivery-v1.json").read_text(encoding="utf-8"))
        self.engine = WorkflowEngine(self.store, self.definition)

    def tearDown(self):
        self.store.close()
        self.tempdir.cleanup()

    def create(self):
        return self.engine.create_run("单元测试运行", "tester", "test")

    def test_definition_is_valid_dag(self):
        self.assertEqual(len(self.definition["steps"]), 7)
        self.assertEqual(self.definition["steps"][-1]["id"], "deployment")

    def test_create_run_starts_first_step(self):
        run = self.create()
        self.assertEqual(run["status"], "running")
        self.assertEqual(run["currentStepId"], "requirement-analysis")
        self.assertEqual(run["steps"][0]["attempt"], 1)
        self.assertEqual(self.store.get_events(run["id"])[0]["action"], "run.created")

    def test_completing_step_advances_only_to_next_dependency(self):
        run = self.create()
        run = self.engine.apply_action(run["id"], "complete_step")
        self.assertEqual(run["currentStepId"], "architecture-design")
        self.assertEqual(run["steps"][0]["status"], "succeeded")
        self.assertEqual(run["steps"][2]["status"], "pending")

    def test_cannot_approve_before_approval_gate(self):
        run = self.create()
        with self.assertRaises(WorkflowError) as ctx:
            self.engine.apply_action(run["id"], "approve", note="looks good")
        self.assertEqual(ctx.exception.status_code, 409)

    def test_approval_requires_a_reason_and_then_advances(self):
        run = self.create()
        # Fast-forward the deterministic demo until it reaches the approval gate.
        for _ in range(5):
            run = self.engine.apply_action(run["id"], "complete_step")
        self.assertEqual(run["status"], "waiting_approval")
        with self.assertRaises(WorkflowError):
            self.engine.apply_action(run["id"], "approve", note="")
        run = self.engine.apply_action(run["id"], "approve", note="Test and security evidence reviewed")
        self.assertEqual(run["currentStepId"], "deployment")
        self.assertEqual(run["status"], "running")
        self.assertIn("人工审批记录", run["steps"][5]["evidence"][-1])

    def test_retry_increments_attempt_and_preserves_event(self):
        run = self.create()
        run = self.engine.apply_action(run["id"], "fail_step", note="transient worker lost")
        self.assertEqual(run["status"], "failed")
        run = self.engine.apply_action(run["id"], "retry")
        self.assertEqual(run["status"], "running")
        self.assertEqual(run["steps"][0]["attempt"], 2)
        actions = [e["action"] for e in self.store.get_events(run["id"])]
        self.assertIn("step.failed", actions)
        self.assertIn("step.retry_requested", actions)

    def test_deterministic_failure_is_not_retryable(self):
        run = self.create()
        run = self.engine.apply_action(run["id"], "fail_step", note="权限拒绝：policy denied")
        self.assertFalse(run["steps"][0]["retryable"])
        with self.assertRaises(WorkflowError):
            self.engine.apply_action(run["id"], "retry")

    def test_pause_resume_cancel_transitions(self):
        run = self.create()
        run = self.engine.apply_action(run["id"], "pause")
        self.assertEqual(run["status"], "paused")
        run = self.engine.apply_action(run["id"], "resume")
        self.assertEqual(run["status"], "running")
        run = self.engine.apply_action(run["id"], "cancel")
        self.assertEqual(run["status"], "cancelled")
        self.assertTrue(all(s["status"] in {"succeeded", "cancelled"} for s in run["steps"]))

    def test_terminal_run_cannot_be_cancelled(self):
        run = self.create()
        for _ in range(5):
            run = self.engine.apply_action(run["id"], "complete_step")
        run = self.engine.apply_action(run["id"], "approve", note="Approved")
        run = self.engine.apply_action(run["id"], "complete_step")
        self.assertEqual(run["status"], "succeeded")
        with self.assertRaises(WorkflowError) as ctx:
            self.engine.apply_action(run["id"], "cancel")
        self.assertEqual(ctx.exception.status_code, 409)

    def test_unknown_dependency_and_cycle_are_rejected(self):
        bad = json.loads(json.dumps(self.definition))
        bad["steps"][0]["dependsOn"] = ["does-not-exist"]
        with self.assertRaises(ValueError):
            WorkflowEngine(self.store, bad)
        bad = json.loads(json.dumps(self.definition))
        bad["steps"][0]["dependsOn"] = ["deployment"]
        with self.assertRaises(ValueError):
            WorkflowEngine(self.store, bad)

    def test_run_and_event_persist_across_store_reopen(self):
        run = self.create()
        run_id = run["id"]
        self.store.close()
        self.store = SQLiteWorkflowStore(Path(self.tempdir.name) / "test.sqlite3")
        self.engine = WorkflowEngine(self.store, self.definition)
        restored = self.engine.get_run_detail(run_id)
        self.assertEqual(restored["run"]["status"], "running")
        self.assertEqual(restored["events"][0]["action"], "run.created")

    def test_stale_revision_update_fails_closed(self):
        run = self.create()
        with self.assertRaises(ConcurrentWorkflowUpdate):
            self.store.save_updated_run({**run, "revision": run["revision"] + 1},
                                        {"at": run["updatedAt"], "actor": "test", "action": "stale", "summary": "should not save", "payload": {}},
                                        expected_revision=run["revision"] + 10)

if __name__ == "__main__":
    unittest.main()
