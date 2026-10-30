from __future__ import annotations
import json
import tempfile
import unittest
from pathlib import Path
from ontology_software_factory.connector_catalog import ConnectorCatalog, ConnectorPolicyError

ROOT = Path(__file__).resolve().parents[1]


class ConnectorCatalogTests(unittest.TestCase):
    def setUp(self):
        self.catalog = ConnectorCatalog(ROOT)

    def test_source_and_action_planes_are_separated(self):
        sources = self.catalog.list_connectors(category="ontology-source")
        actions = self.catalog.list_connectors(category="agent-action")
        self.assertTrue(sources and actions)
        self.assertTrue(all(item.direction == "read" for item in sources))
        self.assertTrue(all(item.direction == "write" for item in actions))

    def test_implemented_connector_is_authorized_but_planned_is_not(self):
        self.assertEqual(self.catalog.authorize("source.sqlite", "scan.schema").implementation_status, "implemented")
        with self.assertRaises(ConnectorPolicyError):
            self.catalog.authorize("source.confluence", "search.pages")

    def test_unknown_operation_and_connector_fail_closed(self):
        with self.assertRaises(ConnectorPolicyError):
            self.catalog.authorize("source.sqlite", "read.rows")
        with self.assertRaises(ConnectorPolicyError):
            self.catalog.authorize("source.missing", "scan.schema")

    def test_registry_rejects_source_write_capability(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "connectors/schemas").mkdir(parents=True)
            (root / "connectors/schemas/connector-registry.schema.json").write_text(
                (ROOT / "connectors/schemas/connector-registry.schema.json").read_text(encoding="utf-8"), encoding="utf-8")
            data = json.loads((ROOT / "connectors/registry.json").read_text(encoding="utf-8"))
            data["connectors"][0]["direction"] = "write"
            (root / "connectors/registry.json").write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaises(ValueError):
                ConnectorCatalog(root)


if __name__ == "__main__":
    unittest.main()
