#!/usr/bin/env python3
"""Validate multi-agent topology and AgentHandoff example."""
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from ontology_software_factory.multi_agent_architecture import validate_from_root

def main() -> int:
    errors = validate_from_root(ROOT)
    if errors:
        print("Multi-agent architecture check: FAIL")
        for error in errors:
            print(f" - {error}")
        return 1
    print("Multi-agent architecture check: PASS")
    print(" - team roles resolve to registered role files")
    print(" - deterministic controller, independent verification join and bounded loops are present")
    print(" - AgentHandoff example satisfies required contract fields")
    print("NOTE: local topology validation does not prove external IAM/Agent SDK production integration.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
