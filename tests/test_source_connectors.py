from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from ontology_software_factory.source_connectors import (
    LocalDirectoryConnector,
    SQLiteSchemaConnector,
    SourceConnectorError,
    SourceConnectorRegistry,
)


class SourceConnectorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.project = self.root / "project"
        self.project.mkdir()
        (self.project / "src").mkdir()
        (self.project / "src" / "domain.py").write_text(
            "class Order:\n    pass\n", encoding="utf-8"
        )
        (self.project / "README.md").write_text("# Domain\n", encoding="utf-8")
        (self.project / ".env").write_text("TOKEN=must-not-be-indexed", encoding="utf-8")
        (self.project / "id_rsa").write_text("private material", encoding="utf-8")
        (self.project / "image.png").write_bytes(b"not text")
        (self.project / "node_modules").mkdir()
        (self.project / "node_modules" / "ignored.js").write_text("ignored", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_directory_connector_only_indexes_allowed_text_assets(self):
        connector = LocalDirectoryConnector([self.root])
        result = connector.scan("repo-1", self.project)
        locators = {asset.locator for asset in result.assets}
        self.assertEqual(result.status, "connected")
        self.assertEqual(locators, {"README.md", "src/domain.py"})
        self.assertTrue(all(asset.content_sha256 for asset in result.assets))
        self.assertTrue(all(asset.source_id == "repo-1" for asset in result.assets))

    def test_directory_connector_rejects_outside_root(self):
        outside = Path(self.tmp.name).parent
        connector = LocalDirectoryConnector([self.project])
        with self.assertRaises(SourceConnectorError):
            connector.scan("outside", outside)

    def test_directory_connector_skips_symlink_escape(self):
        outside_file = self.root / "outside.py"
        outside_file.write_text("class Secret:\n    pass\n", encoding="utf-8")
        link = self.project / "escape.py"
        try:
            link.symlink_to(outside_file)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks are unavailable on this platform")
        result = LocalDirectoryConnector([self.root]).scan("repo-1", self.project)
        self.assertNotIn("escape.py", {asset.locator for asset in result.assets})

    def test_max_file_limit_is_explicitly_partial(self):
        result = LocalDirectoryConnector([self.root], max_files=1).scan("repo-1", self.project)
        self.assertEqual(result.status, "partial")
        self.assertEqual(len(result.assets), 1)
        self.assertTrue(any("file limit reached" in warning for warning in result.warnings))

    def test_sqlite_connector_reads_schema_without_reading_or_writing_rows(self):
        database = self.root / "catalog.sqlite3"
        with sqlite3.connect(database) as connection:
            connection.execute(
                'CREATE TABLE "order items" (order_id TEXT PRIMARY KEY, customer_id TEXT NOT NULL)'
            )
            connection.execute('CREATE VIEW active_orders AS SELECT order_id FROM "order items"')
            connection.execute('INSERT INTO "order items" VALUES ("o-1", "c-1")')
        result = SQLiteSchemaConnector([self.root]).scan("db-1", database)
        by_name = {asset.name: asset for asset in result.assets}
        self.assertEqual(result.status, "connected")
        self.assertEqual(set(by_name), {"order items", "active_orders"})
        columns = by_name["order items"].metadata["columns"]
        self.assertEqual([column["name"] for column in columns], ["order_id", "customer_id"])
        with sqlite3.connect(database) as connection:
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM "order items"').fetchone()[0], 1)

    def test_sqlite_connector_rejects_outside_root(self):
        database = self.root / "catalog.sqlite3"
        with sqlite3.connect(database):
            pass
        connector = SQLiteSchemaConnector([self.project])
        with self.assertRaises(SourceConnectorError):
            connector.scan("db-1", database)

    def test_repository_and_document_directory_types_can_be_registered_separately(self):
        registry = SourceConnectorRegistry()
        registry.register(LocalDirectoryConnector([self.root], source_type="repository"))
        registry.register(LocalDirectoryConnector([self.root], source_type="documents"))
        result = registry.scan("documents", "docs-1", self.project)
        self.assertEqual(result.source_type, "documents")
        self.assertGreater(len(result.assets), 0)

    def test_registry_fails_closed_for_unknown_connector(self):
        registry = SourceConnectorRegistry()
        registry.register(LocalDirectoryConnector([self.root]))
        with self.assertRaises(SourceConnectorError):
            registry.scan("remote-git", "git-1", "https://example.invalid/repo")


if __name__ == "__main__":
    unittest.main()
