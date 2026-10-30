from __future__ import annotations
import asyncio
import copy
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from ontology_software_factory.llm_provider import LLMRequest, LLMResponse
from ontology_software_factory.task_runtime import SQLiteTaskStore, TaskWorker
from ontology_software_factory.ontology_discovery_worker import make_ontology_discovery_handler
from ontology_software_factory.ontology_discovery import (
    OntologyDiscoveryError, OntologyDiscoveryPipeline, SourceMaterial, approve_candidate,
    candidate_digest, evaluate_candidate, save_candidate, validate_ontology_candidate,
)
from ontology_software_factory.adapters.nvidia_auto_ontology import NvidiaAutoOntologyAdapter, NvidiaAutoOntologyError
from ontology_software_factory.adapters.cognee_ontology import (
    CogneeOntologyError, build_cognee_graph_schema, candidate_to_graph_document, stage_candidate_in_cognee,
)

ROOT = Path(__file__).resolve().parents[1]


class FixtureProvider:
    def __init__(self, *, overrides=None):
        self.responses = json.loads((ROOT / "examples/ontology-discovery/demo-model-responses.json").read_text(encoding="utf-8"))
        if overrides:
            self.responses.update(overrides)
        self.calls = []
    def generate_structured(self, request: LLMRequest, *, schema_name: str, schema: dict):
        stage = (request.metadata or {}).get("stage_id")
        self.calls.append(stage)
        response = copy.deepcopy(self.responses[stage])
        meta = LLMResponse("fixture", "unit-test-fixture", f"resp-{len(self.calls)}", "fixture", 1,
                           {"input_tokens": 10, "output_tokens": 12, "total_tokens": 22}, 1)
        return response, meta


def fixture_source(content: str | None = None) -> SourceMaterial:
    if content is None:
        content = (ROOT / "examples/ontology-discovery/source-docs/software-factory-requirements.md").read_text(encoding="utf-8")
    return SourceMaterial("fixture:software-factory-requirements", "markdown", "software-factory-requirements.md", content)


def discover(provider=None, source=None):
    provider = provider or FixtureProvider()
    return OntologyDiscoveryPipeline(provider).discover(domain="software-factory", sources=[source or fixture_source()])


class OntologyDiscoveryTests(unittest.TestCase):
    def test_multistage_pipeline_produces_review_candidate_with_verified_provenance(self):
        provider = FixtureProvider()
        candidate = discover(provider)
        self.assertEqual(provider.calls, ["term-discovery", "relation-discovery", "constraint-and-competency-questions", "independent-critic"])
        self.assertEqual(candidate["status"], "review_required")
        self.assertEqual(len(candidate["terms"]), 8)
        self.assertEqual(len(candidate["relations"]), 5)
        self.assertTrue(candidate["validation"]["locallyValid"])
        self.assertEqual(candidate["validation"]["provenanceCoverage"], 1.0)
        self.assertFalse(candidate["governance"]["productionOntologyMutation"])

    def test_candidate_evaluation_scores_fixture_but_never_promotes(self):
        candidate = discover()
        benchmark = json.loads((ROOT / "examples/ontology-discovery/benchmarks/software-factory-benchmark.json").read_text(encoding="utf-8"))
        report = evaluate_candidate(candidate, benchmark)
        self.assertTrue(report["passed"])
        self.assertEqual(report["termMetrics"]["f1"], 1.0)
        self.assertEqual(report["relationMetrics"]["f1"], 1.0)
        self.assertFalse(report["promotionAllowed"])

    def test_approval_is_digest_bound_and_requires_human_identity(self):
        candidate = discover()
        approved = approve_candidate(candidate, reviewer_id="domain-owner-17", approval_ref="ticket:ONTO-17",
                                     expected_digest=candidate_digest(candidate))
        self.assertEqual(approved["status"], "approved")
        self.assertEqual(approved["approval"]["approvedDigest"], approved["candidateDigest"])
        self.assertEqual(candidate_digest(approved), approved["candidateDigest"])
        with self.assertRaises(OntologyDiscoveryError):
            approve_candidate(candidate, reviewer_id="llm-reviewer", approval_ref="ticket:ONTO-17",
                             expected_digest=candidate_digest(candidate))
        with self.assertRaises(OntologyDiscoveryError):
            approve_candidate(candidate, reviewer_id="domain-owner-17", approval_ref="ticket:ONTO-17",
                             expected_digest="0" * 64)

    def test_secrets_are_blocked_before_model_call(self):
        provider = FixtureProvider()
        bad = fixture_source("token=sk-abcdefghijklmnopqrstuvwxyz0123456789")
        with self.assertRaises(OntologyDiscoveryError):
            OntologyDiscoveryPipeline(provider).discover(domain="x", sources=[bad])
        self.assertEqual(provider.calls, [])

    def test_unverifiable_source_quote_fails_closed_in_validation(self):
        fixture = json.loads((ROOT / "examples/ontology-discovery/demo-model-responses.json").read_text(encoding="utf-8"))
        fixture["term-discovery"]["terms"][0]["sourceRefs"][0]["quote"] = "this sentence does not exist"
        candidate = discover(FixtureProvider(overrides=fixture))
        self.assertFalse(candidate["validation"]["locallyValid"])
        self.assertIn("one or more source references are unverified", candidate["validation"]["errors"])

    def test_unresolved_relation_endpoint_is_reported(self):
        fixture = json.loads((ROOT / "examples/ontology-discovery/demo-model-responses.json").read_text(encoding="utf-8"))
        fixture["relation-discovery"]["relations"][0]["objectTerm"] = "UncataloguedObject"
        candidate = discover(FixtureProvider(overrides=fixture))
        self.assertFalse(candidate["validation"]["locallyValid"])
        self.assertTrue(any(f["code"] == "relation.unresolved_endpoint" for f in candidate["localFindings"]))

    def test_critic_blocker_prevents_candidate_validation(self):
        fixture = json.loads((ROOT / "examples/ontology-discovery/demo-model-responses.json").read_text(encoding="utf-8"))
        fixture["independent-critic"] = {"findings": [{"code": "semantic-conflict", "severity": "blocker",
            "message": "unresolved conflict", "affectedNames": ["Release"], "recommendedAction": "domain review"}]}
        candidate = discover(FixtureProvider(overrides=fixture))
        self.assertFalse(candidate["validation"]["locallyValid"])

    def test_secrets_in_context_are_blocked_before_model_call(self):
        provider = FixtureProvider()
        with self.assertRaises(OntologyDiscoveryError):
            OntologyDiscoveryPipeline(provider).discover(domain="x", sources=[fixture_source()], context="token=sk-abcdefghijklmnopqrstuvwxyz0123456789")
        self.assertEqual(provider.calls, [])

    def test_context_counts_toward_total_input_limit(self):
        provider = FixtureProvider()
        with self.assertRaises(OntologyDiscoveryError):
            OntologyDiscoveryPipeline(provider, max_total_chars=20).discover(domain="x", sources=[fixture_source("short")], context="context too long")
        self.assertEqual(provider.calls, [])

    def test_source_size_limit_applies(self):
        provider = FixtureProvider()
        with self.assertRaises(OntologyDiscoveryError):
            OntologyDiscoveryPipeline(provider, max_total_chars=10).discover(domain="x", sources=[fixture_source()])
        self.assertEqual(provider.calls, [])

    def test_candidate_output_does_not_overwrite_without_explicit_flag(self):
        candidate = discover()
        with tempfile.TemporaryDirectory() as temp:
            path = save_candidate(candidate, temp)
            self.assertTrue(path.is_file())
            with self.assertRaises(OntologyDiscoveryError):
                save_candidate(candidate, temp)

    def test_candidate_digest_is_stable_across_approval_status_change(self):
        candidate = discover()
        original = candidate_digest(candidate)
        approved = approve_candidate(candidate, reviewer_id="domain-owner", approval_ref="approval-1", expected_digest=original)
        self.assertEqual(candidate_digest(approved), original)


class NvidiaAutoOntologyAdapterTests(unittest.TestCase):
    def test_reads_documented_terms_and_acronyms_with_service_token(self):
        captured = []
        def get_bytes(url, headers, timeout):
            captured.append((url, headers, timeout))
            if url.endswith("/api/terms"):
                return b'{"items":[{"id":"term-1","name":"Order","description":"A customer order"}]}'
            return b'[{"id":"abbr-1","name":"SLA","description":"Service level agreement"}]'
        adapter = NvidiaAutoOntologyAdapter(base_url="http://127.0.0.1:3000", api_key="opaque-token", get_bytes=get_bytes)
        sources = adapter.fetch_catalog_sources()
        self.assertEqual(len(sources), 2)
        self.assertIn("x-api-key", captured[0][1])
        self.assertEqual(captured[0][1]["x-api-key"], "opaque-token")
        self.assertTrue(sources[0].source_id.startswith("nvidia-auto-ontology:semantic-term:"))

    def test_rejects_non_https_non_loopback_url(self):
        with self.assertRaises(NvidiaAutoOntologyError):
            NvidiaAutoOntologyAdapter(base_url="http://example.com")


class CogneeOntologyAdapterTests(unittest.TestCase):
    def test_graph_schema_is_explicit_and_not_production_promotion(self):
        schema = build_cognee_graph_schema()
        self.assertEqual(schema["defaultDatasetPattern"], "ontology-candidate-review-{candidateId}")
        self.assertFalse(schema["productionDatasetAllowedForDraft"])

    def test_draft_is_limited_to_review_dataset(self):
        candidate = discover()
        self.assertIn('"terms"', candidate_to_graph_document(candidate))
        with self.assertRaises(CogneeOntologyError):
            asyncio.run(stage_candidate_in_cognee(cognee_client=SimpleNamespace(), candidate=candidate,
                graph_model=object(), dataset_name="main_dataset"))

    def test_cognee_staging_calls_only_review_dataset(self):
        candidate = discover()
        class FakeCognee:
            def __init__(self): self.calls=[]
            async def add(self, data, dataset_name): self.calls.append(("add", dataset_name, data))
            async def cognify(self, graph_model, dataset_name): self.calls.append(("cognify", dataset_name, graph_model))
        fake = FakeCognee()
        result = asyncio.run(stage_candidate_in_cognee(cognee_client=fake, candidate=candidate,
            graph_model={"nodeTypes": []}, dataset_name="ontology-candidate-review-demo"))
        self.assertEqual(result["stageStatus"], "staged")
        self.assertEqual([x[0] for x in fake.calls], ["add", "cognify"])
        self.assertTrue(all(x[1].startswith("ontology-candidate-review-") for x in fake.calls))


class OntologyDiscoveryWorkerTests(unittest.TestCase):
    def test_worker_runs_discovery_from_authorized_source_references(self):
        with tempfile.TemporaryDirectory() as temp:
            source = fixture_source()
            benchmark = json.loads((ROOT / "examples/ontology-discovery/benchmarks/software-factory-benchmark.json").read_text(encoding="utf-8"))
            handler = make_ontology_discovery_handler(FixtureProvider(), output_root=Path(temp) / "candidates",
                source_resolver=lambda ref: source, benchmark=benchmark)
            store = SQLiteTaskStore(Path(temp) / "tasks.sqlite")
            store.enqueue(task_type="ontology.discovery.run", payload={"domain":"software-factory",
                "sourceRefs":[{"sourceId":source.source_id,"sourceType":source.source_type,"locator":source.locator}]},
                idempotency_key="ontology-discovery-worker-001", required_evidence=["ontology-candidate-json", "ontology-evaluation-json"])
            result = TaskWorker(store, {"ontology.discovery.run":handler}, worker_id="ontology-discovery-worker").run_once()
            self.assertEqual(result["status"], "succeeded")
            task = result["task"]
            self.assertEqual(task["output"]["status"], "review_required")
            self.assertFalse(task["output"]["promotionAllowed"])
            self.assertFalse(task["output"]["productionOntologyMutation"])
            self.assertEqual({item["type"] for item in task["evidence"]}, {"ontology-candidate-json", "ontology-evaluation-json"})
            store.close()

    def test_worker_rejects_source_locator_mismatch(self):
        with tempfile.TemporaryDirectory() as temp:
            source = fixture_source()
            handler = make_ontology_discovery_handler(FixtureProvider(), output_root=Path(temp) / "candidates", source_resolver=lambda ref: source)
            with self.assertRaises(OntologyDiscoveryError):
                handler({"domain":"software-factory", "sourceRefs":[{"sourceId":source.source_id,"sourceType":source.source_type,"locator":"other.md"}]}, SimpleNamespace(task_id="task", check_deadline=lambda: None))

    def test_worker_rejects_raw_source_content_in_persistent_task_payload(self):
        with tempfile.TemporaryDirectory() as temp:
            source = fixture_source()
            handler = make_ontology_discovery_handler(FixtureProvider(), output_root=Path(temp) / "candidates",
                source_resolver=lambda ref: source)
            store = SQLiteTaskStore(Path(temp) / "tasks.sqlite")
            store.enqueue(task_type="ontology.discovery.run", payload={"domain":"software-factory",
                "sourceRefs":[{"sourceId":source.source_id,"sourceType":source.source_type,"locator":source.locator,"content":source.content}]},
                idempotency_key="ontology-discovery-worker-raw-payload")
            result = TaskWorker(store, {"ontology.discovery.run":handler}, worker_id="ontology-discovery-worker").run_once()
            self.assertIn(result["status"], {"failed", "dead_letter", "retry_wait"})
            self.assertIsNone(result["task"].get("output"))
            store.close()


if __name__ == "__main__":
    unittest.main()
