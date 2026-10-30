#!/usr/bin/env python3
"""Validate the orchestrator role, Skill, typed output, and example plan."""
from __future__ import annotations
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from ontology_software_factory.factory_orchestration import validate_factory_plan


def main() -> int:
    try:
        plan = json.loads((ROOT / "contracts/examples/factory-orchestrator-plan.example.json").read_text(encoding="utf-8"))
        result = validate_factory_plan(ROOT, plan)
        ontology = json.loads((ROOT / "ontology/software-factory-ontology.json").read_text(encoding="utf-8"))
        if "AgentPlan" not in {item["name"] for item in ontology["operationalExtensions"]["classes"]}:
            raise ValueError("AgentPlan is missing from the formal ontology")
    except Exception as exc:
        print(f"Factory Orchestrator plan validation: FAIL ({type(exc).__name__}: {exc})", file=sys.stderr)
        return 1
    print("Factory Orchestrator plan validation: PASS")
    print(f"plan={result['planId']} phases={result['phaseCount']} assignments={result['assignmentCount']} ontology={result['ontologySnapshotId']}")
    print("Boundary: validates a proposal only; it does not create Workflow Tasks, grant permissions or execute Agent assignments.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
