"""Fail-closed validation of Factory Orchestrator plans before Workflow Engine intake."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator


class FactoryPlanError(ValueError):
    """A proposed factory plan violates its contract or registered execution boundary."""


def validate_factory_plan(
    project_root: str | Path,
    plan: dict[str, Any],
    *,
    ontology_binding: dict[str, Any] | None = None,
) -> dict[str, Any]:
    root = Path(project_root).resolve()
    schema = json.loads((root / "contracts/schemas/factory-orchestrator-plan.schema.json").read_text(encoding="utf-8"))
    errors = sorted(Draft202012Validator(schema).iter_errors(plan), key=lambda item: list(item.absolute_path))
    if errors:
        raise FactoryPlanError("plan schema violation: " + "; ".join(item.message for item in errors[:5]))

    digest = str(plan["ontologyBinding"]["digest"])
    if plan["ontologyBinding"]["snapshotId"] != "ont-" + digest[:16]:
        raise FactoryPlanError("plan ontology snapshot ID does not match its digest")
    if ontology_binding is not None:
        for key in ("snapshotId", "digest", "ontologyId", "ontologyVersion", "schemaVersion"):
            if plan["ontologyBinding"].get(key) != ontology_binding.get(key):
                raise FactoryPlanError(f"plan is not pinned to the active ontology binding: {key}")

    try:
        team = json.loads((root / "agents/teams/software-factory-mvp.json").read_text(encoding="utf-8"))
        registered = {item["roleId"] for item in team.get("registeredRoles", [])}
        roles = {
            json.loads(path.read_text(encoding="utf-8"))["roleId"]: json.loads(path.read_text(encoding="utf-8"))
            for path in (root / "agents/roles").glob("*.json")
        }
    except (OSError, KeyError, json.JSONDecodeError) as exc:
        raise FactoryPlanError("cannot load registered role topology") from exc

    limits = plan["limits"]
    topology_limits = team.get("limits", {})
    if limits["maxAgentAssignments"] > topology_limits.get("maxAgentHops", 0):
        raise FactoryPlanError("plan assignment count exceeds the team maxAgentHops limit")
    if limits["maxParallelAssignments"] > topology_limits.get("maxParallelAgents", 0):
        raise FactoryPlanError("plan parallelism exceeds the team maxParallelAgents limit")
    if limits["maxRevisionLoops"] > topology_limits.get("maxRevisionLoops", 0):
        raise FactoryPlanError("plan revision loops exceed the team limit")

    ontology = json.loads((root / "ontology/software-factory-ontology.json").read_text(encoding="utf-8"))
    known_classes = {item["name"] for item in ontology.get("classes", []) + ontology.get("operationalExtensions", {}).get("classes", [])}
    phase_ids = [phase["phaseId"] for phase in plan["phases"]]
    if len(phase_ids) != len(set(phase_ids)):
        raise FactoryPlanError("phase IDs must be unique")
    known_phases = set(phase_ids)
    phase_by_id = {phase["phaseId"]: phase for phase in plan["phases"]}
    for phase in plan["phases"]:
        missing = set(phase["dependsOn"]) - known_phases
        if missing:
            raise FactoryPlanError(f"phase {phase['phaseId']} depends on unknown phases: {sorted(missing)}")
        if phase["phaseId"] in phase["dependsOn"]:
            raise FactoryPlanError(f"phase {phase['phaseId']} cannot depend on itself")

    # A topological traversal rejects cycles before any Workflow Step is created.
    remaining = {key: set(value["dependsOn"]) for key, value in phase_by_id.items()}
    resolved: set[str] = set()
    while remaining:
        ready = {key for key, dependencies in remaining.items() if dependencies <= resolved}
        if not ready:
            raise FactoryPlanError("phase dependency graph contains a cycle")
        resolved.update(ready)
        for key in ready:
            remaining.pop(key)

    assignment_ids: set[str] = set()
    assignment_count = 0
    for phase in plan["phases"]:
        if len(phase["assignments"]) > limits["maxParallelAssignments"]:
            raise FactoryPlanError(f"phase {phase['phaseId']} has more assignments than maxParallelAssignments")
        for assignment in phase["assignments"]:
            assignment_count += 1
            assignment_id = assignment["assignmentId"]
            if assignment_id in assignment_ids:
                raise FactoryPlanError(f"duplicate assignmentId: {assignment_id}")
            assignment_ids.add(assignment_id)
            role_id = assignment["roleId"]
            if role_id not in registered or role_id not in roles:
                raise FactoryPlanError(f"assignment references an unregistered role: {role_id}")
            role = roles[role_id]
            skill_id = assignment["skillId"]
            if skill_id not in role.get("skillIds", []):
                raise FactoryPlanError(f"Skill {skill_id} is not declared by Role {role_id}")
            skill_path = root / "skills" / skill_id / "skill.json"
            try:
                skill = json.loads(skill_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise FactoryPlanError(f"missing or invalid Skill definition: {skill_id}") from exc
            if role_id not in skill.get("compatibleRoleIds", []):
                raise FactoryPlanError(f"Skill {skill_id} is not compatible with Role {role_id}")
            unknown_types = set(assignment["outputEntityTypes"]) - known_classes
            if unknown_types:
                raise FactoryPlanError(f"assignment references unknown ontology classes: {sorted(unknown_types)}")
            if not set(assignment["outputEntityTypes"]) <= set(role.get("outputEntityTypes", [])):
                raise FactoryPlanError(f"assignment output types exceed Role {role_id} contract")
            if not set(assignment["outputEntityTypes"]) <= set(skill.get("outputEntityTypes", [])):
                raise FactoryPlanError(f"assignment output types exceed Skill {skill_id} contract")
    if assignment_count > limits["maxAgentAssignments"]:
        raise FactoryPlanError("actual assignment count exceeds plan maxAgentAssignments")
    if limits["maxToolCalls"] < assignment_count:
        raise FactoryPlanError("maxToolCalls must provide at least one call budget unit per assignment")
    if plan["riskAssessment"]["level"] in {"high", "critical"} and not plan["riskAssessment"]["requiresHumanApproval"]:
        raise FactoryPlanError("high or critical risk plan must require human approval")
    return {
        "valid": True,
        "planId": plan["planId"],
        "phaseCount": len(plan["phases"]),
        "assignmentCount": assignment_count,
        "ontologySnapshotId": plan["ontologyBinding"]["snapshotId"],
        "workflowStateMutationAllowed": False,
        "permissionGrantAllowed": False,
        "approvalAuthority": "independent-human-or-policy-service",
    }
