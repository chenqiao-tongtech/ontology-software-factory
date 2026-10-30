#!/usr/bin/env python3
"""Validate the architecture baseline and design-document consistency."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from ontology_software_factory.architecture_baseline import validate_from_root  # noqa: E402


def main() -> int:
    errors = validate_from_root(ROOT)
    if errors:
        print("Architecture baseline check: FAIL")
        for error in errors:
            print(f" - {error}")
        return 1
    print("Architecture baseline check: PASS")
    print(" - Subsystems, modules, principles and constraints have unique IDs")
    print(" - Dependency references are valid and acyclic")
    print(" - Roadmap P0..P9 has outputs and exit criteria")
    print(" - Core ontology classes match the implemented vocabulary")
    print(" - Required planning documents exist")
    print("NOTE: this validates design-baseline consistency, not production readiness.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
