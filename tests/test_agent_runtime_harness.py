from __future__ import annotations

import json
import tempfile
import unittest
from contextvars import ContextVar
from pathlib import Path

from ontology_software_factory.agent_runtime import OpenAIAgentsRuntime
from ontology_software_factory.harness import HarnessPrincipal, HarnessRuntime
from ontology_software_factory.governance import SQLiteInvocationLedger, ToolGateway
from ontology_software_factory.tool_registry import ToolRegistry

ROOT = Path(__file__).resolve().parents[1]


def identity_function_tool(**_metadata):
    return lambda function: function


class AgentRuntimeHarnessTests(unittest.TestCase):
    def test_agent_tool_functions_route_through_harness_and_write_metadata_audit(self):
        runtime = OpenAIAgentsRuntime.__new__(OpenAIAgentsRuntime)
        runtime.project_root = ROOT
        runtime._active_harness_context = ContextVar("test_agent_harness", default=None)
        tools = runtime._build_tools(identity_function_tool)
        registry = ToolRegistry(ROOT, runtime._tool_handlers)

        with tempfile.TemporaryDirectory() as temp:
            harness = HarnessRuntime(
                project_root=ROOT, tool_registry=registry,
                audit_path=Path(temp) / "harness-audit.jsonl",
            )
            principal = HarnessPrincipal(
                principal_id="sf:task:test-harness", role_id="requirement-analyst",
                tenant_id="tenant-test", project_id="project-test",
            )
            harness.assemble_context(
                principal, run_id="RUN-HARNESS", task_id="sf:task:test-harness",
                shared={"tenant_id": "tenant-test", "project_id": "project-test", "task_id": "sf:task:test-harness"},
            )
            ledger = SQLiteInvocationLedger(Path(temp) / "invocations.sqlite3")
            self.addCleanup(ledger.close)
            gateway = ToolGateway(harness, ledger)
            token = runtime._active_harness_context.set((
                gateway, principal, "RUN-HARNESS", "sf:task:test-harness"
            ))
            try:
                result = tools["documents.read"]("docs/architecture-principles-and-constraints.md")
                self.assertIn("AP-14", result)
                validated = tools["contract.validate"](
                    '{"valid": true}', '{"type": "object", "required": ["valid"]}'
                )
                self.assertEqual(json.loads(validated), {"valid": True})
            finally:
                runtime._active_harness_context.reset(token)

            events = [json.loads(line) for line in (Path(temp) / "harness-audit.jsonl").read_text().splitlines()]
            self.assertEqual([item["toolId"] for item in events], ["documents.read", "contract.validate"])
            self.assertTrue(all(item["status"] == "succeeded" for item in events))
            self.assertTrue(all("payload" not in item for item in events))

    def test_agent_tool_call_fails_closed_without_active_harness_context(self):
        runtime = OpenAIAgentsRuntime.__new__(OpenAIAgentsRuntime)
        runtime.project_root = ROOT
        runtime._active_harness_context = ContextVar("test_agent_harness_missing", default=None)
        with self.assertRaises(Exception):
            runtime._invoke_harness_tool("documents.read", {"relativePath": "README.md"})


if __name__ == "__main__":
    unittest.main()
