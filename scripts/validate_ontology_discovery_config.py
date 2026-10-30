#!/usr/bin/env python3
"""Validate ontology-discovery policy, schema, fixture, and benchmark contracts."""
from __future__ import annotations
import json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from ontology_software_factory.ontology_discovery import TERMS_SCHEMA, RELATIONS_SCHEMA, CONSTRAINTS_SCHEMA, CRITIC_SCHEMA  # noqa: E402

def main() -> int:
    try:
        from jsonschema import Draft202012Validator
        policy = json.loads((ROOT / "ontology/discovery-policy.json").read_text(encoding="utf-8"))
        candidate_schema = json.loads((ROOT / "ontology/schemas/ontology-candidate.schema.json").read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(candidate_schema)
        for schema in (TERMS_SCHEMA, RELATIONS_SCHEMA, CONSTRAINTS_SCHEMA, CRITIC_SCHEMA):
            Draft202012Validator.check_schema(schema)
        assert policy["candidateOnly"] is True
        assert policy["productionOntologyMutationByLLM"] is False
        assert policy["promotion"]["requiresIndependentHumanApproval"] is True
        fixture = json.loads((ROOT / "examples/ontology-discovery/demo-model-responses.json").read_text(encoding="utf-8"))
        required = {"term-discovery", "relation-discovery", "constraint-and-competency-questions", "independent-critic"}
        assert required == set(fixture)
        benchmark = json.loads((ROOT / "examples/ontology-discovery/benchmarks/software-factory-benchmark.json").read_text(encoding="utf-8"))
        assert len(benchmark["expectedTerms"]) >= 5 and len(benchmark["expectedRelations"]) >= 3
        assert (ROOT / "src/ontology_software_factory/ontology_discovery_worker.py").is_file()
        assert (ROOT / "scripts/run_ontology_discovery_worker_demo.py").is_file()
        assert (ROOT / "scripts/approve_ontology_candidate.py").is_file()
    except Exception as exc:
        print(f"Ontology discovery config validation: FAIL ({type(exc).__name__}: {exc})")
        return 1
    print("Ontology discovery config validation: PASS")
    print("Validated: candidate schema, 4 LLM pass schemas, source/provenance policy, offline fixture, benchmark, Worker adapter and digest-bound approval CLI.")
    print("NOTE: config validation does not call NVIDIA Auto Ontology, Cognee, or a live LLM endpoint.")
    return 0
if __name__ == "__main__":
    raise SystemExit(main())
