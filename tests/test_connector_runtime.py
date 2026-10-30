from __future__ import annotations
import json
import tempfile
import unittest
from pathlib import Path
from ontology_software_factory.connector_catalog import ConnectorCatalog
from ontology_software_factory.connector_runtime import (
    ConnectorPrincipal, ConnectorRuntime, ConnectorRuntimeDenied,
    ConnectorRuntimeUnavailable, SourceBinding
)

ROOT = Path(__file__).resolve().parents[1]


class FakeSource:
    def scan(self, source_id, location):
        return {
            "sourceId": source_id, "sourceType": "fixture", "status": "complete",
            "assets": [{
                "asset_id": "asset-1", "source_id": source_id, "kind": "document",
                "name": "architecture", "locator": "docs/architecture.md",
                "content_sha256": "abc123", "size_bytes": 10,
                "metadata": {"classification": "internal"},
                "raw_content": "must not be returned", "api_key": "secret"
            }]
        }


class ConnectorRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.audit = Path(self.tmp.name) / "connector-audit.jsonl"
        self.catalog = ConnectorCatalog(ROOT)
        self.principal = ConnectorPrincipal("principal-1", "tenant-a")
        self.binding = SourceBinding("source-1", "source.local-directory", "tenant-a", "/tmp/source")
        self.runtime = ConnectorRuntime(
            catalog=self.catalog,
            source_adapters={"source.local-directory": FakeSource()},
            audit_path=self.audit,
        )

    def test_source_scan_returns_metadata_only_and_audit(self):
        result = self.runtime.scan_source(self.principal, self.binding)
        self.assertEqual(result["assetCount"], 1)
        asset = result["assets"][0]
        self.assertEqual(asset["assetId"], "asset-1")
        self.assertNotIn("raw_content", asset)
        self.assertNotIn("api_key", asset)
        event = json.loads(self.audit.read_text().splitlines()[0])
        self.assertEqual(event["status"], "complete")
        self.assertNotIn("location", event)

    def test_cross_tenant_binding_is_denied(self):
        binding = SourceBinding("source-1", "source.local-directory", "tenant-b", "/tmp/source")
        with self.assertRaises(ConnectorRuntimeDenied):
            self.runtime.scan_source(self.principal, binding)

    def test_unapproved_source_is_denied(self):
        binding = SourceBinding("source-1", "source.local-directory", "tenant-a", "/tmp/source", approved=False)
        with self.assertRaises(ConnectorRuntimeDenied):
            self.runtime.scan_source(self.principal, binding)

    def test_planned_connector_is_denied_by_catalog(self):
        binding = SourceBinding("source-2", "source.confluence", "tenant-a", "space", approved=True)
        with self.assertRaises(ConnectorPolicyError):
            self.runtime.scan_source(self.principal, binding)

    def test_declared_connector_without_adapter_is_unavailable(self):
        runtime = ConnectorRuntime(catalog=self.catalog, source_adapters={}, audit_path=self.audit)
        with self.assertRaises(ConnectorRuntimeUnavailable):
            runtime.scan_source(self.principal, self.binding)


if __name__ == "__main__":
    unittest.main()
