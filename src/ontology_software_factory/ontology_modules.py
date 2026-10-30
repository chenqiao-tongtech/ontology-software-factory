"""Validation for the logical module manifest over the canonical ontology source."""
from __future__ import annotations

from typing import Any


def validate_module_manifest(ontology: dict[str, Any], manifest: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if manifest.get("ontologyId") != ontology.get("ontologyId"):
        errors.append("module manifest ontologyId does not match canonical ontology")
    if manifest.get("ontologyVersion") != ontology.get("ontologyVersion"):
        errors.append("module manifest ontologyVersion does not match canonical ontology")
    if manifest.get("canonicalSource") != "ontology/software-factory-ontology.json":
        errors.append("module manifest must point to the canonical ontology source")
    if manifest.get("authority") != "canonical-source":
        errors.append("module manifest cannot claim authority over canonical ontology definitions")

    core_classes = ontology.get("classes", [])
    core_relations = ontology.get("relations", [])
    extensions = ontology.get("operationalExtensions", {})
    all_classes = {
        str(item.get("name")) for item in core_classes + extensions.get("classes", [])
        if isinstance(item, dict) and item.get("name")
    }
    all_relations = {
        str(item.get("name")) for item in core_relations + extensions.get("relations", [])
        if isinstance(item, dict) and item.get("name")
    }
    for relation in core_relations + extensions.get("relations", []):
        if not isinstance(relation, dict):
            errors.append("ontology relation definition must be an object")
            continue
        source = relation.get("source")
        targets = relation.get("target", [])
        targets = targets if isinstance(targets, list) else [targets]
        if source not in all_classes or not targets or any(target not in all_classes for target in targets):
            errors.append(f"ontology relation has unknown source or target: {relation.get('name', '<unnamed>')}")

    seen_modules: set[str] = set()
    seen_classes: list[str] = []
    seen_relations: list[str] = []
    for module in manifest.get("modules", []):
        if not isinstance(module, dict):
            errors.append("module entry must be an object")
            continue
        module_id = str(module.get("moduleId", ""))
        if not module_id or module_id in seen_modules:
            errors.append(f"missing or duplicate moduleId: {module_id or '<empty>'}")
        seen_modules.add(module_id)
        seen_classes.extend(str(x) for x in module.get("classes", []))
        seen_relations.extend(str(x) for x in module.get("relations", []))

    for kind, declared, actual in (
        ("class", seen_classes, all_classes),
        ("relation", seen_relations, all_relations),
    ):
        duplicates = sorted({item for item in declared if declared.count(item) > 1})
        missing = sorted(actual - set(declared))
        unknown = sorted(set(declared) - actual)
        if duplicates:
            errors.append(f"ontology {kind} assigned to multiple modules: {', '.join(duplicates)}")
        if missing:
            errors.append(f"ontology {kind} missing from module manifest: {', '.join(missing)}")
        if unknown:
            errors.append(f"unknown ontology {kind} in module manifest: {', '.join(unknown)}")
    return errors
