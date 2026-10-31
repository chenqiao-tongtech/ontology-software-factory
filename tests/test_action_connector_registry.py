import json
import tempfile
import unittest
from pathlib import Path

from ontology_software_factory.action_connector_registry import (
    ActionConnectorPolicyError, ActionConnectorRegistry,
)

ROOT = Path(__file__).resolve().parents[1]


class ActionConnectorRegistryTests(unittest.TestCase):
    def test_empty_registry_denies_all_outbound_actions(self):
        registry = ActionConnectorRegistry(ROOT)
        with self.assertRaises(ActionConnectorPolicyError):
            registry.authorize("unconfigured", tool_id="documents.read", method="POST")

    def test_explicit_connector_binding_and_no_approval_downgrade(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "policies").mkdir()
            (root / "tools").mkdir()
            (root / "policies/action-connectors.json").write_text(json.dumps({
                "schemaVersion": "1.0.0", "defaultDecision": "deny",
                "connectors": [{
                    "connectorId": "deploy-prod", "adapterType": "http-json",
                    "toolIds": ["release.simulation.promote"], "methods": ["POST"],
                    "approvalRequired": False, "idempotencyRequired": True,
                }],
            }))
            (root / "tools/registry.json").write_text(json.dumps({"tools": [{
                "toolId": "release.simulation.promote", "approvalRequired": True,
            }]}))
            with self.assertRaises(ValueError):
                ActionConnectorRegistry(root)

    def test_valid_connector_is_scoped_to_one_tool_and_method(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "policies").mkdir()
            (root / "tools").mkdir()
            (root / "policies/action-connectors.json").write_text(json.dumps({
                "schemaVersion": "1.0.0", "defaultDecision": "deny",
                "connectors": [{
                    "connectorId": "mcp-docs", "adapterType": "mcp-stdio",
                    "toolIds": ["documents.read"], "methods": ["MCP_TOOLS_CALL"],
                    "approvalRequired": True, "idempotencyRequired": True,
                }],
            }))
            (root / "tools/registry.json").write_text(json.dumps({"tools": [{
                "toolId": "documents.read", "approvalRequired": False,
            }]}))
            registry = ActionConnectorRegistry(root)
            self.assertEqual(registry.authorize("mcp-docs", tool_id="documents.read",
                method="MCP_TOOLS_CALL").adapter_type, "mcp-stdio")
            with self.assertRaises(ActionConnectorPolicyError):
                registry.authorize("mcp-docs", tool_id="documents.read", method="POST")


if __name__ == "__main__":
    unittest.main()
