from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ontology_software_factory.harness import (
    HarnessBudget, HarnessBudgetExceeded, HarnessPrincipal, HarnessRuntime,
)
from ontology_software_factory.tool_registry import ToolRegistry
from ontology_software_factory.workflow_store import SQLiteWorkflowStore

ROOT = Path(__file__).resolve().parents[1]


class PersistedUsage:
    """Small deterministic stand-in for the SQLite usage-store contract."""

    def __init__(self, tool_calls: int = 0):
        self.value = {
            "toolCalls": tool_calls, "contextBytes": 0,
            "inputTokens": 0, "outputTokens": 0,
        }
        self.events = []

    def get_harness_usage(self, run_id):
        return dict(self.value)

    def record_harness_usage(self, **event):
        # Match the SQLite usage-store contract: limit check and increment are
        # one atomic operation, and rejected attempts remain in the audit ledger.
        self.events.append(event)
        limits = event.get("limits") or {}
        deltas = {
            "toolCalls": event.get("tool_calls", 0),
            "contextBytes": event.get("context_bytes", 0),
            "inputTokens": event.get("input_tokens", 0),
            "outputTokens": event.get("output_tokens", 0),
        }
        exceeded = any(
            self.value.get(key, 0) + deltas.get(key, 0) > limit
            for key, limit in limits.items()
        )
        if exceeded and event.get("enforce_limits"):
            return {"allowed": False, "usage": dict(self.value)}
        for key, delta in deltas.items():
            self.value[key] += delta
        return {"allowed": True, "usage": dict(self.value)}


class HarnessGovernanceTests(unittest.TestCase):
    def setUp(self):
        self.principal = HarnessPrincipal(
            principal_id="task-1", role_id="requirement-analyst",
            tenant_id="tenant-a", project_id="project-a",
        )

    def test_persisted_run_budget_is_checked_before_tool_dispatch(self):
        calls = []
        registry = ToolRegistry(ROOT, {"documents.read": lambda payload: calls.append(payload) or "ok"})
        usage = PersistedUsage(tool_calls=1)
        with tempfile.TemporaryDirectory() as temp:
            harness = HarnessRuntime(
                project_root=ROOT, tool_registry=registry,
                audit_path=Path(temp) / "audit.jsonl",
                budget=HarnessBudget(max_tool_calls=1, max_run_tool_calls=10),
                usage_store=usage,
            )
            with self.assertRaises(HarnessBudgetExceeded):
                harness.invoke_tool(
                    self.principal, run_id="run-1", task_id="task-1",
                    tool_id="documents.read", payload={"relativePath": "README.md"},
                )
        self.assertEqual(calls, [])
        self.assertEqual(usage.value["toolCalls"], 1)
        self.assertEqual(len(usage.events), 1)
        self.assertTrue(usage.events[0]["enforce_limits"])
        self.assertEqual(usage.events[0]["limits"], {"toolCalls": 1})

    def test_sqlite_usage_store_atomically_rejects_and_audits_budget_overrun(self):
        calls = []
        registry = ToolRegistry(ROOT, {"documents.read": lambda payload: calls.append(payload) or "ok"})
        with tempfile.TemporaryDirectory() as temp:
            store = SQLiteWorkflowStore(Path(temp) / "workflow.db")
            try:
                harness = HarnessRuntime(
                    project_root=ROOT, tool_registry=registry,
                    audit_path=Path(temp) / "audit.jsonl",
                    budget=HarnessBudget(max_tool_calls=1, max_run_tool_calls=10),
                    usage_store=store,
                )
                harness.invoke_tool(
                    self.principal, run_id="run-sqlite", task_id="task-1",
                    tool_id="documents.read", payload={"relativePath": "README.md"},
                )
                with self.assertRaises(HarnessBudgetExceeded):
                    harness.invoke_tool(
                        self.principal, run_id="run-sqlite", task_id="task-2",
                        tool_id="documents.read", payload={"relativePath": "README.md"},
                    )
                self.assertEqual(len(calls), 1)
                self.assertEqual(store.get_harness_usage("run-sqlite")["toolCalls"], 1)
                events = store.list_harness_usage_events("run-sqlite")
                self.assertEqual(len(events), 2)
                self.assertEqual(events[-1]["status"], "budget_exceeded")
                self.assertEqual(events[-1]["toolCalls"], 1)
            finally:
                store.close()

    def test_lifecycle_audit_is_metadata_only_and_allowlisted(self):
        with tempfile.TemporaryDirectory() as temp:
            audit = Path(temp) / "audit.jsonl"
            registry = ToolRegistry(ROOT, {})
            harness = HarnessRuntime(
                project_root=ROOT, tool_registry=registry, audit_path=audit,
                policy_version="p1", policy_digest="d1",
            )
            harness.record_lifecycle_event(
                run_id="run-1", task_id="task-1", event_type="agent.run.started",
                principal=self.principal,
                metadata={
                    "workflowId": "agent-proposal-v1",
                    "ontologyDigest": "a" * 64,
                    "prompt": "must not be written",
                    "apiKey": "must not be written",
                },
                status="started",
            )
            event = json.loads(audit.read_text(encoding="utf-8").splitlines()[0])
        self.assertEqual(event["eventType"], "agent.run.started")
        self.assertEqual(event["metadata"]["workflowId"], "agent-proposal-v1")
        self.assertNotIn("prompt", json.dumps(event))
        self.assertNotIn("apiKey", json.dumps(event))
        self.assertNotIn("payload", event)


if __name__ == "__main__":
    unittest.main()
