"""Validation for the machine-readable MVP scope manifest.

This module validates project planning metadata only. It does not prove that
any build, test, security scan, or deployment capability has been implemented.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DEFAULT_MANIFEST = Path("config/mvp-scope.json")


def load_manifest(path: Path) -> dict[str, Any]:
    """Load the MVP scope manifest from a JSON file."""
    with path.open("r", encoding="utf-8") as stream:
        data = json.load(stream)
    if not isinstance(data, dict):
        raise ValueError("manifest root must be a JSON object")
    return data


def validate_manifest(data: dict[str, Any], root: Path) -> list[str]:
    """Return a list of validation errors; an empty list means structural checks pass."""
    errors: list[str] = []

    for key in ("schema_version", "project", "mvp", "required_modules", "acceptance_criteria"):
        if key not in data:
            errors.append(f"missing required top-level field: {key}")

    project = data.get("project")
    if not isinstance(project, dict):
        errors.append("project must be an object")
    elif not project.get("name") or not project.get("stage"):
        errors.append("project.name and project.stage are required")

    mvp = data.get("mvp")
    if not isinstance(mvp, dict):
        errors.append("mvp must be an object")
        mvp = {}
    if not isinstance(mvp.get("goal"), str) or not mvp.get("goal", "").strip():
        errors.append("mvp.goal must be a non-empty string")

    included = mvp.get("included_capabilities", [])
    excluded = mvp.get("excluded_capabilities", [])
    if not isinstance(included, list) or not all(isinstance(item, str) for item in included):
        errors.append("mvp.included_capabilities must be a list of strings")
        included = []
    if not isinstance(excluded, list) or not all(isinstance(item, str) for item in excluded):
        errors.append("mvp.excluded_capabilities must be a list of strings")
        excluded = []
    if not included:
        errors.append("mvp.included_capabilities must not be empty")
    if not excluded:
        errors.append("mvp.excluded_capabilities must not be empty")
    overlap = sorted(set(included) & set(excluded))
    if overlap:
        errors.append("capabilities cannot be both included and excluded: " + ", ".join(overlap))

    modules = data.get("required_modules", [])
    if not isinstance(modules, list) or not all(isinstance(module, str) for module in modules):
        errors.append("required_modules must be a list of directory names")
        modules = []
    for module in modules:
        if not (root / module).is_dir():
            errors.append(f"required module directory does not exist: {module}/")

    criteria = data.get("acceptance_criteria", [])
    if not isinstance(criteria, list) or not criteria:
        errors.append("acceptance_criteria must be a non-empty list")
        criteria = []

    seen_ids: set[str] = set()
    evidence_cache: dict[str, str] = {}
    for index, criterion in enumerate(criteria, start=1):
        if not isinstance(criterion, dict):
            errors.append(f"acceptance_criteria[{index}] must be an object")
            continue
        criterion_id = criterion.get("id")
        description = criterion.get("description")
        evidence = criterion.get("evidence")
        if not isinstance(criterion_id, str) or not criterion_id.strip():
            errors.append(f"acceptance_criteria[{index}].id must be a non-empty string")
            continue
        if criterion_id in seen_ids:
            errors.append(f"duplicate acceptance criterion id: {criterion_id}")
        seen_ids.add(criterion_id)
        if not isinstance(description, str) or not description.strip():
            errors.append(f"{criterion_id}: description must be a non-empty string")
        if not isinstance(evidence, str) or not evidence.strip():
            errors.append(f"{criterion_id}: evidence must be a relative path")
            continue
        evidence_path = (root / evidence).resolve()
        root_resolved = root.resolve()
        try:
            evidence_path.relative_to(root_resolved)
        except ValueError:
            errors.append(f"{criterion_id}: evidence path must stay within the repository")
            continue
        if not evidence_path.is_file():
            errors.append(f"{criterion_id}: evidence document does not exist: {evidence}")
            continue
        if evidence not in evidence_cache:
            evidence_cache[evidence] = evidence_path.read_text(encoding="utf-8")
        if criterion_id not in evidence_cache[evidence]:
            errors.append(f"{criterion_id}: ID is not traceable in {evidence}")

    return errors


def validate_from_root(root: Path) -> list[str]:
    """Load and validate config/mvp-scope.json under the supplied root."""
    manifest_path = root / DEFAULT_MANIFEST
    if not manifest_path.is_file():
        return [f"manifest not found: {DEFAULT_MANIFEST.as_posix()}"]
    try:
        data = load_manifest(manifest_path)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        return [f"cannot load manifest: {exc}"]
    return validate_manifest(data, root)
