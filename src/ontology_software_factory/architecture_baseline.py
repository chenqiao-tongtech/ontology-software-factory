"""Machine-checkable architecture/design baseline validation."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

VALID_STATUSES = {"planned", "partial", "implemented", "defined"}


def _unique_ids(items: list[dict[str, Any]], key: str, label: str, errors: list[str]) -> None:
    values = [item.get(key) for item in items]
    if any(not isinstance(value, str) or not value.strip() for value in values):
        errors.append(f"{label}: every item must have a non-empty {key}")
    duplicates = sorted({value for value in values if values.count(value) > 1})
    if duplicates:
        errors.append(f"{label}: duplicate {key}: {', '.join(map(str, duplicates))}")


def validate_baseline(root: Path, baseline: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if baseline.get("schema_version") != "1.0.0":
        errors.append("schema_version must be 1.0.0")
    if baseline.get("baseline_id") != "software-factory-architecture-baseline":
        errors.append("unexpected baseline_id")
    if (baseline.get("project") or {}).get("name") != "ontology-software-factory":
        errors.append("project.name must be ontology-software-factory")

    principles = baseline.get("principles") or []
    constraints = baseline.get("constraints") or []
    subsystems = baseline.get("subsystems") or []
    roadmap = baseline.get("roadmap") or []
    _unique_ids(principles, "id", "principles", errors)
    _unique_ids(constraints, "id", "constraints", errors)
    _unique_ids(subsystems, "id", "subsystems", errors)
    _unique_ids(roadmap, "id", "roadmap", errors)

    principle_ids = {item.get("id") for item in principles}
    required_principles = {f"AP-{i:02d}" for i in range(1, 14)}
    missing_principles = sorted(required_principles - principle_ids)
    if missing_principles:
        errors.append(f"missing principles: {', '.join(missing_principles)}")
    constraint_ids = {item.get("id") for item in constraints}
    required_constraints = {f"C-{i:02d}" for i in range(1, 10)}
    missing_constraints = sorted(required_constraints - constraint_ids)
    if missing_constraints:
        errors.append(f"missing constraints: {', '.join(missing_constraints)}")

    subsystem_ids = {item.get("id") for item in subsystems}
    module_ids: list[str] = []
    for subsystem in subsystems:
        sid = subsystem.get("id", "<missing-id>")
        deps = subsystem.get("depends_on") or []
        if not isinstance(deps, list):
            errors.append(f"{sid}: depends_on must be an array")
            continue
        for dep in deps:
            if dep not in subsystem_ids:
                errors.append(f"{sid}: unknown dependency {dep}")
            if dep == sid:
                errors.append(f"{sid}: cannot depend on itself")
        modules = subsystem.get("modules") or []
        _unique_ids(modules, "id", f"modules in {sid}", errors)
        for module in modules:
            module_ids.append(module.get("id"))
            if module.get("status") not in VALID_STATUSES:
                errors.append(f"{module.get('id')}: invalid status {module.get('status')}")
            path = module.get("path")
            if not isinstance(path, str) or not path:
                errors.append(f"{module.get('id')}: path is required")
            elif Path(path).is_absolute() or ".." in Path(path).parts:
                errors.append(f"{module.get('id')}: path must be relative and stay inside repository")
            elif module.get("status") == "implemented" and not (root / path).exists():
                errors.append(f"{module.get('id')}: implemented path does not exist: {path}")
    duplicates = sorted({value for value in module_ids if value and module_ids.count(value) > 1})
    if duplicates:
        errors.append(f"module IDs must be unique across subsystems: {', '.join(duplicates)}")

    # Detect subsystem dependency cycles with a three-color DFS.
    graph = {item.get("id"): item.get("depends_on") or [] for item in subsystems if item.get("id")}
    visiting: set[str] = set()
    visited: set[str] = set()
    cycle_nodes: set[str] = set()

    def visit(node: str, stack: list[str]) -> None:
        if node in visiting:
            if node in stack:
                cycle_nodes.update(stack[stack.index(node):])
            return
        if node in visited:
            return
        visiting.add(node)
        stack.append(node)
        for dependency in graph.get(node, []):
            if dependency in graph:
                visit(dependency, stack)
        stack.pop()
        visiting.remove(node)
        visited.add(node)

    for node in graph:
        visit(node, [])
    if cycle_nodes:
        errors.append(f"subsystem dependency cycle: {', '.join(sorted(cycle_nodes))}")

    if len(roadmap) != 10:
        errors.append("roadmap must define P0 through P9")
    for index, phase in enumerate(roadmap):
        if phase.get("id") != f"P{index}":
            errors.append("roadmap phases must be contiguous and ordered P0..P9")
        if not isinstance(phase.get("article"), int):
            errors.append(f"{phase.get('id')}: article must be an integer")
        if not phase.get("outputs"):
            errors.append(f"{phase.get('id')}: outputs must not be empty")
        if not phase.get("exit_criteria"):
            errors.append(f"{phase.get('id')}: exit_criteria must not be empty")
        if phase.get("status") not in VALID_STATUSES:
            errors.append(f"{phase.get('id')}: invalid status {phase.get('status')}")

    ontology = baseline.get("ontology_plan") or {}
    current_ontology_path = root / "ontology/software-factory-ontology.json"
    try:
        current_ontology = json.loads(current_ontology_path.read_text(encoding="utf-8"))
        defined_classes = {item.get("name") for item in current_ontology.get("classes", [])}
        planned_classes = set(ontology.get("core_classes_current") or [])
        if defined_classes != planned_classes:
            missing = sorted(planned_classes - defined_classes)
            extra = sorted(defined_classes - planned_classes)
            errors.append(f"ontology class list mismatch; missing={missing}, extra={extra}")
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"cannot read current ontology: {exc}")

    # Multi-agent coordination is a required, machine-checked part of the core architecture.
    multi = baseline.get("multi_agent_architecture") or {}
    required_multi_fields = ["pattern", "controller", "coordination_patterns", "parallel_verification_roles", "max_agent_hops", "max_revision_loops", "max_parallel_agents", "team_config_path", "handoff_schema_path"]
    for field in required_multi_fields:
        if field not in multi:
            errors.append(f"multi_agent_architecture missing {field}")
    if multi.get("pattern") != "bounded_specialist_team_with_deterministic_workflow_control":
        errors.append("multi_agent_architecture must define bounded specialist topology")
    controller = multi.get("controller") or {}
    if controller.get("llmPowered") is not False:
        errors.append("multi-agent controller must be deterministic, not LLM-powered")
    if controller.get("component") != "workflow-state-machine":
        errors.append("multi-agent controller must reference workflow-state-machine")
    if set(multi.get("parallel_verification_roles") or []) != {"test-agent", "security-reviewer"}:
        errors.append("multi-agent architecture must declare independent test and security reviewers")
    extensions_expected = set(ontology.get("operational_extension_classes") or [])
    try:
        current_ontology = json.loads(current_ontology_path.read_text(encoding="utf-8"))
        ext_defined = {item.get("name") for item in (current_ontology.get("operationalExtensions") or {}).get("classes", [])}
        if extensions_expected != ext_defined:
            errors.append(f"operational extension class list mismatch; expected={sorted(extensions_expected)}, actual={sorted(ext_defined)}")
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"cannot read operational ontology extensions: {exc}")
    try:
        from ontology_software_factory.multi_agent_architecture import validate_from_root as validate_multi_agent
        errors.extend(validate_multi_agent(root))
    except Exception as exc:
        errors.append(f"multi-agent topology validator failed: {exc}")

    for relpath in baseline.get("required_design_documents") or []:
        path = Path(relpath)
        if path.is_absolute() or ".." in path.parts:
            errors.append(f"invalid design document path: {relpath}")
        elif not (root / path).is_file():
            errors.append(f"missing design document: {relpath}")

    if not (root / "config/mvp-scope.json").is_file():
        errors.append("missing config/mvp-scope.json")
    return errors


def validate_from_root(root: Path) -> list[str]:
    baseline_path = root / "config/architecture-baseline.json"
    try:
        baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"cannot load architecture baseline: {exc}"]
    return validate_baseline(root, baseline)
