"""Pinned ontology context and semantic Agent task-contract validation."""
from __future__ import annotations

import json
import re
from copy import deepcopy
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from .ontology_versioning import ontology_digest


class OntologyBindingError(ValueError):
    """The requested ontology version is missing, stale, or invalid."""


def _class_names(ontology: dict) -> set[str]:
    names = {
        str(item["name"])
        for item in ontology.get("classes", [])
        if isinstance(item, dict) and item.get("name")
    }
    extensions = ontology.get("operationalExtensions", {})
    if isinstance(extensions, dict):
        names.update(
            str(item["name"])
            for item in extensions.get("classes", [])
            if isinstance(item, dict) and item.get("name")
        )
    return names


def validate_ontology_binding(binding: dict[str, Any]) -> dict[str, Any]:
    """Verify a self-contained, immutable snapshot binding before every Agent call."""
    if not isinstance(binding, dict) or not isinstance(binding.get("ontology"), dict):
        raise OntologyBindingError("ontology binding must include the complete ontology snapshot")
    ontology = binding["ontology"]
    digest = ontology_digest(ontology)
    if binding.get("digest") != digest:
        raise OntologyBindingError("ontology snapshot digest mismatch; refusing to execute")
    expected = {
        "snapshotId": "ont-" + digest[:16],
        "ontologyId": ontology.get("ontologyId", "unknown"),
        "ontologyVersion": ontology.get("ontologyVersion", "unknown"),
        "schemaVersion": ontology.get("schemaVersion", "unknown"),
    }
    for key, value in expected.items():
        if binding.get(key) != value:
            raise OntologyBindingError(f"ontology binding metadata mismatch: {key}")
    if not _class_names(ontology):
        raise OntologyBindingError("ontology snapshot contains no class definitions")
    return {
        **{key: value for key, value in expected.items() if key != "snapshotId"},
        "snapshotId": expected["snapshotId"],
        "digest": digest,
        "ontology": deepcopy(ontology),
    }


def load_active_ontology_binding(project_root: str | Path, snapshot_id: str | None = None) -> dict[str, Any]:
    """Load the active or explicitly selected snapshot from the Portal local state file."""
    root = Path(project_root).resolve()
    state_path = root / ".local-portal" / "state.json"
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise OntologyBindingError(
            "ontology version catalog is unavailable; start the Portal and publish an ontology baseline first"
        ) from exc
    selected = str(snapshot_id or state.get("activeOntologySnapshotId") or "").strip()
    if not selected:
        raise OntologyBindingError(
            "no active ontology snapshot; create a snapshot and complete the independent promote approval in the Portal"
        )
    snapshots = state.get("ontologySnapshots", [])
    snapshot = next(
        (item for item in snapshots if isinstance(item, dict) and item.get("snapshotId") == selected),
        None,
    )
    if snapshot is None:
        raise OntologyBindingError(f"ontology snapshot not found in local catalog: {selected}")
    return validate_ontology_binding(snapshot)


def validate_role_ontology_contract(role: dict[str, Any], binding: dict[str, Any]) -> None:
    """Fail closed if a Role or Skill refers to a class absent from the pinned version."""
    verified = validate_ontology_binding(binding)
    classes = _class_names(verified["ontology"])
    for field in ("inputEntityTypes", "outputEntityTypes"):
        declared = role.get(field, [])
        if not isinstance(declared, list) or not declared:
            raise OntologyBindingError(f"role contract must declare a non-empty {field}")
        missing = sorted({str(value) for value in declared} - classes)
        if missing:
            raise OntologyBindingError(
                f"role {role.get('roleId', '<unknown>')} {field} are absent from ontology "
                f"{verified['ontologyVersion']}: {', '.join(missing)}"
            )


def _validate_schema(instance: dict, schema_path: Path, label: str) -> None:
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        errors = sorted(
            Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(instance),
            key=lambda error: list(error.absolute_path),
        )
    except (OSError, json.JSONDecodeError, Exception) as exc:
        raise OntologyBindingError(f"cannot validate {label} contract ({type(exc).__name__})") from exc
    if errors:
        first = errors[0]
        location = ".".join(str(part) for part in first.absolute_path) or "$"
        raise OntologyBindingError(f"{label} contract invalid at {location}: {first.message}")


def validate_typed_entity_references(
    value: Any, *, ontology_classes: set[str], allowed_types: set[str], label: str
) -> None:
    """Validate explicit entityType fields; ordinary prose is never interpreted as a type reference."""
    if isinstance(value, dict):
        for key in ("entityType", "entity_type"):
            entity_type = value.get(key)
            if entity_type is not None:
                if not isinstance(entity_type, str) or entity_type not in ontology_classes:
                    raise OntologyBindingError(f"{label} references an entity type absent from the pinned ontology")
                if entity_type not in allowed_types:
                    raise OntologyBindingError(f"{label} references an entity type not allowed by the Role contract")
        for child in value.values():
            validate_typed_entity_references(
                child, ontology_classes=ontology_classes, allowed_types=allowed_types, label=label
            )
    elif isinstance(value, list):
        for child in value:
            validate_typed_entity_references(
                child, ontology_classes=ontology_classes, allowed_types=allowed_types, label=label
            )


def build_agent_task_contract(
    project_root: str | Path,
    *,
    role: dict[str, Any],
    binding: dict[str, Any],
    run_id: str,
    step_id: str,
    attempt: int,
    objective: str,
    timeout_seconds: int = 900,
    max_attempts: int = 3,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """Create the formal task envelope used for a single pinned Agent execution."""
    verified = validate_ontology_binding(binding)
    validate_role_ontology_contract(role, verified)
    role_inputs = [str(value) for value in role["inputEntityTypes"]]
    entity_type = "Requirement" if "Requirement" in role_inputs else role_inputs[0]
    entity_slug = re.sub(r"(?<!^)(?=[A-Z])", "-", entity_type).lower()
    task_key = idempotency_key or f"ontology-task:{run_id}:{step_id}:{attempt}"
    contract = {
        "taskId": f"sf:task:{run_id}.{step_id}.{attempt}",
        "tenantId": "local-reference",
        "projectId": "ontology-software-factory",
        "roleId": role["roleId"],
        "ontologyVersion": verified["ontologyVersion"],
        "ontologySnapshotId": verified["snapshotId"],
        "ontologyDigest": verified["digest"],
        "ontologySchemaVersion": verified["schemaVersion"],
        "objective": str(objective).strip(),
        "inputs": [{
            "entityId": f"sf:{entity_slug}:{run_id}.{step_id}",
            "entityType": entity_type,
            "schemaVersion": verified["schemaVersion"],
            "evidenceRef": f"workflow-input:{run_id}",
        }],
        "expectedOutputEntityTypes": list(role["outputEntityTypes"]),
        "acceptanceCriteria": [{
            "id": "AC-ONTOLOGY-BOUND-OUTPUT",
            "description": "Output must match the Role's typed output contract and the pinned ontology version. "
                           + " ".join(str(item) for item in role.get("handoffRequirements", [])),
            "verificationMethod": "schema",
        }],
        "contextRefs": [],
        "sensitivity": "internal",
        "resourceLimits": {
            "maxAttempts": max(1, min(int(max_attempts), 5)),
            "timeoutSeconds": max(1, min(int(timeout_seconds), 7200)),
            "maxToolCalls": 50,
        },
        "idempotencyKey": task_key,
    }
    validate_typed_entity_references(
        contract["inputs"],
        ontology_classes=_class_names(verified["ontology"]),
        allowed_types=set(role["inputEntityTypes"]),
        label="Agent Task",
    )
    _validate_schema(contract, Path(project_root) / "contracts/schemas/agent-task.schema.json", "Agent Task")
    return contract


def validate_agent_task_contract(
    project_root: str | Path,
    contract: dict[str, Any],
    *,
    role: dict[str, Any],
    binding: dict[str, Any],
) -> None:
    verified = validate_ontology_binding(binding)
    validate_role_ontology_contract(role, verified)
    _validate_schema(contract, Path(project_root) / "contracts/schemas/agent-task.schema.json", "Agent Task")
    expected = {
        "roleId": role["roleId"],
        "ontologyVersion": verified["ontologyVersion"],
        "ontologySnapshotId": verified["snapshotId"],
        "ontologyDigest": verified["digest"],
        "ontologySchemaVersion": verified["schemaVersion"],
        "expectedOutputEntityTypes": list(role["outputEntityTypes"]),
    }
    for key, value in expected.items():
        if contract.get(key) != value:
            raise OntologyBindingError(f"Agent Task does not match pinned runtime context: {key}")
    validate_typed_entity_references(
        contract.get("inputs", []),
        ontology_classes=_class_names(verified["ontology"]),
        allowed_types=set(role["inputEntityTypes"]),
        label="Agent Task",
    )


def validate_agent_output(
    output: dict[str, Any], *, role: dict[str, Any], binding: dict[str, Any]
) -> None:
    verified = validate_ontology_binding(binding)
    validate_typed_entity_references(
        output,
        ontology_classes=_class_names(verified["ontology"]),
        allowed_types=set(role["outputEntityTypes"]),
        label="Agent output",
    )
