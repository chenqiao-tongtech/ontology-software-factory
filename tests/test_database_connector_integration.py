"""Opt-in live database integration checks.

Set the documented FACTORY_TEST_* variables to run against dedicated, non-production
test databases. These tests only invoke the schema scanners; they never issue business
table SELECT statements or mutate connected databases.
"""
from __future__ import annotations

import os
import unittest
from urllib.parse import urlparse
from unittest.mock import patch

from ontology_software_factory.database_connectors import MySQLSchemaConnector, PostgreSQLSchemaConnector


class PostgreSQLLiveIntegrationTests(unittest.TestCase):
    @unittest.skipUnless(os.getenv("FACTORY_TEST_POSTGRES_DSN"), "FACTORY_TEST_POSTGRES_DSN not configured")
    def test_live_postgresql_schema_scan(self):
        dsn = os.environ["FACTORY_TEST_POSTGRES_DSN"]
        host = urlparse(dsn).hostname
        self.assertTrue(host)
        env_name = "FACTORY_TEST_POSTGRES_CONN"
        with patch.dict(os.environ, {env_name: dsn}):
            result = PostgreSQLSchemaConnector(allowed_hosts=[host]).scan("integration-postgres", env_name)
        self.assertEqual(result.status, "connected")
        self.assertTrue(all((asset.metadata or {}).get("readOnly") for asset in result.assets))
        self.assertTrue(all("columns" in (asset.metadata or {}) for asset in result.assets))
        expected = os.getenv("FACTORY_TEST_POSTGRES_EXPECT_TABLE")
        if expected:
            self.assertIn(expected, {asset.locator for asset in result.assets})


class MySQLLiveIntegrationTests(unittest.TestCase):
    @unittest.skipUnless(os.getenv("FACTORY_TEST_MYSQL_DSN"), "FACTORY_TEST_MYSQL_DSN not configured")
    def test_live_mysql_schema_scan(self):
        dsn = os.environ["FACTORY_TEST_MYSQL_DSN"]
        host = urlparse(dsn).hostname
        self.assertTrue(host)
        env_name = "FACTORY_TEST_MYSQL_CONN"
        with patch.dict(os.environ, {env_name: dsn}):
            result = MySQLSchemaConnector(allowed_hosts=[host]).scan("integration-mysql", env_name)
        self.assertEqual(result.status, "connected")
        self.assertTrue(all((asset.metadata or {}).get("readOnly") for asset in result.assets))
        self.assertTrue(all("columns" in (asset.metadata or {}) for asset in result.assets))
        expected = os.getenv("FACTORY_TEST_MYSQL_EXPECT_TABLE")
        if expected:
            self.assertIn(expected, {asset.locator for asset in result.assets})


if __name__ == "__main__":
    unittest.main()
