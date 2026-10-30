#!/usr/bin/env python3
"""Validate the project scope manifest and its documentation traceability."""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ontology_software_factory.scope import validate_from_root  # noqa: E402


def main() -> int:
    errors = validate_from_root(ROOT)
    if errors:
        print("MVP scope check: FAIL")
        for error in errors:
            print(f" - {error}")
        return 1
    print("MVP scope check: PASS")
    print(" - Manifest structure is valid")
    print(" - Required module directories exist")
    print(" - Acceptance criteria IDs are traceable to the checklist")
    print("NOTE: this is a scope/documentation check, not proof of a working software factory.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
