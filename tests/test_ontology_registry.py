import sqlite3
import tempfile
import unittest
from pathlib import Path

from ontology_software_factory.ontology_registry import OntologyRegistryError, SQLiteOntologyRegistry
from ontology_software_factory.ontology_versioning import create_snapshot


def ontology(version, classes=None):
    return {
        "ontologyId": "test-domain",
        "ontologyVersion": version,
        "schemaVersion": "1.0.0",
        "classes": classes or [{"name": "Order", "description": "An order"}],
        "relations": [],
    }


class OntologyRegistryTests(unittest.TestCase):
    def test_snapshot_registration_is_content_addressed_and_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            snapshot = create_snapshot(ontology("1.0.0"), actor="domain-owner", reason="initial baseline")
            with SQLiteOntologyRegistry(Path(tmp) / "registry.sqlite3") as registry:
                first = registry.register_snapshot(snapshot)
                second = registry.register_snapshot(snapshot)
                self.assertTrue(first["created"])
                self.assertFalse(second["created"])
                self.assertEqual(registry.get_snapshot(snapshot["snapshotId"])["digest"], snapshot["digest"])
                self.assertEqual(len(registry.list_snapshots()), 1)

    def test_registry_rejects_snapshot_digest_tampering_and_immutable_update(self):
        with tempfile.TemporaryDirectory() as tmp:
            snapshot = create_snapshot(ontology("1.0.0"), actor="owner", reason="baseline")
            with SQLiteOntologyRegistry(Path(tmp) / "registry.sqlite3") as registry:
                registry.register_snapshot(snapshot)
                tampered = dict(snapshot)
                tampered["ontology"] = ontology("9.9.9")
                with self.assertRaises(OntologyRegistryError):
                    registry.register_snapshot(tampered)
                with self.assertRaises(sqlite3.IntegrityError):
                    registry._connection.execute(
                        "UPDATE ontology_snapshots SET reason='changed' WHERE snapshot_id=?",
                        (snapshot["snapshotId"],),
                    )

    def test_activation_uses_optimistic_pointer_and_append_only_events(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = create_snapshot(ontology("1.0.0"), actor="owner", reason="baseline")
            second = create_snapshot(ontology("1.1.0", [{"name": "Order"}, {"name": "Payment"}]), actor="owner", reason="extension")
            with SQLiteOntologyRegistry(Path(tmp) / "registry.sqlite3") as registry:
                registry.register_snapshot(first)
                registry.register_snapshot(second)
                activated = registry.activate_snapshot(
                    first["snapshotId"], ontology_id="test-domain",
                    expected_active_snapshot_id=None, actor="release-operator",
                    approval_ref="CAB-001", proposal_id="proposal-1", occurred_at="2026-10-30T00:00:00Z",
                )
                self.assertIsNone(activated["previousSnapshotId"])
                with self.assertRaises(OntologyRegistryError):
                    registry.activate_snapshot(
                        second["snapshotId"], ontology_id="test-domain",
                        expected_active_snapshot_id=None, actor="release-operator",
                        approval_ref="CAB-002", proposal_id="proposal-2", occurred_at="2026-10-30T00:01:00Z",
                    )
                registry.activate_snapshot(
                    second["snapshotId"], ontology_id="test-domain",
                    expected_active_snapshot_id=first["snapshotId"], actor="release-operator",
                    approval_ref="CAB-002", proposal_id="proposal-2", occurred_at="2026-10-30T00:02:00Z",
                )
                pointer = registry.get_active_pointer("test-domain")
                self.assertEqual(pointer["snapshot_id"], second["snapshotId"])
                self.assertEqual(pointer["previous_snapshot_id"], first["snapshotId"])
                self.assertEqual([x["action"] for x in registry.list_events("test-domain")], ["snapshot-registered", "snapshot-registered", "activate", "activate"])

    def test_legacy_active_pointer_is_imported_without_faking_human_approval(self):
        with tempfile.TemporaryDirectory() as tmp:
            snapshot = create_snapshot(ontology("1.0.0"), actor="old-portal", reason="legacy snapshot")
            with SQLiteOntologyRegistry(Path(tmp) / "registry.sqlite3") as registry:
                registry.register_snapshot(snapshot)
                self.assertTrue(registry.import_legacy_active("test-domain", snapshot["snapshotId"]))
                pointer = registry.get_active_pointer("test-domain")
                self.assertEqual(pointer["approval_ref"], "legacy-state-import")
                self.assertEqual(registry.list_events("test-domain")[-1]["action"], "legacy-import")


if __name__ == "__main__":
    unittest.main()
