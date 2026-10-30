from __future__ import annotations

import importlib.util
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "run_factory_portal.py"
SPEC = importlib.util.spec_from_file_location("factory_portal_module", SCRIPT)
portal = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(portal)


class FactoryPortalServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.originals = {name: getattr(portal, name) for name in ("STATE_DIR", "STATE_PATH", "SOURCES_PATH")}
        portal.STATE_DIR = self.base / ".portal-state"
        portal.STATE_PATH = portal.STATE_DIR / "state.json"
        portal.SOURCES_PATH = self.base / "sources.json"
        self.repo = self.base / "repo"
        self.repo.mkdir()
        (self.repo / "example.py").write_text("class ExampleEntity:\n    pass\n\ndef create_example():\n    return 1\n", encoding="utf-8")
        (self.repo / "README.md").write_text("# Example Domain\n\n## Candidate Model\n", encoding="utf-8")
        (self.repo / ".env").write_text("SHOULD_NOT_BE_SCANNED=true\n", encoding="utf-8")
        self.docs = self.base / "docs"
        self.docs.mkdir()
        (self.docs / "domain.md").write_text("# Customer Domain\n", encoding="utf-8")
        self.db_path = self.base / "sample.sqlite3"
        with sqlite3.connect(self.db_path) as db:
            db.execute("CREATE TABLE orders (order_id TEXT PRIMARY KEY, customer_id TEXT NOT NULL)")
            db.execute("CREATE VIEW active_orders AS SELECT order_id FROM orders")
        portal.dump(portal.SOURCES_PATH, {"schemaVersion": "1.0.0", "sources": [
            {"id": "test-repo", "name": "Test repository", "type": "repository", "path": str(self.repo), "enabled": True, "fixture": False},
            {"id": "test-db", "name": "Test database", "type": "sqlite", "path": str(self.db_path), "enabled": True, "fixture": True},
            {"id": "test-docs", "name": "Test documents", "type": "documents", "path": str(self.docs), "enabled": True, "fixture": False},
        ]})

    def tearDown(self):
        for name, value in self.originals.items():
            setattr(portal, name, value)
        self.tmp.cleanup()

    def test_directory_connector_filters_hidden_secret_file(self):
        source = portal.source_configs()[0]
        result = portal.scan_source(source)
        self.assertEqual(result["status"], "connected")
        self.assertGreaterEqual(result["assetCount"], 2)
        paths = {item["path"] for item in result["assets"]}
        self.assertNotIn(".env", paths)
        self.assertTrue(all(not path.startswith(".") for path in paths))
        self.assertTrue(all(item.get("sha256") for item in result["assets"]))
        self.assertEqual(result["details"]["connector"], "LocalDirectoryConnector")

    def test_document_directory_uses_the_same_connector_contract(self):
        source = portal.source_configs()[2]
        result = portal.scan_source(source)
        self.assertEqual(result["status"], "connected")
        self.assertEqual(result["details"]["connector"], "LocalDirectoryConnector")
        self.assertEqual(result["assets"][0]["path"], "domain.md")

    def test_sqlite_connector_reads_schema_and_is_read_only(self):
        result = portal.scan_source(portal.source_configs()[1])
        self.assertEqual(result["status"], "connected")
        names = {item["name"] for item in result["details"]["tables"]}
        self.assertEqual(names, {"orders", "active_orders"})
        self.assertEqual(result["details"]["connector"], "SQLiteSchemaConnector")
        self.assertIn("customer_id", {column["name"] for table in result["details"]["tables"] for column in table["columns"]})
        with sqlite3.connect(self.db_path) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM orders").fetchone()[0], 0)

    def test_formal_ontology_graph_has_resolvable_endpoints(self):
        graph = portal.load_ontology()
        names = {node["name"] for node in graph["classes"]}
        self.assertGreater(len(names), 10)
        self.assertGreater(len(graph["relations"]), 5)
        self.assertTrue(all(edge["source"] in names and edge["target"] in names for edge in graph["relations"]))

    def test_discovery_creates_candidate_with_source_evidence_and_no_promotion(self):
        candidate = portal.discover_candidates()
        self.assertEqual(candidate["engine"], "local-rule-based-extraction")
        self.assertIn("ExampleEntity", {term["label"] for term in candidate["terms"]})
        self.assertIn("customer_id", {term["label"] for term in candidate["terms"]})
        self.assertTrue(all(term["evidence"] for term in candidate["terms"]))
        evidence = next(item for term in candidate["terms"] for item in term["evidence"] if item.get("sourceType") == "repository")
        self.assertEqual(evidence["sourceId"], "test-repo")
        self.assertEqual(evidence["sourceName"], "Test repository")
        self.assertTrue(evidence.get("assetId"))
        self.assertTrue(evidence.get("contentSha256"))
        self.assertTrue(evidence.get("scannedAt"))
        db_term = next(term for term in candidate["terms"] if term["label"] == "customer_id")
        db_evidence = next(item for item in db_term["evidence"] if item.get("sourceType") == "sqlite")
        self.assertTrue(db_evidence.get("assetId"))
        self.assertEqual(db_evidence["path"], "table:orders")
        self.assertIn(candidate["candidateId"], {x["candidateId"] for x in portal.state_read()["ontologyCandidates"]})
        self.assertIn("不会自动", candidate["notice"])

    def test_deterministic_agent_run_moves_through_review_and_decision(self):
        run = portal.create_agent_run("test run")
        self.assertEqual(run["runtimeMode"], "deterministic-fixture")
        for _ in range(5):
            run = portal.advance_agent_run(run["runId"])
        self.assertEqual(run["status"], "waiting_approval")
        self.assertTrue(all(step["status"] == "succeeded" for step in run["steps"]))
        run = portal.decide_agent_run(run["runId"], True, "reviewer", "test evidence reviewed")
        self.assertEqual(run["status"], "succeeded")
        self.assertEqual(run["approval"]["approver"], "reviewer")

    def test_approval_rejects_missing_actor_or_reason(self):
        run = portal.create_agent_run("test approval")
        for _ in range(5):
            run = portal.advance_agent_run(run["runId"])
        with self.assertRaises(ValueError):
            portal.decide_agent_run(run["runId"], True, "", "reason")
        with self.assertRaises(ValueError):
            portal.decide_agent_run(run["runId"], True, "reviewer", "")

    def test_github_metadata_connector_uses_api_tree_and_does_not_return_token(self):
        source = {"id": "remote-test", "name": "remote", "type": "github", "url": "https://github.com/acme/example", "tokenEnv": "TEST_GITHUB_TOKEN", "enabled": True}
        with patch.dict("os.environ", {"TEST_GITHUB_TOKEN": "never-echo-this"}), patch.object(portal, "_remote_json") as mocked:
            mocked.side_effect = [
                (200, {"default_branch": "main", "private": True, "visibility": "private", "pushed_at": "2026-10-01T00:00:00Z"}),
                (200, {"sha": "tree-sha", "truncated": False, "tree": [
                    {"path": "src/domain.py", "type": "blob", "size": 120},
                    {"path": "docs/contract.md", "type": "blob", "size": 80},
                    {"path": ".github/workflows/ci.yml", "type": "blob", "size": 40},
                    {"path": "node_modules/vendor.js", "type": "blob", "size": 500},
                ]}),
            ]
            result = portal.scan_source(source, allow_remote=True)
        self.assertEqual(result["status"], "connected")
        self.assertEqual(result["assetCount"], 2)
        self.assertEqual(result["details"]["connector"], "RemoteRepositoryConnector")
        self.assertEqual(result["details"]["sourceRevision"], "tree-sha")
        self.assertEqual(result["assets"][0]["browseUrl"], "https://github.com/acme/example/blob/main/src/domain.py")
        self.assertTrue(result["details"]["tokenConfigured"])
        self.assertNotIn("never-echo-this", json.dumps(result))
        self.assertEqual(mocked.call_count, 2)

    def test_gitlab_metadata_connector_accepts_only_gitlab_com_and_uses_project_api(self):
        source = {"id": "remote-gitlab", "name": "gitlab", "type": "gitlab", "url": "https://gitlab.com/group/subgroup/project", "tokenEnv": "TEST_GITLAB_TOKEN", "enabled": True}
        with patch.dict("os.environ", {"TEST_GITLAB_TOKEN": "never-echo-this"}), patch.object(portal, "_remote_json") as mocked:
            mocked.side_effect = [
                (200, {"default_branch": "main", "visibility": "private", "last_activity_at": "2026-10-01T00:00:00Z"}),
                (200, [{"path": "src/domain.py", "type": "blob"}, {"path": "docs/model.md", "type": "blob"}]),
            ]
            result = portal.scan_source(source, allow_remote=True)
        self.assertEqual(result["status"], "connected")
        self.assertEqual(result["assetCount"], 2)
        self.assertEqual(result["details"]["connector"], "RemoteRepositoryConnector")
        self.assertNotIn("never-echo-this", json.dumps(result))
        self.assertIn("/api/v4/projects/group%2Fsubgroup%2Fproject", mocked.call_args_list[0].args[0])

    def test_remote_asset_browse_urls_are_provider_allowlisted_and_encoded(self):
        github = {"type": "github", "url": "https://github.com/acme/example"}
        gitlab = {"type": "gitlab", "url": "https://gitlab.com/group/subgroup/project"}
        self.assertEqual(
            portal.remote_asset_browse_url(github, "src/a file.py", "main"),
            "https://github.com/acme/example/blob/main/src/a%20file.py",
        )
        self.assertEqual(
            portal.remote_asset_browse_url(gitlab, "docs/model.md", "release/1"),
            "https://gitlab.com/group/subgroup/project/-/blob/release/1/docs/model.md",
        )
        self.assertIsNone(portal.remote_asset_browse_url(
            {"type": "github", "url": "https://attacker.example/acme/example"},
            "src/domain.py", "main",
        ))

    def test_source_sync_history_records_duration_status_and_error_class(self):
        def fake_scan(source, *, allow_remote=False):
            status = "connected" if source["id"] != "test-docs" else "unavailable"
            return {
                "id": source["id"], "name": source["name"], "type": source["type"],
                "pathLabel": source.get("path", ""), "lastSyncAt": portal.now_iso(),
                "status": status, "assetCount": 3 if status == "connected" else 0,
                "assets": [], "details": {},
                "message": "provider unavailable" if status == "unavailable" else "ok",
            }
        with patch.object(portal, "scan_source", side_effect=fake_scan):
            results = portal.source_scan_results(force=True)
        repo_result = next(x for x in results if x["id"] == "test-repo")
        docs_result = next(x for x in results if x["id"] == "test-docs")
        self.assertGreaterEqual(repo_result["lastSyncDurationMs"], 0)
        self.assertEqual(repo_result["syncHistory"][-1]["assetCount"], 3)
        self.assertIsNone(repo_result["lastErrorClass"])
        self.assertEqual(docs_result["lastErrorClass"], "provider-unavailable")
        history = portal.state_read()["sourceSyncHistory"]
        self.assertEqual(len(history["test-repo"]), 1)
        self.assertEqual(history["test-docs"][-1]["status"], "unavailable")

    def test_remote_connector_rejects_non_https_and_non_provider_hosts(self):
        source = {"id": "bad-remote", "name": "bad", "type": "github", "url": "http://127.0.0.1/secret", "enabled": True}
        result = portal.scan_source(source, allow_remote=True)
        self.assertEqual(result["status"], "invalid-url")
        self.assertEqual(result["assetCount"], 0)

    def test_background_source_refresh_does_not_call_remote_provider(self):
        remote_sources = [
            {"id": "source-github", "name": "Remote", "type": "github", "url": "https://github.com/acme/example", "enabled": True},
            {"id": "source-pg", "name": "Database", "type": "postgresql", "connectionEnv": "FACTORY_PG_URL", "allowedHosts": ["db.internal"], "enabled": True}
        ]
        portal.dump(portal.SOURCES_PATH, {"schemaVersion": "1.0.0", "sources": remote_sources})
        with patch.object(portal, "_remote_json", side_effect=AssertionError("background refresh must not make network calls")):
            results = portal.source_scan_results(force=True, allow_remote=False)
        self.assertEqual(results[0]["status"], "not-synced")
        self.assertEqual(results[1]["status"], "not-synced")


if __name__ == "__main__":
    unittest.main()
