"""Validation of the bounded multi-agent team topology used by the MVP."""
from __future__ import annotations
import json
from pathlib import Path
from typing import Any
try:
    from jsonschema import Draft202012Validator
except ImportError:  # schema validation is optional in minimal source-only installs
    Draft202012Validator = None


def validate_team(root: Path, team: dict[str, Any] | None = None) -> list[str]:
    errors: list[str] = []
    team_path = root / "agents/teams/software-factory-mvp.json"
    if team is None:
        try:
            team = json.loads(team_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return [f"cannot load team topology: {exc}"]
    if Draft202012Validator is not None:
        try:
            team_schema = json.loads((root / "contracts/schemas/agent-team.schema.json").read_text(encoding="utf-8"))
            errors.extend(f"team schema violation at {list(e.absolute_path)}: {e.message}" for e in Draft202012Validator(team_schema).iter_errors(team))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"cannot load agent-team schema: {exc}")
    if team.get("schemaVersion") != "1.0.0":
        errors.append("team schemaVersion must be 1.0.0")
    if team.get("pattern") != "bounded_specialist_team_with_deterministic_workflow_control":
        errors.append("MVP must use bounded specialist team with deterministic workflow control")
    controller = team.get("controller") or {}
    if controller.get("type") != "deterministic" or controller.get("llmPowered") is not False:
        errors.append("team controller must be deterministic and not LLM-powered")
    if controller.get("mayGrantPermissions") is not False:
        errors.append("team controller must not grant permissions")
    limits = team.get("limits") or {}
    for key, minimum in (("maxAgentHops", 1), ("maxRevisionLoops", 0), ("maxParallelAgents", 1), ("defaultTaskTimeoutSeconds", 1)):
        if not isinstance(limits.get(key), int) or limits[key] < minimum:
            errors.append(f"limits.{key} must be an integer >= {minimum}")
    role_defs = {}
    for path in sorted((root / "agents/roles").glob("*.json")):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            role_defs[value.get("roleId")] = path
        except (OSError, json.JSONDecodeError):
            errors.append(f"cannot read role definition: {path}")
    registered = team.get("registeredRoles") or []
    role_ids = [x.get("roleId") for x in registered]
    duplicates = sorted({x for x in role_ids if role_ids.count(x) > 1})
    if duplicates:
        errors.append(f"duplicate registered role IDs: {', '.join(duplicates)}")
    for rid in role_ids:
        if rid not in role_defs:
            errors.append(f"unknown role in topology: {rid}")
    for role in registered:
        if role.get("mayApproveHighRisk") is not False:
            errors.append(f"role {role.get('roleId')} cannot approve its own high-risk result")
    stages = team.get("stages") or []
    stage_ids = [x.get("stageId") for x in stages]
    if len(set(stage_ids)) != len(stage_ids):
        errors.append("stage IDs must be unique")
    known_stages = set(stage_ids)
    for stage in stages:
        for dep in stage.get("requires") or []:
            if dep not in known_stages:
                errors.append(f"stage {stage.get('stageId')} requires unknown stage {dep}")
        for rid in stage.get("roleIds") or []:
            if rid not in role_ids:
                errors.append(f"stage {stage.get('stageId')} references unregistered role {rid}")
    groups = [s for s in stages if s.get("mode") == "parallel_all_required"]
    if not any(set(g.get("roleIds") or []) >= {"test-agent", "security-reviewer"} for g in groups):
        errors.append("candidate verification must run test-agent and security-reviewer as independent parallel branches")
    joins = [s for s in stages if s.get("mode") == "deterministic_join"]
    if not joins:
        errors.append("team requires a deterministic join for independent verification results")
    failure_paths = team.get("failurePaths") or []
    bounded = [f for f in failure_paths if f.get("action") == "bounded_revision_loop"]
    if not bounded or any(not isinstance(f.get("maxIterations"), int) or f["maxIterations"] < 1 or f["maxIterations"] > limits.get("maxRevisionLoops", 0) for f in bounded):
        errors.append("revision loop must be explicitly bounded by team limits")
    rules = team.get("handoffRules") or {}
    if rules.get("agentsMayMutateWorkflowState") is not False:
        errors.append("agents must not directly mutate workflow state")
    if rules.get("agentsMayApproveOwnHighRiskResult") is not False:
        errors.append("agents must not approve their own high-risk result")
    if rules.get("toolsGrantedBy") != "policy-runtime-only":
        errors.append("tool grants must come from policy runtime only")
    schema_path = root / str(rules.get("schemaPath", ""))
    if not schema_path.is_file():
        errors.append("handoff schema path is missing")
    return errors


def validate_handoff_instance(root: Path, instance: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    schema_path = root / "contracts/schemas/agent-handoff.schema.json"
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"cannot load handoff schema: {exc}"]
    if Draft202012Validator is not None:
        errors.extend(f"handoff schema violation at {list(e.absolute_path)}: {e.message}" for e in Draft202012Validator(schema).iter_errors(instance))
    else:
        missing = sorted(set(schema.get("required", [])) - set(instance))
        if missing:
            errors.append(f"handoff missing required fields: {', '.join(missing)}")
    if instance.get("fromRoleId") == instance.get("toRoleId"):
        errors.append("handoff sender and recipient must differ")
    role_dir = root / "agents/roles"
    roles = {}
    for path in role_dir.glob("*.json"):
        try:
            role = json.loads(path.read_text(encoding="utf-8"))
            roles[role.get("roleId")] = role
        except (OSError, json.JSONDecodeError):
            continue
    sender, recipient = instance.get("fromRoleId"), instance.get("toRoleId")
    if sender not in roles:
        errors.append(f"handoff sender role is unknown: {sender}")
    if recipient not in roles:
        errors.append(f"handoff recipient role is unknown: {recipient}")
    if recipient in roles:
        allowed = set(roles[recipient].get("toolIds", []))
        requested = set(instance.get("allowedToolIds", []))
        if not requested <= allowed:
            errors.append(f"handoff tools exceed recipient role declaration: {sorted(requested - allowed)}")
    return errors


def validate_handoff_example(root: Path) -> list[str]:
    example_path = root / "examples/multi-agent-handoffs/requirement-to-architecture.json"
    try:
        instance = json.loads(example_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"cannot load handoff example: {exc}"]
    return validate_handoff_instance(root, instance)


def validate_from_root(root: Path) -> list[str]:
    errors = validate_team(root) + validate_handoff_example(root)
    try:
        baseline = json.loads((root / "config/architecture-baseline.json").read_text(encoding="utf-8"))
        team = json.loads((root / "agents/teams/software-factory-mvp.json").read_text(encoding="utf-8"))
        limits = team.get("limits", {})
        declared = baseline.get("multi_agent_architecture", {})
        for baseline_key, team_key in (("max_agent_hops", "maxAgentHops"), ("max_revision_loops", "maxRevisionLoops"), ("max_parallel_agents", "maxParallelAgents")):
            if declared.get(baseline_key) != limits.get(team_key):
                errors.append(f"architecture baseline and team topology disagree on {baseline_key}")
        if declared.get("team_config_path") != "agents/teams/software-factory-mvp.json":
            errors.append("architecture baseline team_config_path is not canonical")
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"cannot compare baseline with team topology: {exc}")
    return errors
