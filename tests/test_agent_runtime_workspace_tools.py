import tempfile
import unittest
from pathlib import Path

from ontology_software_factory.agent_runtime import OpenAIAgentsRuntime
from ontology_software_factory.workspace_execution import WorkspaceManager, WorkspaceExecution


def identity_function_tool(**kwargs):
    def decorate(function):
        return function
    return decorate


class AgentRuntimeWorkspaceToolTests(unittest.TestCase):
    def test_role_tools_are_registered_only_with_a_run_workspace(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "checkout"
            (root / "agents" / "roles").mkdir(parents=True)
            (root / "agents" / "roles" / "implementation-agent.json").write_text(
                '{"roleId":"implementation-agent","toolIds":["workspace.read","repository.branch.write","tests.run","repository.merge"]}',
                encoding="utf-8",
            )
            manager = WorkspaceManager(root, workspace_root=Path(temp) / "workspaces")
            workspace_path = manager.open("runtime-test")
            runtime = OpenAIAgentsRuntime.__new__(OpenAIAgentsRuntime)
            runtime.project_root = root
            runtime._function_tool = identity_function_tool
            base_tools = runtime._build_tools(identity_function_tool)
            self.assertNotIn("repository.branch.write", base_tools)
            scoped = runtime._build_tools(
                identity_function_tool,
                WorkspaceExecution(root, workspace_path, run_id="runtime-test"),
            )
            self.assertTrue({
                "workspace.read", "repository.branch.write", "architecture.plan.write",
                "tests.run", "security.scan",
            }.issubset(scoped))
            implementation_tools = runtime.effective_tool_ids(
                "implementation-agent", set(scoped)
            )
            self.assertIn("workspace.read", implementation_tools)
            self.assertIn("repository.branch.write", implementation_tools)
            self.assertIn("tests.run", implementation_tools)
            self.assertNotIn("repository.merge", implementation_tools)


if __name__ == "__main__":
    unittest.main()
