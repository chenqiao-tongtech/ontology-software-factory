from __future__ import annotations
import unittest
from pathlib import Path
from ontology_software_factory.tool_registry import ToolRegistry, ToolPolicyError

ROOT = Path(__file__).resolve().parents[1]


class AgentMetadataToolTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.registry = ToolRegistry(ROOT, {
            "ontology.definition.read": lambda payload: self.calls.append(("ontology", payload)) or {"classes": []},
            "source.catalog.read": lambda payload: self.calls.append(("sources", payload)) or {"connectors": []},
            "dependencies.inspect": lambda payload: self.calls.append(("dependencies", payload)) or {"dependencies": []},
        })

    def test_read_tools_are_enabled_only_for_declared_roles(self):
        self.assertIn("ontology.definition.read", self.registry.effective_tools("solution-architect"))
        self.assertIn("source.catalog.read", self.registry.effective_tools("ontology-discovery-agent"))
        self.assertIn("dependencies.inspect", self.registry.effective_tools("security-reviewer"))
        self.assertNotIn("dependencies.inspect", self.registry.effective_tools("requirement-analyst"))

    def test_tool_input_schemas_reject_extra_fields(self):
        with self.assertRaises(ValueError):
            self.registry.invoke("solution-architect", "ontology.definition.read",
                                 {"conceptName": "Product", "path": "/etc/passwd"})
        with self.assertRaises(ValueError):
            self.registry.invoke("ontology-discovery-agent", "source.catalog.read",
                                 {"category": "unknown"})

    def test_read_tool_invocation_uses_injected_handler(self):
        result = self.registry.invoke("solution-architect", "ontology.definition.read",
                                       {"conceptName": "Product"})
        self.assertEqual(result, {"classes": []})
        self.assertEqual(self.calls[0][0], "ontology")

    def test_unknown_role_is_denied(self):
        with self.assertRaises(ToolPolicyError):
            self.registry.invoke("unknown-role", "ontology.definition.read", {})


if __name__ == "__main__":
    unittest.main()
