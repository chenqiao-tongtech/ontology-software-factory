#!/usr/bin/env python3
"""Validate asset catalogue structure and cross-reference semantics."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ontology_software_factory.catalog import (  # noqa: E402
    DEFAULT_CATALOG,
    check_version_readiness,
    load_json,
    validate_catalog,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG, help="catalog JSON file")
    parser.add_argument("--readiness-version", help="optional version ID to check against MVP release-readiness policy")
    args = parser.parse_args()
    try:
        document = load_json(args.catalog)
    except (OSError, ValueError) as exc:
        print(f"ERROR: cannot load catalog {args.catalog}: {exc}", file=sys.stderr)
        return 2

    errors = validate_catalog(document)
    if errors:
        print("Asset catalogue validation FAILED:")
        for error in errors:
            print(f"- {error}")
        return 1

    product_count = len(document.get("products", []))
    component_count = len(document.get("components", []))
    version_count = sum(len(c.get("versions", [])) for c in document.get("components", []))
    print("Asset catalogue structure and semantic references: PASS")
    print(f"Products: {product_count}; components: {component_count}; versions: {version_count}; artifacts: {len(document.get('artifacts', []))}")

    if args.readiness_version:
        blockers = check_version_readiness(document, args.readiness_version)
        if blockers:
            print(f"Readiness check for {args.readiness_version}: BLOCKED")
            for item in blockers:
                print(f"- {item}")
            return 3
        print(f"Readiness check for {args.readiness_version}: PASS")
    print("NOTE: metadata validation does not fetch files, verify digests, parse SBOMs, or authenticate attestations.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
