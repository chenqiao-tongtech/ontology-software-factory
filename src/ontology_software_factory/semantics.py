"""Cross-entity relationship and business-invariant validation."""
from __future__ import annotations
from collections import Counter
from typing import Any

# (source entity type, field) -> expected target entity type; array-valued fields are indicated below.
SINGLE_REFS = {
    ("Requirement", "targetProductId"): "Product",
    ("Component", "currentVersionId"): "Version",
    ("Version", "componentId"): "Component",
    ("Build", "componentId"): "Component",
    ("Build", "versionId"): "Version",
    ("TestRun", "buildId"): "Build",
    ("TestRun", "reportArtifactId"): "Artifact",
    ("Vulnerability", "componentId"): "Component",
    ("Deployment", "releaseId"): "Release",
    ("Incident", "deploymentId"): "Deployment",
    ("Artifact", "createdByBuildId"): "Build",
    ("Release", "productId"): "Product",
}
ARRAY_REFS = {
    ("Product", "componentIds"): "Component",
    ("Build", "artifactIds"): "Artifact",
    ("Vulnerability", "affectedVersionIds"): "Version",
    ("Release", "versionIds"): "Version",
    ("Release", "artifactIds"): "Artifact",
    ("Release", "buildIds"): "Build",
    ("Release", "testRunIds"): "TestRun",
    ("Release", "evidenceArtifactIds"): "Artifact",
    ("Incident", "affectedComponentIds"): "Component",
    ("Incident", "evidenceArtifactIds"): "Artifact",
}


def validate_entity_graph(entities: list[dict[str, Any]]) -> list[str]:
    """Validate unique IDs, typed references, and a small set of MVP invariants."""
    errors: list[str] = []
    counts = Counter(e.get("id") for e in entities if isinstance(e, dict) and isinstance(e.get("id"), str))
    duplicates = sorted(entity_id for entity_id, count in counts.items() if count > 1)
    for entity_id in duplicates:
        errors.append(f"duplicate entity id: {entity_id}")

    by_id: dict[str, dict[str, Any]] = {}
    for entity in entities:
        if not isinstance(entity, dict):
            errors.append("entity graph items must be objects")
            continue
        entity_id = entity.get("id")
        if isinstance(entity_id, str) and entity_id not in by_id:
            by_id[entity_id] = entity

    def check_ref(source: dict[str, Any], field: str, target_id: Any, target_type: str) -> None:
        src_id = source.get("id", "<unknown>")
        if not isinstance(target_id, str):
            errors.append(f"{src_id}.{field}: reference must be an entity ID string")
            return
        target = by_id.get(target_id)
        if target is None:
            errors.append(f"{src_id}.{field}: referenced entity does not exist: {target_id}")
            return
        actual_type = target.get("entityType")
        if actual_type != target_type:
            errors.append(f"{src_id}.{field}: expected {target_type}, got {actual_type} ({target_id})")
        source_tenant = source.get("tenantId")
        target_tenant = target.get("tenantId")
        if source_tenant is not None and target_tenant is not None and source_tenant != target_tenant:
            errors.append(f"{src_id}.{field}: cross-tenant reference is not allowed ({source_tenant} -> {target_tenant})")

    for entity in entities:
        if not isinstance(entity, dict):
            continue
        entity_type = entity.get("entityType")
        for (source_type, field), target_type in SINGLE_REFS.items():
            if entity_type == source_type and field in entity:
                check_ref(entity, field, entity[field], target_type)
        for (source_type, field), target_type in ARRAY_REFS.items():
            if entity_type == source_type and field in entity:
                value = entity[field]
                if not isinstance(value, list):
                    errors.append(f"{entity.get('id', '<unknown>')}.{field}: expected an array of IDs")
                    continue
                for index, target_id in enumerate(value):
                    check_ref(entity, f"{field}[{index}]", target_id, target_type)

    for entity in entities:
        if not isinstance(entity, dict):
            continue
        eid, etype = entity.get("id", "<unknown>"), entity.get("entityType")
        if etype == "Component":
            current_version = by_id.get(entity.get("currentVersionId"))
            if current_version and current_version.get("entityType") == "Version" and current_version.get("componentId") != eid:
                errors.append(f"{eid}: currentVersionId points to a Version belonging to another component")
        elif etype == "Vulnerability":
            for version_id in entity.get("affectedVersionIds", []):
                version = by_id.get(version_id)
                if version and version.get("entityType") == "Version" and version.get("componentId") != entity.get("componentId"):
                    errors.append(f"{eid}: affected version {version_id} belongs to a different component")
        elif etype == "Build":
            version = by_id.get(entity.get("versionId"))
            if version and version.get("entityType") == "Version" and version.get("componentId") != entity.get("componentId"):
                errors.append(f"{eid}: versionId belongs to a different component than componentId")
            if entity.get("status") == "succeeded" and not entity.get("artifactIds"):
                errors.append(f"{eid}: succeeded Build must reference at least one artifact in this MVP")
        elif etype == "TestRun":
            total, passed, failed, skipped = (entity.get(k) for k in ("total", "passed", "failed", "skipped"))
            if all(isinstance(x, int) and not isinstance(x, bool) for x in (total, passed, failed, skipped)):
                if passed + failed + skipped != total:
                    errors.append(f"{eid}: passed + failed + skipped must equal total")
                if entity.get("status") == "passed" and failed != 0:
                    errors.append(f"{eid}: TestRun status passed requires failed = 0")
                if entity.get("status") == "failed" and failed < 1:
                    errors.append(f"{eid}: TestRun status failed requires failed >= 1")
        elif etype == "Release":
            product = by_id.get(entity.get("productId"))
            if product and product.get("entityType") == "Product":
                product_components = set(product.get("componentIds", []))
                for version_id in entity.get("versionIds", []):
                    version = by_id.get(version_id)
                    if version and version.get("entityType") == "Version" and version.get("componentId") not in product_components:
                        errors.append(f"{eid}: version {version_id} is not part of product {product.get('id')}")
            if entity.get("status") == "published" and entity.get("vulnerabilityReview") not in ("pass", "waived"):
                errors.append(f"{eid}: published Release requires vulnerabilityReview pass or an audited waiver")
            if entity.get("status") in ("approved", "published") and not entity.get("approvedBy"):
                errors.append(f"{eid}: approved/published Release requires approvedBy")
            if entity.get("status") in ("approved", "published") and not entity.get("approvedAt"):
                errors.append(f"{eid}: approved/published Release requires approvedAt")
        elif etype == "Deployment":
            if entity.get("environment") == "prod" and entity.get("status") == "succeeded" and not entity.get("approvalRef"):
                errors.append(f"{eid}: successful production Deployment requires approvalRef")
    return errors
