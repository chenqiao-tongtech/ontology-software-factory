"""Asset catalogue validation for the ontology-driven software-factory MVP.

The module validates machine-readable catalog metadata. It deliberately does not
fetch remote artifacts, inspect real SBOMs, verify signatures, or authorize deploys.
Those checks must be connected to trusted external tools in later iterations.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CATALOG = ROOT / "catalog" / "examples" / "demo-catalog.json"
DEFAULT_SCHEMA = ROOT / "catalog" / "schemas" / "asset-catalog.schema.json"
_SEMVER = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-([0-9A-Za-z.-]+))?(?:\+[0-9A-Za-z.-]+)?$")


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _version_parts(value: str) -> tuple[tuple[int, int, int], tuple[str, ...] | None] | None:
    match = _SEMVER.fullmatch(value)
    if not match:
        return None
    core = (int(match.group(1)), int(match.group(2)), int(match.group(3)))
    prerelease = tuple(match.group(4).split(".")) if match.group(4) else None
    return core, prerelease


def _compare_semver(left: str, right: str) -> int:
    """Compare the SemVer subset used by version ranges; build metadata is ignored."""
    lp, rp = _version_parts(left), _version_parts(right)
    if lp is None or rp is None:
        raise ValueError("version must be valid SemVer")
    if lp[0] != rp[0]:
        return -1 if lp[0] < rp[0] else 1
    lpre, rpre = lp[1], rp[1]
    if lpre is None and rpre is not None:
        return 1
    if lpre is not None and rpre is None:
        return -1
    if lpre is None and rpre is None:
        return 0
    assert lpre is not None and rpre is not None
    for li, ri in zip(lpre, rpre):
        if li == ri:
            continue
        if li.isdigit() and ri.isdigit():
            return -1 if int(li) < int(ri) else 1
        if li.isdigit() != ri.isdigit():
            return -1 if li.isdigit() else 1
        return -1 if li < ri else 1
    if len(lpre) == len(rpre):
        return 0
    return -1 if len(lpre) < len(rpre) else 1


def version_satisfies(version: str, constraint: str) -> bool:
    """Support exact SemVer, ^, ~, and comma-separated < <= > >= == range terms."""
    constraint = constraint.strip()
    if not constraint:
        return False
    if constraint.startswith("^") or constraint.startswith("~"):
        operator, base = constraint[0], constraint[1:].strip()
        base_parts = _version_parts(base)
        if base_parts is None or base_parts[1] is not None:
            return False
        major, minor, patch = base_parts[0]
        if operator == "~":
            upper = f"{major}.{minor + 1}.0"
        elif major > 0:
            upper = f"{major + 1}.0.0"
        elif minor > 0:
            upper = f"0.{minor + 1}.0"
        else:
            upper = f"0.0.{patch + 1}"
        return _compare_semver(version, base) >= 0 and _compare_semver(version, upper) < 0
    terms = [part.strip() for part in constraint.split(",") if part.strip()]
    if len(terms) == 1 and not re.match(r"^(?:==|>=|<=|>|<)", terms[0]):
        return _compare_semver(version, terms[0]) == 0
    for term in terms:
        match = re.fullmatch(r"(==|>=|<=|>|<)\s*(\S+)", term)
        if not match:
            return False
        comparison = _compare_semver(version, match.group(2))
        op = match.group(1)
        if op == "==" and comparison != 0:
            return False
        if op == ">=" and comparison < 0:
            return False
        if op == "<=" and comparison > 0:
            return False
        if op == ">" and comparison <= 0:
            return False
        if op == "<" and comparison >= 0:
            return False
    return bool(terms)


def _schema_errors(document: Any, schema_path: Path) -> list[str]:
    schema = load_json(schema_path)
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    messages = []
    for error in validator.iter_errors(document):
        path = ".".join(str(part) for part in error.absolute_path) or "$"
        messages.append(f"schema {path}: {error.message}")
    return sorted(messages)


def _all_ids(catalog: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], dict[str, str], dict[str, dict[str, Any]]]:
    by_id: dict[str, dict[str, Any]] = {}
    id_types: dict[str, str] = {}
    versions: dict[str, dict[str, Any]] = {}

    def add(item: dict[str, Any], type_name: str) -> None:
        item_id = item.get("id")
        if isinstance(item_id, str):
            if item_id in by_id:
                # Duplicate detection is reported in validate_catalog; retain first record for safe lookup.
                return
            by_id[item_id] = item
            id_types[item_id] = type_name

    for type_name, key in (("Product", "products"), ("Component", "components"), ("Artifact", "artifacts"),
                           ("CompatibilityRule", "compatibilityRules"), ("CustomerConfiguration", "customerConfigurations"),
                           ("CustomPatch", "customPatches")):
        for item in catalog.get(key, []):
            if isinstance(item, dict):
                add(item, type_name)
    for component in catalog.get("components", []):
        if not isinstance(component, dict):
            continue
        for version in component.get("versions", []):
            if isinstance(version, dict) and isinstance(version.get("id"), str):
                versions[version["id"]] = {**version, "_componentId": component.get("id"), "_component": component}
                if version["id"] in by_id:
                    # Keep the first object for collision reporting; IDs are invalid if duplicated.
                    pass
                else:
                    by_id[version["id"]] = versions[version["id"]]
                    id_types[version["id"]] = "Version"
    return by_id, id_types, versions


def validate_catalog(catalog: Any, schema_path: Path = DEFAULT_SCHEMA) -> list[str]:
    """Return structural and semantic catalogue errors. Empty means metadata is consistent."""
    errors = _schema_errors(catalog, schema_path)
    if not isinstance(catalog, dict):
        return errors or ["catalog root must be an object"]

    # A structurally malformed document may still provide enough data to report semantic issues,
    # but semantic checks are defensive and ignore objects of unexpected types.
    collections = ("products", "components", "artifacts", "compatibilityRules", "customerConfigurations", "customPatches")
    seen: set[str] = set()
    for key in collections:
        for item in catalog.get(key, []) if isinstance(catalog.get(key, []), list) else []:
            if isinstance(item, dict) and isinstance(item.get("id"), str):
                if item["id"] in seen:
                    errors.append(f"duplicate catalogue ID: {item['id']}")
                seen.add(item["id"])
            if key == "components" and isinstance(item, dict):
                for version in item.get("versions", []) if isinstance(item.get("versions", []), list) else []:
                    if isinstance(version, dict) and isinstance(version.get("id"), str):
                        if version["id"] in seen:
                            errors.append(f"duplicate catalogue ID: {version['id']}")
                        seen.add(version["id"])

    by_id, id_types, versions = _all_ids(catalog)
    products = {x.get("id"): x for x in catalog.get("products", []) if isinstance(x, dict) and isinstance(x.get("id"), str)}
    components = {x.get("id"): x for x in catalog.get("components", []) if isinstance(x, dict) and isinstance(x.get("id"), str)}
    artifacts = {x.get("id"): x for x in catalog.get("artifacts", []) if isinstance(x, dict) and isinstance(x.get("id"), str)}
    compatibility_rules = catalog.get("compatibilityRules", []) if isinstance(catalog.get("compatibilityRules", []), list) else []
    configs = catalog.get("customerConfigurations", []) if isinstance(catalog.get("customerConfigurations", []), list) else []
    patches = catalog.get("customPatches", []) if isinstance(catalog.get("customPatches", []), list) else []

    def ref(source_id: str, field: str, target_id: Any, expected: str, allow_missing: bool = False) -> dict[str, Any] | None:
        if target_id is None and allow_missing:
            return None
        if not isinstance(target_id, str):
            errors.append(f"{source_id}.{field}: expected ID string")
            return None
        target = by_id.get(target_id)
        if target is None:
            errors.append(f"{source_id}.{field}: referenced ID does not exist: {target_id}")
            return None
        actual = id_types.get(target_id)
        if actual != expected:
            errors.append(f"{source_id}.{field}: expected {expected}, got {actual}: {target_id}")
            return None
        return target

    graph: dict[str, list[str]] = {version_id: [] for version_id in versions}
    for product in products.values():
        for component_id in product.get("componentIds", []):
            ref(product["id"], "componentIds", component_id, "Component")

    for component in components.values():
        component_id = component["id"]
        version_ids = [v.get("id") for v in component.get("versions", []) if isinstance(v, dict)]
        if component.get("defaultVersionId") and component.get("defaultVersionId") not in version_ids:
            errors.append(f"{component_id}.defaultVersionId must point to a version of the same component")
        for version in component.get("versions", []):
            if not isinstance(version, dict) or not isinstance(version.get("id"), str):
                continue
            version_id = version["id"]
            if version.get("lifecycleStatus") == "active" and component.get("lifecycleStatus") == "active":
                license_meta = component.get("license", {})
                if license_meta.get("reviewStatus") != "approved":
                    errors.append(f"{component_id}: active component requires approved license review before catalogue activation")
            for artifact_id in version.get("artifactIds", []):
                ref(version_id, "artifactIds", artifact_id, "Artifact")
            for field, expected_kind in (("sbomArtifactId", "sbom"), ("provenanceArtifactId", "provenance")):
                if field in version:
                    artifact = ref(version_id, field, version[field], "Artifact")
                    if artifact and artifact.get("kind") != expected_kind:
                        errors.append(f"{version_id}.{field}: referenced Artifact kind must be {expected_kind}")
            for dep in version.get("dependencies", []):
                if not isinstance(dep, dict):
                    continue
                dep_component_id = dep.get("componentId")
                ref(version_id, "dependencies.componentId", dep_component_id, "Component")
                dep_version_id = dep.get("resolvedVersionId")
                target_version = ref(version_id, "dependencies.resolvedVersionId", dep_version_id, "Version")
                if target_version:
                    target_component_id = target_version.get("_componentId")
                    if target_component_id != dep_component_id:
                        errors.append(f"{version_id}: dependency resolvedVersionId does not belong to componentId {dep_component_id}")
                    graph.setdefault(version_id, []).append(dep_version_id)
                    target_version_str = target_version.get("version")
                    constraint = dep.get("versionConstraint", "")
                    try:
                        if not version_satisfies(target_version_str, constraint):
                            errors.append(f"{version_id}: resolved dependency {dep_version_id} ({target_version_str}) does not satisfy '{constraint}'")
                    except ValueError:
                        errors.append(f"{version_id}: invalid SemVer used by dependency constraint '{constraint}'")
                for evidence_id in dep.get("evidenceArtifactIds", []):
                    ref(version_id, "dependencies.evidenceArtifactIds", evidence_id, "Artifact")

    # The resolved version graph must be acyclic to avoid impossible dependency locks.
    visiting: set[str] = set()
    visited: set[str] = set()
    cycle_reports: set[str] = set()

    def visit(node: str, path: list[str]) -> None:
        if node in visiting:
            cycle = path[path.index(node):] + [node] if node in path else path + [node]
            cycle_key = " -> ".join(cycle)
            if cycle_key not in cycle_reports:
                cycle_reports.add(cycle_key)
                errors.append(f"dependency cycle detected: {cycle_key}")
            return
        if node in visited:
            return
        visiting.add(node)
        path.append(node)
        for child in graph.get(node, []):
            if child in graph:
                visit(child, path)
        path.pop()
        visiting.remove(node)
        visited.add(node)

    for version_id in graph:
        visit(version_id, [])

    for rule in compatibility_rules:
        if not isinstance(rule, dict):
            continue
        source_id, target_id = rule.get("id", "<compatibility>"), None
        source_version = ref(source_id, "sourceVersionId", rule.get("sourceVersionId"), "Version")
        target_version = ref(source_id, "targetVersionId", rule.get("targetVersionId"), "Version")
        if rule.get("status") in ("compatible", "incompatible") and not rule.get("evidenceArtifactIds"):
            errors.append(f"{source_id}: compatibility status {rule.get('status')} requires test evidence")
        for evidence_id in rule.get("evidenceArtifactIds", []):
            evidence = ref(source_id, "evidenceArtifactIds", evidence_id, "Artifact")
            if evidence and rule.get("status") in ("compatible", "incompatible") and evidence.get("verificationStatus") != "verified":
                errors.append(f"{source_id}: compatibility evidence must be verified for status {rule.get('status')}")
        if source_version and target_version and source_version.get("id") == target_version.get("id"):
            errors.append(f"{source_id}: compatibility rule cannot compare a version with itself")

    for config in configs:
        if not isinstance(config, dict):
            continue
        config_id, tenant_id = config.get("id", "<config>"), config.get("tenantId")
        product = ref(config_id, "productId", config.get("productId"), "Product")
        product_component_ids = set(product.get("componentIds", [])) if product else set()
        for version_id in config.get("baseVersionIds", []):
            version = ref(config_id, "baseVersionIds", version_id, "Version")
            if version and version.get("_componentId") not in product_component_ids:
                errors.append(f"{config_id}: baseline version {version_id} belongs to a component outside the selected product")
        if config.get("status") == "approved" and (not config.get("approvedBy") or not config.get("approvedAt")):
            errors.append(f"{config_id}: approved customer configuration requires approvedBy and approvedAt")
        override_keys: set[str] = set()
        for override in config.get("overrides", []):
            if not isinstance(override, dict):
                continue
            key = override.get("key", "")
            if key in override_keys:
                errors.append(f"{config_id}: duplicate configuration override key: {key}")
            override_keys.add(key)
            if re.search(r"password|passwd|secret|token|api[_-]?key|private[_-]?key|credential", str(key), re.IGNORECASE):
                errors.append(f"{config_id}: secret-like value must not be stored in overrides: {key}; use secretRefs")
        for patch_id in config.get("customPatchIds", []):
            patch = ref(config_id, "customPatchIds", patch_id, "CustomPatch")
            if patch and patch.get("tenantId") != tenant_id:
                errors.append(f"{config_id}: custom patch {patch_id} belongs to a different tenant")

    for patch in patches:
        if not isinstance(patch, dict):
            continue
        patch_id = patch.get("id", "<patch>")
        component = ref(patch_id, "componentId", patch.get("componentId"), "Component")
        base_version = ref(patch_id, "baseVersionId", patch.get("baseVersionId"), "Version")
        if component and base_version and base_version.get("_componentId") != component.get("id"):
            errors.append(f"{patch_id}: baseVersionId must belong to componentId")
        artifact = ref(patch_id, "artifactId", patch.get("artifactId"), "Artifact")
        if artifact and artifact.get("kind") != "patch-package":
            errors.append(f"{patch_id}.artifactId must reference an Artifact of kind patch-package")
        for evidence_id in patch.get("testEvidenceArtifactIds", []):
            ref(patch_id, "testEvidenceArtifactIds", evidence_id, "Artifact")
        if patch.get("status") == "approved":
            if patch.get("securityReviewStatus") not in ("pass", "waived"):
                errors.append(f"{patch_id}: approved patch requires security review pass or audited waiver")
            if not patch.get("testEvidenceArtifactIds"):
                errors.append(f"{patch_id}: approved patch requires test evidence")

    return sorted(set(errors))


def check_version_readiness(catalog: dict[str, Any], version_id: str) -> list[str]:
    """Return release-readiness blockers for a component version.

    This is a local metadata policy, not a complete release authorization system.
    It cannot prove that remote file digests or attestations are genuine.
    """
    _, _, versions = _all_ids(catalog)
    artifacts = {x.get("id"): x for x in catalog.get("artifacts", []) if isinstance(x, dict)}
    target = versions.get(version_id)
    if target is None:
        return [f"unknown version ID: {version_id}"]
    component = target.get("_component", {})
    blockers: list[str] = []
    if component.get("lifecycleStatus") != "active":
        blockers.append("component lifecycle is not active")
    if target.get("lifecycleStatus") != "active" or target.get("channel") != "stable":
        blockers.append("version must be active and on stable channel")
    license_meta = component.get("license", {})
    if license_meta.get("reviewStatus") != "approved":
        blockers.append("license review is not approved")
    if not target.get("sourceRevision"):
        blockers.append("source revision is missing")
    if not target.get("artifactIds"):
        blockers.append("version has no registered artifacts")
    for artifact_id in target.get("artifactIds", []):
        artifact = artifacts.get(artifact_id)
        if artifact is None:
            blockers.append(f"artifact is missing from catalogue: {artifact_id}")
        elif artifact.get("verificationStatus") != "verified":
            blockers.append(f"artifact is not verified: {artifact_id}")
    for field, expected_kind in (("sbomArtifactId", "sbom"), ("provenanceArtifactId", "provenance")):
        artifact_id = target.get(field)
        if not artifact_id:
            blockers.append(f"{field} is required by MVP release policy")
            continue
        artifact = artifacts.get(artifact_id)
        if artifact is None:
            blockers.append(f"{field} points to a missing artifact")
        else:
            if artifact.get("kind") != expected_kind:
                blockers.append(f"{field} must point to kind={expected_kind}")
            if artifact.get("verificationStatus") != "verified":
                blockers.append(f"{field} is not verified")
    return sorted(set(blockers))
