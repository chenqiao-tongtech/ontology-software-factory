#!/usr/bin/env python3
"""Run ontology discovery as a persistent Worker task using safe source references.

This offline demo uses a fixture LLM provider. Replace it with configured provider adapters
for live model calls; keep source_resolver responsible for authorization and source retrieval.
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ontology_software_factory.llm_provider import LLMRequest, LLMResponse  # noqa: E402
from ontology_software_factory.ontology_discovery import SourceMaterial  # noqa: E402
from ontology_software_factory.ontology_discovery_worker import make_ontology_discovery_handler  # noqa: E402
from ontology_software_factory.task_runtime import SQLiteTaskStore, TaskWorker  # noqa: E402


class FixtureStructuredProvider:
    def __init__(self) -> None:
        self.responses = json.loads((ROOT / "examples/ontology-discovery/demo-model-responses.json").read_text(encoding="utf-8"))
        self.calls = 0
    def generate_structured(self, request: LLMRequest, *, schema_name: str, schema: dict):
        stage = (request.metadata or {}).get("stage_id")
        self.calls += 1
        return self.responses[stage], LLMResponse("fixture", "offline-fixture", f"fixture-{self.calls}", "<fixture>", 1,
            {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}, 1)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", default="demo-ontology-worker-001")
    parser.add_argument("--runs-root", type=Path, default=ROOT / ".local-runs/ontology-worker-demo")
    args = parser.parse_args()
    source_path = ROOT / "examples/ontology-discovery/source-docs/software-factory-requirements.md"
    source_id = "fixture:software-factory-requirements"
    source = SourceMaterial(source_id, "markdown", source_path.name, source_path.read_text(encoding="utf-8"))
    trusted_sources = {source_id: source}

    def source_resolver(ref: dict):
        resolved = trusted_sources.get(str(ref.get("sourceId", "")))
        if not resolved or ref.get("locator") != resolved.locator:
            raise ValueError("source reference is not in the approved demo source registry")
        return resolved

    runs_root = args.runs_root.resolve()
    runs_root.mkdir(parents=True, exist_ok=True)
    store = SQLiteTaskStore(runs_root / "worker-tasks.sqlite")
    try:
        provider = FixtureStructuredProvider()
        handler = make_ontology_discovery_handler(provider, output_root=runs_root / "candidates",
            source_resolver=source_resolver,
            benchmark=json.loads((ROOT / "examples/ontology-discovery/benchmarks/software-factory-benchmark.json").read_text(encoding="utf-8")))
        task, duplicate = store.enqueue(task_type="ontology.discovery.run",
            payload={"domain": "software-factory", "context": "offline demo only", "sourceRefs": [
                {"sourceId": source_id, "sourceType": "markdown", "locator": source_path.name, "version": "fixture-v1"}
            ]}, idempotency_key=f"ontology-discovery:{args.run_id}", max_attempts=1, timeout_seconds=180,
            required_evidence=["ontology-candidate-json", "ontology-evaluation-json"])
        if duplicate and task.get("status") == "succeeded":
            print(json.dumps({"status": task["status"], "taskId": task["id"], "output": task["output"], "reusedIdempotentTask": True}, ensure_ascii=False, indent=2))
            return 0
        result = TaskWorker(store, {"ontology.discovery.run": handler}, worker_id="ontology-discovery-demo-worker", lease_seconds=30).run_once()
        print(json.dumps({"status": result.get("status"), "taskId": result.get("task", {}).get("id", task["id"]),
            "output": result.get("task", {}).get("output"), "evidence": result.get("task", {}).get("evidence"),
            "liveExternalCalls": False, "modelProviderCalls": provider.calls}, ensure_ascii=False, indent=2))
        return 0 if result.get("status") == "succeeded" else 2
    finally:
        store.close()

if __name__ == "__main__":
    raise SystemExit(main())
