#!/usr/bin/env python3
"""Validate all declared repository consumers of the formal ontology."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from ontology_software_factory.ontology_governance import build_consumer_graph


def main() -> int:
    ontology_path = ROOT / "ontology" / "software-factory-ontology.json"
    ontology = json.loads(ontology_path.read_text(encoding="utf-8"))
    graph = build_consumer_graph(ROOT, ontology)
    summary = graph["summary"]
    print("Ontology consumer reference validation")
    print(" | ".join(f"{key}={value}" for key, value in summary.items()))
    if graph["issues"]:
        for issue in graph["issues"]:
            print("ERROR " + json.dumps(issue, ensure_ascii=False, sort_keys=True))
        return 1
    print("PASS: all declared role, Skill, workflow, tool and contract references resolve")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
