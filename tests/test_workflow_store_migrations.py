from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from ontology_software_factory.workflow_store import SQLiteWorkflowStore


class WorkflowStoreMigrationTests(unittest.TestCase):
    def test_backfills_plan_approval_and_phase_rows_for_legacy_plans(self):
        with tempfile.TemporaryDirectory() as temp:
            database = Path(temp) / "legacy.sqlite3"
            plan = {
                "planId": "sf:agent-plan:legacy",
                "workflowRunId": "RUN-LEGACY",
                "phases": [{"phaseId": "requirements"}, {"phaseId": "delivery"}],
            }
            with sqlite3.connect(database) as connection:
                connection.execute(
                    """CREATE TABLE factory_orchestrator_plans(
                        plan_id TEXT PRIMARY KEY, run_id TEXT NOT NULL,
                        payload_sha256 TEXT NOT NULL, payload_json TEXT NOT NULL,
                        created_at TEXT NOT NULL
                    )"""
                )
                connection.execute(
                    """CREATE TABLE factory_plan_phases(
                        plan_id TEXT NOT NULL, phase_id TEXT NOT NULL, run_id TEXT NOT NULL,
                        status TEXT NOT NULL, started_at TEXT, finished_at TEXT,
                        error_json TEXT NOT NULL DEFAULT '{}', updated_at TEXT NOT NULL,
                        PRIMARY KEY(plan_id, phase_id)
                    )"""
                )
                connection.execute(
                    """CREATE TABLE factory_assignment_results(
                        plan_id TEXT NOT NULL, assignment_id TEXT NOT NULL, run_id TEXT NOT NULL,
                        task_id TEXT NOT NULL, status TEXT NOT NULL, output_json TEXT NOT NULL,
                        evidence_json TEXT NOT NULL, error_json TEXT NOT NULL, event_id TEXT NOT NULL,
                        updated_at TEXT NOT NULL, PRIMARY KEY(plan_id, assignment_id)
                    )"""
                )
                connection.execute(
                    "INSERT INTO factory_orchestrator_plans VALUES(?,?,?,?,?)",
                    (plan["planId"], plan["workflowRunId"], "a" * 64,
                     json.dumps(plan), "2026-10-30T00:00:00+00:00"),
                )
            store = SQLiteWorkflowStore(database)
            try:
                approval = store.get_factory_plan_approval(plan["planId"])
                self.assertIsNotNone(approval)
                self.assertEqual(approval["status"], "pending")
                self.assertEqual(approval["requestedBy"], "factory-orchestrator")
                phases = store.list_factory_plan_phases(plan["workflowRunId"], plan["planId"])
                self.assertEqual({item["phaseId"] for item in phases}, {"requirements", "delivery"})
                self.assertTrue(all(item["status"] == "pending" for item in phases))
                phase_columns = {
                    row["name"] for row in store._conn.execute("PRAGMA table_info(factory_plan_phases)").fetchall()
                }
                result_columns = {
                    row["name"] for row in store._conn.execute("PRAGMA table_info(factory_assignment_results)").fetchall()
                }
                self.assertIn("attempt", phase_columns)
                self.assertIn("phase_attempt", result_columns)
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
