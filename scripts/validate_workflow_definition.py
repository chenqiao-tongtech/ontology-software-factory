#!/usr/bin/env python3
"""Validate the Article 19 workflow definition without third-party dependencies."""
from __future__ import annotations
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
DEFINITIONS = [
    ROOT / "workflows" / "definitions" / "software-delivery-v1.json",
    ROOT / "workflows" / "definitions" / "ontology-discovery-review-v1.json",
]
SCHEMA = ROOT / "workflows" / "schemas" / "workflow-definition.schema.json"


def validate(doc: dict) -> list[str]:
    errors: list[str] = []
    for field in ("id", "name", "version", "startStepId", "steps"):
        if field not in doc:
            errors.append(f"missing required field: {field}")
    steps = doc.get("steps", [])
    if not isinstance(steps, list) or not steps:
        return errors + ["steps must be a non-empty array"]
    ids = [s.get("id") for s in steps if isinstance(s, dict)]
    if len(ids) != len(set(ids)):
        errors.append("step IDs must be unique")
    idset = set(ids)
    if doc.get("startStepId") not in idset:
        errors.append("startStepId does not refer to a declared step")
    indegree = {sid: 0 for sid in idset}
    children = {sid: [] for sid in idset}
    for step in steps:
        if not isinstance(step, dict):
            errors.append("each step must be an object")
            continue
        for key in ("id", "name", "roleId", "executionMode", "dependsOn", "timeoutSeconds", "maxAttempts", "retryableErrorClasses", "requiresEvidence", "requiresIdempotencyKey", "sideEffect", "requiresApproval"):
            if key not in step:
                errors.append(f"step {step.get('id', '<unknown>')} missing {key}")
        if step.get("executionMode") not in {"agent", "system", "human"}:
            errors.append(f"step {step.get('id')} has invalid executionMode")
        if not isinstance(step.get("maxAttempts"), int) or step.get("maxAttempts", 0) < 1:
            errors.append(f"step {step.get('id')} maxAttempts must be >= 1")
        for dep in step.get("dependsOn", []):
            if dep not in idset:
                errors.append(f"step {step.get('id')} depends on unknown step {dep}")
            elif dep == step.get("id"):
                errors.append(f"step {dep} cannot depend on itself")
            else:
                indegree[step["id"]] += 1
                children[dep].append(step["id"])
        if step.get("sideEffect") == "external" and not step.get("requiresIdempotencyKey"):
            errors.append(f"external side-effect step {step.get('id')} must require an idempotency key")
        if step.get("sideEffect") == "external" and not step.get("compensation"):
            errors.append(f"external side-effect step {step.get('id')} must declare a compensation strategy")
    ready = [sid for sid, degree in indegree.items() if degree == 0]
    visited = 0
    while ready:
        sid = ready.pop()
        visited += 1
        for child in children[sid]:
            indegree[child] -= 1
            if indegree[child] == 0:
                ready.append(child)
    if visited != len(idset):
        errors.append("workflow dependencies contain a cycle")
    return errors


def main() -> int:
    try:
        docs = [(path, json.loads(path.read_text(encoding="utf-8"))) for path in DEFINITIONS]
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"Could not load workflow files: {exc}", file=sys.stderr)
        return 2
    all_errors = []
    for path, doc in docs:
        all_errors.extend(f"{path.name}: {error}" for error in validate(doc))
    # Defensive spot-check that schemas keep a JSON Schema contract marker.
    if schema.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
        all_errors.append("workflow definition schema must declare JSON Schema 2020-12")
    if all_errors:
        print("Workflow definition validation: FAIL")
        for error in all_errors:
            print(f" - {error}")
        return 1
    print("Workflow definition validation: PASS")
    for path, doc in docs:
        print(f"Workflow: {doc['id']}@{doc['version']}; steps: {len(doc['steps'])}; DAG: acyclic ({path.name})")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
