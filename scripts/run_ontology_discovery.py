#!/usr/bin/env python3
"""Create an ontology candidate from source documents, with an offline fixture mode."""
from __future__ import annotations
import argparse
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from ontology_software_factory.llm_provider import LLMRequest, LLMResponse, OpenAIResponsesProvider  # noqa: E402
from ontology_software_factory.ontology_discovery import (  # noqa: E402
    OntologyDiscoveryError, OntologyDiscoveryPipeline, SourceMaterial, evaluate_candidate, save_candidate,
)
from ontology_software_factory.observability import JsonlUsageLedger  # noqa: E402


class FixtureStructuredProvider:
    """Deterministic local fixture; never calls external services."""
    def __init__(self, path: Path):
        self.responses = json.loads(path.read_text(encoding="utf-8"))
        self.calls = []

    def generate_structured(self, request: LLMRequest, *, schema_name: str, schema: dict):
        stage = (request.metadata or {}).get("stage_id")
        if stage not in self.responses:
            raise ValueError(f"fixture has no response for stage {stage}")
        payload = self.responses[stage]
        self.calls.append({"stage": stage, "schemaName": schema_name})
        return payload, LLMResponse("fixture", "offline-fixture", f"fixture-{len(self.calls)}", "<structured fixture>", 0,
                                      {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}, 1)


def load_sources(paths: list[Path]) -> list[SourceMaterial]:
    sources = []
    for path in paths:
        resolved = path.resolve()
        if not resolved.is_file():
            raise OntologyDiscoveryError(f"source is not a file: {path}")
        content = resolved.read_text(encoding="utf-8")
        rel = path.name
        sources.append(SourceMaterial(
            source_id=f"source:{rel}", source_type=path.suffix.lower().lstrip(".") or "text",
            locator=rel, content=content,
        ))
    return sources


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", action="append", type=Path, default=[], help="Source document; repeat for multiple files")
    parser.add_argument("--domain", default="software-factory", help="Domain name")
    parser.add_argument("--context", default="", help="Short domain context; do not put secrets here")
    parser.add_argument("--output-root", type=Path, default=ROOT / ".local-runs/ontology-candidates")
    parser.add_argument("--benchmark", type=Path, default=ROOT / "examples/ontology-discovery/benchmarks/software-factory-benchmark.json")
    parser.add_argument("--demo", action="store_true", help="Use a deterministic local fixture instead of an external LLM")
    parser.add_argument("--overwrite", action="store_true", help="Explicitly overwrite same candidate file")
    parser.add_argument("--usage-ledger", type=Path, default=ROOT / ".local-runs/ontology-candidates/llm-usage.jsonl")
    args = parser.parse_args()
    try:
        if args.demo:
            source_path = ROOT / "examples/ontology-discovery/source-docs/software-factory-requirements.md"
            sources = [SourceMaterial("fixture:software-factory-requirements", "markdown", source_path.name,
                                      source_path.read_text(encoding="utf-8"))]
            provider = FixtureStructuredProvider(ROOT / "examples/ontology-discovery/demo-model-responses.json")
        else:
            if not args.source:
                parser.error("provide --source FILE (repeatable) or use --demo")
            sources = load_sources(args.source)
            if not os.getenv("OPENAI_API_KEY"):
                raise OntologyDiscoveryError("OPENAI_API_KEY is required for live discovery; use --demo for offline validation")
            usage_sink = JsonlUsageLedger(args.usage_ledger)
            default_provider = OpenAIResponsesProvider(usage_sink=usage_sink)
            provider = {"default": default_provider}
            for stage, env_name in {
                "term-discovery": "ONTOLOGY_TERM_MODEL",
                "relation-discovery": "ONTOLOGY_RELATION_MODEL",
                "constraint-and-competency-questions": "ONTOLOGY_CONSTRAINT_MODEL",
                "independent-critic": "ONTOLOGY_CRITIC_MODEL",
            }.items():
                model = os.getenv(env_name)
                if model:
                    provider[stage] = OpenAIResponsesProvider(model=model, usage_sink=usage_sink)
        pipeline = OntologyDiscoveryPipeline(provider)
        candidate = pipeline.discover(domain=args.domain, sources=sources, context=args.context)
        out = save_candidate(candidate, args.output_root, overwrite=args.overwrite)
        result = {"candidatePath": str(out), "candidateId": candidate["candidateId"],
                  "candidateDigest": candidate["candidateDigest"], "status": candidate["status"],
                  "terms": len(candidate["terms"]), "relations": len(candidate["relations"]),
                  "constraints": len(candidate["constraints"]), "criticFindings": len(candidate["criticFindings"]),
                  "validation": candidate["validation"], "calls": len(candidate["generationTrace"]),
                  "liveExternalCalls": not args.demo}
        if args.benchmark.is_file():
            benchmark = json.loads(args.benchmark.read_text(encoding="utf-8"))
            result["evaluation"] = evaluate_candidate(candidate, benchmark)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0 if candidate["validation"]["locallyValid"] else 2
    except Exception as exc:
        print(f"Ontology discovery failed closed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

if __name__ == "__main__":
    raise SystemExit(main())
