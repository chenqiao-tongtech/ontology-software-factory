#!/usr/bin/env python3
"""Validate example entities against the JSON Schema and graph-level rules."""
from __future__ import annotations
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from ontology_software_factory.contracts import load_entity_schema, validate_entity  # noqa: E402
from ontology_software_factory.semantics import validate_entity_graph  # noqa: E402


def main() -> int:
    sample_path = ROOT / "contracts" / "examples" / "sample-entities.json"
    try:
        entities = json.loads(sample_path.read_text(encoding="utf-8"))
        if not isinstance(entities, list):
            raise ValueError("sample file root must be an array")
        ontology_path = ROOT / "ontology" / "software-factory-ontology.json"
        ontology = json.loads(ontology_path.read_text(encoding="utf-8"))
        if not isinstance(ontology, dict):
            raise ValueError("ontology root must be an object")
        class_names = [item.get("name") for item in ontology.get("classes", []) if isinstance(item, dict)]
        if not class_names or len(class_names) != len(set(class_names)):
            raise ValueError("ontology classes must be non-empty and have unique names")
        known_classes = set(class_names)
        for index, relation in enumerate(ontology.get("relations", [])):
            if not isinstance(relation, dict) or relation.get("source") not in known_classes:
                raise ValueError(f"ontology relation[{index}] has an unknown source class")
            targets = relation.get("target")
            if isinstance(targets, str):
                targets = [targets]
            if not isinstance(targets, list) or not targets or any(target not in known_classes for target in targets):
                raise ValueError(f"ontology relation[{index}] has an unknown target class")
        schema = load_entity_schema()
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"ERROR: cannot load input/schema: {exc}", file=sys.stderr)
        return 2

    errors: list[str] = []
    for index, entity in enumerate(entities):
        entity_id = entity.get("id", f"index:{index}") if isinstance(entity, dict) else f"index:{index}"
        for message in validate_entity(entity, schema):
            errors.append(f"[schema] {entity_id}: {message}")
    for message in validate_entity_graph(entities):
        errors.append(f"[semantic] {message}")

    if errors:
        print(f"Domain validation failed with {len(errors)} error(s):")
        for error in errors:
            print(f" - {error}")
        return 1
    print(f"Domain validation passed: {len(entities)} entities; ontology catalogue, JSON Schema and graph semantics are valid.")
    print("Note: passing validates the example contract data, not a real build, scan, release, or deployment.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
