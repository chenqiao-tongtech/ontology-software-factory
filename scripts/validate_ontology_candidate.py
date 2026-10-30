#!/usr/bin/env python3
"""Validate candidate ontology JSON contract and local semantic/provenance rules."""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from ontology_software_factory.ontology_discovery import validate_ontology_candidate  # noqa: E402

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidate", type=Path)
    args = parser.parse_args()
    candidate = json.loads(args.candidate.read_text(encoding="utf-8"))
    from jsonschema import validate
    schema = json.loads((ROOT / "ontology/schemas/ontology-candidate.schema.json").read_text(encoding="utf-8"))
    validate(candidate, schema)
    report = validate_ontology_candidate(candidate)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report["locallyValid"] else 2
if __name__ == "__main__":
    raise SystemExit(main())
