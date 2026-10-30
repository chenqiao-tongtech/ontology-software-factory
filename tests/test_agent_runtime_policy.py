import tempfile
import unittest
from pathlib import Path

from ontology_software_factory.agent_runtime import AgentContractError, OpenAIAgentsRuntime


class AgentRuntimePolicyTests(unittest.TestCase):
    def make_runtime(self, root):
        runtime = OpenAIAgentsRuntime.__new__(OpenAIAgentsRuntime)
        runtime.project_root = Path(root).resolve()
        return runtime

    def test_safe_document_path_allowed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "docs").mkdir()
            (root / "docs" / "readme.md").write_text("safe", encoding="utf-8")
            path = self.make_runtime(root)._safe_read_path("docs/readme.md")
            self.assertEqual(path.read_text(encoding="utf-8"), "safe")

    def test_parent_traversal_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(AgentContractError):
                self.make_runtime(temp)._safe_read_path("docs/../../secret.txt")

    def test_env_file_is_outside_allowed_roots(self):
        with tempfile.TemporaryDirectory() as temp:
            (Path(temp) / ".env").write_text("secret", encoding="utf-8")
            with self.assertRaises(AgentContractError):
                self.make_runtime(temp)._safe_read_path(".env")

    def test_role_effective_tools_intersect_runtime_registry(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "agents" / "roles").mkdir(parents=True)
            (root / "agents" / "roles" / "requirement-analyst.json").write_text(
                '{"roleId":"requirement-analyst","toolIds":["documents.read","repository.write","contract.validate","production.deploy"]}',
                encoding="utf-8")
            runtime = self.make_runtime(root)
            runtime._tools_by_id = {"documents.read": object(), "contract.validate": object(), "catalog.read": object()}
            self.assertEqual(runtime.effective_tool_ids("requirement-analyst"), ["documents.read", "contract.validate"])


if __name__ == "__main__":
    unittest.main()
