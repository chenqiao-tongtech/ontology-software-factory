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
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
