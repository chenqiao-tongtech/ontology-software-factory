from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from ontology_software_factory.llm_provider import LLMResponse
from ontology_software_factory.ontology_discovery_service import (
    collect_local_source_materials,
    create_live_provider,
    approve_llm_candidate_artifact,
    run_live_ontology_discovery,
    to_portal_candidate,
)
from ontology_software_factory.ontology_discovery import OntologyDiscoveryError


ROOT = Path(__file__).resolve().parents[1]


class FixtureProvider:
    def __init__(self):
        self.responses = json.loads((ROOT / "examples/ontology-discovery/demo-model-responses.json").read_text(encoding="utf-8"))
    def generate_structured(self, request, *, schema_name, schema):
        stage = request.metadata["stage_id"]
        return copy.deepcopy(self.responses[stage]), LLMResponse(
            "fixture", "unit-test-fixture", stage, "fixture", 1,
            {"input_tokens": 10, "output_tokens": 12, "total_tokens": 22}, 1,
        )


class OntologyDiscoveryServiceTests(unittest.TestCase):
    def _source(self, directory):
        source_file = ROOT / "examples/ontology-discovery/source-docs/software-factory-requirements.md"
        (directory / source_file.name).write_text(source_file.read_text(encoding="utf-8"), encoding="utf-8")
        return {"id": "fixture:software-factory-requirements", "name": "Domain docs", "type": "documents", "path": str(directory), "enabled": True}

    def test_collects_only_explicit_local_source_and_tracks_file_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = self._source(Path(tmp))
            materials, index = collect_local_source_materials([source], ["fixture:software-factory-requirements"], root=tmp)
            self.assertEqual(len(materials), 1)
            self.assertIn("SOURCE FILE: software-factory-requirements.md", materials[0].content)
            self.assertIn("fixture:software-factory-requirements::software-factory-requirements.md", index)
            self.assertEqual(len(index["fixture:software-factory-requirements::software-factory-requirements.md"]["sha256"]), 64)

    def test_live_discovery_builds_portal_candidate_and_persists_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = self._source(Path(tmp))
            output = Path(tmp) / "candidates"
            result = run_live_ontology_discovery(
                [source], ["fixture:software-factory-requirements"], domain="software-factory", root=tmp,
                output_root=output, usage_path=Path(tmp) / "usage.jsonl",
                provider=FixtureProvider(),
            )
            portal = to_portal_candidate(result, [source], [{
                "id": "fixture:software-factory-requirements", "status": "connected", "assetCount": 1,
                "assets": [{"path": "software-factory-requirements.md", "assetId": "asset-1", "sha256": result["assetIndex"]["fixture:software-factory-requirements::software-factory-requirements.md"]["sha256"]}],
            }])
            self.assertEqual(portal["engine"], "llm-structured-discovery")
            self.assertTrue(portal["candidateDigest"])
            self.assertTrue(Path(result["artifactPath"]).is_file())
            self.assertTrue(all(term["evidence"] for term in portal["terms"]))
            self.assertTrue(all(e["verified"] for term in portal["terms"] for e in term["evidence"]))

    def test_approval_persists_digest_bound_human_approved_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = self._source(Path(tmp))
            result = run_live_ontology_discovery(
                [source], ["fixture:software-factory-requirements"], domain="software-factory", root=tmp,
                output_root=Path(tmp) / "candidates", usage_path=Path(tmp) / "usage.jsonl",
                provider=FixtureProvider(),
            )
            approved = approve_llm_candidate_artifact(
                result["candidate"]["candidateId"],
                candidate_root=Path(tmp) / "candidates",
                approved_root=Path(tmp) / "approved",
                reviewer_id="human-reviewer",
                approval_ref="CAB-2026-123",
                expected_digest=result["candidate"]["candidateDigest"],
            )
            self.assertEqual(approved["candidate"]["status"], "approved")
            self.assertEqual(approved["candidate"]["approval"]["approvalRef"], "CAB-2026-123")
            self.assertTrue(Path(approved["artifactPath"]).is_file())

    def test_approval_refuses_digest_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = self._source(Path(tmp))
            result = run_live_ontology_discovery(
                [source], ["fixture:software-factory-requirements"], domain="software-factory", root=tmp,
                output_root=Path(tmp) / "candidates", usage_path=Path(tmp) / "usage.jsonl",
                provider=FixtureProvider(),
            )
            with self.assertRaises(OntologyDiscoveryError):
                approve_llm_candidate_artifact(
                    result["candidate"]["candidateId"],
                    candidate_root=Path(tmp) / "candidates",
                    approved_root=Path(tmp) / "approved",
                    reviewer_id="human-reviewer",
                    approval_ref="CAB-2026-123",
                    expected_digest="0" * 64,
                )

    def test_live_provider_requires_explicit_opt_in_and_api_key(self):
        with self.assertRaises(OntologyDiscoveryError):
            create_live_provider({"OPENAI_API_KEY": "not-used"})
        with self.assertRaises(OntologyDiscoveryError):
            create_live_provider({"FACTORY_ENABLE_LLM_ONTOLOGY_DISCOVERY": "1"})

    def test_remote_sources_are_not_accepted_for_live_content_discovery(self):
        with self.assertRaises(OntologyDiscoveryError):
            collect_local_source_materials(
                [{"id": "remote", "type": "github", "url": "https://github.com/acme/repo", "enabled": True}],
                ["remote"], root=ROOT,
            )


if __name__ == "__main__":
    unittest.main()
