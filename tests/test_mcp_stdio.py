import sys
import tempfile
import unittest
from pathlib import Path

from ontology_software_factory.adapters.mcp_stdio import MCPStdioClient, MCPTransportError
from ontology_software_factory.harness import HarnessPrincipal, HarnessRuntime
from ontology_software_factory.tool_registry import ToolRegistry, ToolPolicyError

ROOT = Path(__file__).resolve().parents[1]


class MCPStdioTests(unittest.TestCase):
    def test_initialize_list_and_call_allowlisted_tool_through_harness(self):
        command = [sys.executable, str(ROOT / "tests/fixtures/fake_mcp_server.py")]
        with tempfile.TemporaryDirectory() as temp, MCPStdioClient(command, cwd=ROOT, timeout=2) as client:
            init = client.start()
            self.assertEqual(init["serverInfo"]["name"], "fixture")
            self.assertEqual(client.list_tools()[0]["name"], "echo")
            registry = ToolRegistry(ROOT, {
                "documents.read": lambda payload, context: client.call_tool(
                    "echo", payload, allowed_names={"echo"}, invocation_context=context
                )
            })
            harness = HarnessRuntime(project_root=ROOT, tool_registry=registry,
                audit_path=Path(temp) / "audit.jsonl")
            principal = HarnessPrincipal("principal", "requirement-analyst", "tenant", "project")
            result = harness.invoke_tool(principal, run_id="run", task_id="task",
                tool_id="documents.read", payload={"relativePath": "README.md"}, idempotency_key="mcp-call-1")
            self.assertFalse(result["isError"])

    def test_mcp_mutation_cannot_be_called_without_gateway_context(self):
        command = [sys.executable, str(ROOT / "tests/fixtures/fake_mcp_server.py")]
        with MCPStdioClient(command, cwd=ROOT, timeout=2) as client:
            client.start()
            with self.assertRaises(ToolPolicyError):
                client.call_tool("echo", {}, allowed_names={"echo"})
            with self.assertRaises(ToolPolicyError):
                client.request("tools/call", {"name": "echo", "arguments": {}})

    def test_tool_not_allowlisted_is_blocked(self):
        command = [sys.executable, str(ROOT / "tests/fixtures/fake_mcp_server.py")]
        with MCPStdioClient(command, cwd=ROOT, timeout=2) as client:
            client.start()
            with self.assertRaises(MCPTransportError):
                client.call_tool("exec", {}, allowed_names={"echo"},
                    invocation_context=object())


if __name__ == "__main__":
    unittest.main()
