from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ontology_software_factory.harness import (
    HarnessBudget, HarnessBudgetExceeded, HarnessDenied, HarnessPrincipal, HarnessRuntime
)
from ontology_software_factory.tool_registry import ToolRegistry
from ontology_software_factory.workflow_store import SQLiteWorkflowStore

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
        events = [json.loads(line) for line in (self.root / "audit.jsonl").read_text().splitlines()]
        self.assertEqual([event["status"] for event in events], ["denied", "succeeded"])
        self.assertNotIn("payload", events[0])

    def test_kill_switch_blocks_tool_invocation(self):
        (self.root / "KILL").write_text("stop")
        with self.assertRaises(HarnessDenied):
            self.harness.invoke_tool(
                self.principal, run_id="run-1", task_id="task-1",
                tool_id="documents.read", payload={"relativePath": "docs/architecture.md"}
            )

    def test_persistent_run_budget_is_shared_across_harness_instances(self):
        store = SQLiteWorkflowStore(self.root / "workflow.sqlite3")
        self.addCleanup(store.close)
        shared_budget = HarnessBudget(
            max_tool_calls=10, max_run_tool_calls=1, max_context_bytes=4096,
            max_input_tokens=100, max_output_tokens=100,
        )
        first = HarnessRuntime(
            project_root=ROOT, tool_registry=self.registry,
            audit_path=self.root / "first-audit.jsonl",
            budget=shared_budget, usage_store=store, policy_version="test-policy-v1", policy_digest="sha256:test-policy",
        )
        second = HarnessRuntime(
            project_root=ROOT, tool_registry=self.registry,
            audit_path=self.root / "second-audit.jsonl",
            budget=shared_budget, usage_store=store, policy_version="test-policy-v1",
        )
        first.invoke_tool(
            self.principal, run_id="shared-run", task_id="task-a",
            tool_id="documents.read", payload={"relativePath": "docs/architecture.md"},
        )
        with self.assertRaises(HarnessBudgetExceeded):
            second.invoke_tool(
                self.principal, run_id="shared-run", task_id="task-b",
                tool_id="documents.read", payload={"relativePath": "docs/architecture.md"},
            )
        self.assertEqual(store.get_harness_usage("shared-run")["toolCalls"], 1)
        events = store.list_harness_usage_events("shared-run")
        self.assertEqual([item["status"] for item in events], ["recorded", "budget_exceeded"])
        self.assertTrue(all(item["policyVersion"] == "test-policy-v1" for item in events))
        self.assertTrue(all(item["policyDigest"] == "sha256:test-policy" for item in events))
        self.assertTrue(all("payload" not in item["metadata"] for item in events))

    def test_persistent_model_token_usage_survives_runtime_recreation(self):
        store = SQLiteWorkflowStore(self.root / "usage.sqlite3")
        self.addCleanup(store.close)
        harness = HarnessRuntime(
            project_root=ROOT, tool_registry=self.registry,
            audit_path=self.root / "usage-audit.jsonl",
            budget=HarnessBudget(max_input_tokens=100, max_output_tokens=50),
            usage_store=store, policy_version="policy-1",
        )
        harness.record_model_usage(
            "token-run", task_id="task-llm", provider="openai-agents",
            model="test-model", input_tokens=12, output_tokens=7, response_id="resp-safe",
        )
        self.assertEqual(store.get_harness_usage("token-run")["inputTokens"], 12)
        event = store.list_harness_usage_events("token-run")[0]
        self.assertEqual(event["provider"], "openai-agents")
        self.assertEqual(event["model"], "test-model")
        self.assertNotIn("prompt", event["metadata"])

    def test_model_usage_budget(self):
        self.harness.record_model_usage("run-1", input_tokens=50, output_tokens=20)
        with self.assertRaises(HarnessBudgetExceeded):
            self.harness.record_model_usage("run-1", input_tokens=60, output_tokens=0)


if __name__ == "__main__":
    unittest.main()
