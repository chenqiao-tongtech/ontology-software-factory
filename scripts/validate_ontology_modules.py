#!/usr/bin/env python3
"""Validate the ontology module manifest against the canonical ontology."""
from __future__ import annotations
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from jsonschema import Draft202012Validator
from ontology_software_factory.ontology_modules import validate_module_manifest


def main() -> int:
    try:
        ontology = json.loads((ROOT / "ontology/software-factory-ontology.json").read_text(encoding="utf-8"))
        manifest = json.loads((ROOT / "ontology/module-manifest.json").read_text(encoding="utf-8"))
        schema = json.loads((ROOT / "ontology/schemas/module-manifest.schema.json").read_text(encoding="utf-8"))
        schema_errors = list(Draft202012Validator(schema).iter_errors(manifest))
        errors = [f"schema: {item.message}" for item in schema_errors]
        errors.extend(validate_module_manifest(ontology, manifest))
    except Exception as exc:
        print(f"Ontology module validation: FAIL ({type(exc).__name__}: {exc})", file=sys.stderr)
        return 1
    if errors:
        for item in errors:
            print("ERROR " + item, file=sys.stderr)
        return 1
    classes = sum(len(item["classes"]) for item in manifest["modules"])
    relations = sum(len(item["relations"]) for item in manifest["modules"])
    print(f"Ontology module validation: PASS; modules={len(manifest['modules'])}; classes={classes}; relations={relations}")
    print("Definitions remain authoritative in the canonical ontology JSON; the module manifest is a logical partition, not a second source of truth.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
