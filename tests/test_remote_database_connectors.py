from __future__ import annotations

import json
import os
import unittest
from unittest.mock import patch

from ontology_software_factory.remote_connectors import RemoteRepositoryConnector
from ontology_software_factory.database_connectors import MySQLSchemaConnector, PostgreSQLSchemaConnector
from ontology_software_factory.source_connectors import SourceConnectorError


class RemoteRepositoryConnectorTests(unittest.TestCase):
    def test_github_scan_returns_revision_and_never_token(self):
        calls = []
        def fake(url, headers):
            calls.append((url, headers))
            if len(calls) == 1:
                return 200, {"default_branch": "main", "visibility": "private", "pushed_at": "2026-10-30"}
            return 200, {"sha": "tree-revision-123", "truncated": False, "tree": [
                {"path": "src/OrderService.py", "type": "blob", "size": 42},
                {"path": ".github/workflows/ci.yml", "type": "blob", "size": 20},
                {"path": "node_modules/vendor.js", "type": "blob", "size": 10},
            ]}
        with patch.dict(os.environ, {"TEST_GH_TOKEN": "do-not-return-this"}):
            connector = RemoteRepositoryConnector("github", fake, token_env="TEST_GH_TOKEN")
            result = connector.scan("repo-1", "https://github.com/acme/orders")
        self.assertEqual(result.status, "connected")
        self.assertEqual(len(result.assets), 1)
        self.assertEqual(result.assets[0].metadata["sourceRevision"], "tree-revision-123")
        self.assertNotIn("do-not-return-this", json.dumps(result.as_dict()))
        self.assertEqual(calls[0][1]["Authorization"], "Bearer do-not-return-this")

    def test_gitlab_scan_supports_nested_group_paths(self):
        calls = []
        def fake(url, headers):
            calls.append(url)
            if "/projects/" in url and "/repository/tree" not in url:
                return 200, {"default_branch": "main", "visibility": "private", "last_activity_at": "2026-10-30"}
            return 200, [{"path": "domain/customer.proto", "type": "blob"}]
        result = RemoteRepositoryConnector("gitlab", fake).scan(
            "gl-1", "https://gitlab.com/group/subgroup/project"
        )
        self.assertEqual(result.status, "connected")
        self.assertEqual(result.assets[0].locator, "domain/customer.proto")
        self.assertIn("group%2Fsubgroup%2Fproject", calls[0])

    def test_remote_connector_rejects_host_injection_and_embedded_credentials(self):
        connector = RemoteRepositoryConnector("github", lambda *_: self.fail("network must not run"))
        for url in ("https://evil.example/acme/repo", "https://user:pass@github.com/acme/repo"):
            with self.subTest(url=url), self.assertRaises(SourceConnectorError):
                connector.scan("bad", url)


class DatabaseConnectorBoundaryTests(unittest.TestCase):
    def test_postgres_rejects_non_allowlisted_host_before_driver_access(self):
        connector = PostgreSQLSchemaConnector(allowed_hosts=["db.internal"])
        with patch.dict(os.environ, {"PG_CONN": "postgresql://user:pass@attacker.example/db?sslmode=require"}):
            with self.assertRaisesRegex(SourceConnectorError, "allow-list"):
                connector.scan("pg-1", "PG_CONN")

    def test_mysql_rejects_non_allowlisted_host_before_driver_access(self):
        connector = MySQLSchemaConnector(allowed_hosts=["db.internal"])
        with patch.dict(os.environ, {"MYSQL_CONN": "mysql://user:pass@attacker.example/db"}):
            with self.assertRaisesRegex(SourceConnectorError, "allow-list"):
                connector.scan("mysql-1", "MYSQL_CONN")

    def test_postgres_requires_tls_mode(self):
        connector = PostgreSQLSchemaConnector(allowed_hosts=["db.internal"])
        with patch.dict(os.environ, {"PG_CONN": "postgresql://user:pass@db.internal/db"}):
            with self.assertRaisesRegex(SourceConnectorError, "sslmode"):
                connector.scan("pg-1", "PG_CONN")


if __name__ == "__main__":
    unittest.main()
