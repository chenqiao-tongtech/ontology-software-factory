from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ontology_software_factory.harness import (
    HarnessBudget, HarnessBudgetExceeded, HarnessDenied, HarnessPrincipal, HarnessRuntime
)
from ontology_software_factory.tool_registry import ToolRegistry

ROOT = Path(__file__).resolve().parents[1]


class HarnessRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.calls = []
        handlers = {
            "documents.read": lambda payload: self.calls.append(("documents.read", payload)) or {"text": "ok"},
            "catalog.read": lambda payload: {"assets": []},
            "contract.validate": lambda payload: {"valid": True},
            "release.simulation.promote": lambda payload: {"promoted": True},
        }
        self.registry = ToolRegistry(ROOT, handlers)
        self.principal = HarnessPrincipal("user-1", "requirement-analyst", "tenant-a", "project-a")
        self.harness = HarnessRuntime(
            project_root=ROOT, tool_registry=self.registry,
            audit_path=self.root / "audit.jsonl",
            budget=HarnessBudget(max_tool_calls=1, max_context_bytes=4096, max_input_tokens=100, max_output_tokens=100),
            approval_validator=lambda ref, run, tool: ref == "approval-1" and run == "run-1" and tool == "release.simulation.promote",
            kill_switch_path=self.root / "KILL",
        )

    def test_context_is_allowlisted_and_tenant_bound(self):
        context = self.harness.assemble_context(
            self.principal, run_id="run-1", task_id="task-1",
            shared={"tenant_id": "tenant-a", "project_id": "project-a", "task_id": "task-1",
                    "raw_passwords": "should-not-pass", "unlisted": "hidden"},
            task_local={"relevant_file_paths": ["docs/architecture.md"], "current_agent_plan": "review"},
            evidence_refs=["ev-1"],
        )
        self.assertEqual(context.fields["task_id"], "task-1")
        self.assertNotIn("raw_passwords", context.fields)
        self.assertNotIn("unlisted", context.fields)
        self.assertEqual(context.evidence_refs, ("ev-1",))

    def test_context_rejects_cross_tenant_and_restricted_task_local(self):
        with self.assertRaises(HarnessDenied):
            self.harness.assemble_context(
                self.principal, run_id="run-1", task_id="task-1",
                shared={"tenant_id": "tenant-b"}, task_local={}
            )
        with self.assertRaises(HarnessDenied):
            self.harness.assemble_context(
                self.principal, run_id="run-1", task_id="task-1",
                shared={"tenant_id": "tenant-a"}, task_local={"raw_passwords": "x"}
            )

    def test_tool_calls_are_budgeted_and_audited_without_payload(self):
        result = self.harness.invoke_tool(
            self.principal, run_id="run-1", task_id="task-1",
            tool_id="documents.read", payload={"relativePath": "docs/architecture.md"}
        )
        self.assertEqual(result, {"text": "ok"})
        self.assertEqual(self.harness.usage("run-1")["toolCalls"], 1)
        with self.assertRaises(HarnessBudgetExceeded):
            self.harness.invoke_tool(
                self.principal, run_id="run-1", task_id="task-2",
                tool_id="documents.read", payload={"relativePath": "docs/architecture.md"}
            )
        event = json.loads((self.root / "audit.jsonl").read_text().splitlines()[0])
        self.assertEqual(event["status"], "succeeded")
        self.assertNotIn("payload", event)
        self.assertNotIn("content", event)

    def test_approval_must_be_independent_and_bound_to_run_and_tool(self):
        release_principal = HarnessPrincipal("user-1", "release-coordinator", "tenant-a", "project-a")
        with self.assertRaises(HarnessDenied):
            self.harness.invoke_tool(
                release_principal, run_id="run-1", task_id="task-1",
                tool_id="release.simulation.promote",
                payload={"releaseId": "rel-1", "targetEnvironment": "test"},
                approval_ref="bad"
            )
        result = self.harness.invoke_tool(
            release_principal, run_id="run-1", task_id="task-1",
            tool_id="release.simulation.promote",
            payload={"releaseId": "rel-1", "targetEnvironment": "test"},
            approval_ref="approval-1"
        )
        self.assertEqual(result, {"promoted": True})

    def test_kill_switch_blocks_tool_invocation(self):
        (self.root / "KILL").write_text("stop")
        with self.assertRaises(HarnessDenied):
            self.harness.invoke_tool(
                self.principal, run_id="run-1", task_id="task-1",
                tool_id="documents.read", payload={"relativePath": "docs/architecture.md"}
            )

    def test_model_usage_budget(self):
        self.harness.record_model_usage("run-1", input_tokens=50, output_tokens=20)
        with self.assertRaises(HarnessBudgetExceeded):
            self.harness.record_model_usage("run-1", input_tokens=60, output_tokens=0)


if __name__ == "__main__":
    unittest.main()
