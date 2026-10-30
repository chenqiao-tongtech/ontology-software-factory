import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from ontology_software_factory.runtime_observability import read_agent_workflow_store


class RuntimeObservabilityTests(unittest.TestCase):
    def test_reads_workflow_and_worker_state_without_returning_payloads(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "agent_workflow.sqlite3"
            with sqlite3.connect(path) as db:
                db.executescript("""
                    CREATE TABLE workflow_runs(run_id TEXT PRIMARY KEY, revision INTEGER, status TEXT, updated_at TEXT, payload TEXT);
                    CREATE TABLE workflow_events(event_id INTEGER PRIMARY KEY, run_id TEXT, at TEXT, actor TEXT, action TEXT, summary TEXT, payload TEXT);
                    CREATE TABLE worker_tasks(task_id TEXT PRIMARY KEY, task_type TEXT, queue_name TEXT, status TEXT, attempts INTEGER, max_attempts INTEGER, created_at REAL, updated_at REAL, lease_owner TEXT, error_class TEXT, payload_json TEXT);
                """)
                payload = {"title": "Real agent run", "createdAt": "2026-10-30T00:00:00Z",
                           "prompt": "PRIVATE_PROMPT", "steps": [{"id": "analysis", "name": "Analysis", "status": "succeeded", "roleId": "analyst"}]}
                db.execute("INSERT INTO workflow_runs VALUES(?,?,?,?,?)", ("run-1", 3, "running", "2026-10-30T00:01:00Z", json.dumps(payload)))
                db.execute("INSERT INTO workflow_events VALUES(?,?,?,?,?,?,?)", (1, "run-1", "now", "worker", "step.done", "Step completed", '{"secret":"PRIVATE_EVENT"}'))
                db.execute("INSERT INTO worker_tasks VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                           ("task-1", "agent.workflow-step.analysis", "default", "succeeded", 1, 3, 1000, 1010, None, None, '{"input":"PRIVATE_TASK"}'))
            report = read_agent_workflow_store(path)
            self.assertTrue(report["available"])
            self.assertEqual(report["workflowRuns"]["total"], 1)
            self.assertEqual(report["workflowRuns"]["byStatus"]["running"], 1)
            self.assertEqual(report["workflowRuns"]["stepStatuses"]["succeeded"], 1)
            self.assertEqual(report["workerTasks"]["total"], 1)
            self.assertEqual(report["workerTasks"]["byStatus"]["succeeded"], 1)
            self.assertEqual(report["recentEvents"][0]["summary"], "Step completed")
            encoded = json.dumps(report)
            self.assertNotIn("PRIVATE_PROMPT", encoded)
            self.assertNotIn("PRIVATE_EVENT", encoded)
            self.assertNotIn("PRIVATE_TASK", encoded)

    def test_missing_workflow_database_is_reported_not_created(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "missing.sqlite3"
            report = read_agent_workflow_store(path)
            self.assertFalse(report["available"])
            self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
