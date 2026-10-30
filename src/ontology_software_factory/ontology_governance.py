"""Ontology consumer dependency graph and version compatibility checks.

The graph is derived from explicit typed references already present in role,
skill, workflow, tool and JSON Schema definitions. It does not infer consumers
from natural-language descriptions.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ontology_software_factory.ontology_versioning import diff_snapshots


DEFAULT_REFERENCE_MAP = {
    "schemaVersion": "1.0.0",
    "roleGlob": "agents/roles/*.json",
    "skillGlob": "skills/*/skill.json",
    "workflowGlob": "workflows/definitions/*.json",
    "toolCatalog": "agents/tool-catalog.json",
    "contractFiles": [
        "contracts/schemas/agent-task.schema.json",
        "contracts/schemas/agent-result.schema.json",
    ],
    "classReferenceFields": ["inputEntityTypes", "outputEntityTypes"],
}


def _read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _semver(value: Any) -> tuple[int, int, int] | None:
    try:
        parts = str(value).split(".")
        if len(parts) != 3 or any(not part.isdigit() for part in parts):
            return None
        return tuple(int(part) for part in parts)  # type: ignore[return-value]
    except (TypeError, ValueError):
        return None


def _walk_enums(value: Any):
    if isinstance(value, dict):
        enum = value.get("enum")
        if isinstance(enum, list):
            yield from enum
        for child in value.values():
            yield from _walk_enums(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_enums(child)


def build_consumer_graph(root: Path, ontology: dict, reference_map: dict | None = None,
                         additional_ontologies: list[dict] | None = None) -> dict:
    """Build a verifiable graph from repository definitions and explicit typed fields."""
    mapping = reference_map or _read_json(root / "ontology" / "consumer-reference-map.json") or DEFAULT_REFERENCE_MAP
    classes = set()
    for item in ontology.get("classes", []):
        if isinstance(item, dict) and item.get("name"):
            classes.add(str(item["name"]))
    for historical in additional_ontologies or []:
        for item in historical.get("classes", []):
            if isinstance(item, dict) and item.get("name"):
                classes.add(str(item["name"]))
        historical_ext = historical.get("operationalExtensions", {})
        if isinstance(historical_ext, dict):
            for item in historical_ext.get("classes", []):
                if isinstance(item, dict) and item.get("name"):
                    classes.add(str(item["name"]))
    ext = ontology.get("operationalExtensions", {})
    if isinstance(ext, dict):
        for item in ext.get("classes", []):
            if isinstance(item, dict) and item.get("name"):
                classes.add(str(item["name"]))

    nodes: dict[str, dict] = {}
    edges: list[dict] = []
    issues: list[dict] = []
    dependencies = mapping.get("dependencyFields", {})
    role_skill_field = dependencies.get("roleSkills", "skillIds")
    role_tool_field = dependencies.get("roleTools", "toolIds")
    skill_role_field = dependencies.get("skillCompatibleRoles", "compatibleRoleIds")
    skill_tool_field = dependencies.get("skillTools", "requiredToolIds")
    workflow_role_field = dependencies.get("workflowRole", "roleId")
    workflow_skill_field = dependencies.get("workflowSkill", "skillId")
    roles: dict[str, dict] = {}
    skills: dict[str, dict] = {}
    tools: dict[str, dict] = {}

    def add_node(node_id: str, kind: str, label: str, path: str | None = None):
        nodes[node_id] = {"id": node_id, "kind": kind, "label": label, "sourcePath": path}

    def add_edge(source: str, target: str, relation: str):
        edge = {"source": source, "target": target, "relation": relation}
        if edge not in edges:
            edges.append(edge)

    role_paths = sorted(root.glob(str(mapping["roleGlob"])))
    if not role_paths:
        issues.append({"code": "consumer-source-files-not-found", "source": mapping["roleGlob"]})
    for path in role_paths:
        data = _read_json(path)
        role_id = str(data.get("roleId", ""))
        if not role_id:
            issues.append({"code": "role-id-missing", "path": str(path.relative_to(root))})
            continue
        node_id = "role:" + role_id
        roles[role_id] = data
        add_node(node_id, "agent-role", data.get("displayName", role_id), str(path.relative_to(root)))
        refs = sorted({str(x) for field in mapping["classReferenceFields"] for x in data.get(field, [])})
        for name in refs:
            if name not in classes:
                issues.append({"code": "unknown-ontology-class", "consumer": node_id, "class": name})
            else:
                add_edge("class:" + name, node_id, "consumes-ontology-class")
        for skill_id in data.get(role_skill_field, []):
            add_edge(node_id, "skill:" + str(skill_id), "uses-skill")
        for tool_id in data.get(role_tool_field, []):
            add_edge(node_id, "tool:" + str(tool_id), "uses-tool")

    skill_paths = sorted(root.glob(str(mapping["skillGlob"])))
    if not skill_paths:
        issues.append({"code": "consumer-source-files-not-found", "source": mapping["skillGlob"]})
    for path in skill_paths:
        data = _read_json(path)
        skill_id = str(data.get("skillId", ""))
        if not skill_id:
            issues.append({"code": "skill-id-missing", "path": str(path.relative_to(root))})
            continue
        node_id = "skill:" + skill_id
        skills[skill_id] = data
        add_node(node_id, "skill", data.get("title", skill_id), str(path.relative_to(root)))
        refs = sorted({str(x) for field in mapping["classReferenceFields"] for x in data.get(field, [])})
        for name in refs:
            if name not in classes:
                issues.append({"code": "unknown-ontology-class", "consumer": node_id, "class": name})
            else:
                add_edge("class:" + name, node_id, "consumes-ontology-class")
        for role_id in data.get(skill_role_field, []):
            add_edge(node_id, "role:" + str(role_id), "compatible-with-role")
            if role_id not in roles:
                issues.append({"code": "unknown-compatible-role", "consumer": node_id, "target": role_id})
        for tool_id in data.get(skill_tool_field, []):
            add_edge(node_id, "tool:" + str(tool_id), "requires-tool")

    workflow_paths = sorted(root.glob(str(mapping["workflowGlob"])))
    if not workflow_paths:
        issues.append({"code": "consumer-source-files-not-found", "source": mapping["workflowGlob"]})
    for path in workflow_paths:
        data = _read_json(path)
        workflow_id = str(data.get("id", path.stem))
        workflow_node = "workflow:" + workflow_id
        add_node(workflow_node, "workflow", data.get("name", workflow_id), str(path.relative_to(root)))
        for step in data.get("steps", []):
            if not isinstance(step, dict):
                continue
            step_node = workflow_node + "/step:" + str(step.get("id", "unknown"))
            add_node(step_node, "workflow-step", step.get("name", step.get("id", "step")), str(path.relative_to(root)))
            add_edge(workflow_node, step_node, "contains-step")
            role_id = step.get(workflow_role_field)
            skill_id = step.get(workflow_skill_field)
            if role_id:
                role_target = ("human-role:" if step.get("executionMode") == "human" else "role:") + str(role_id)
                if step.get("executionMode") == "human":
                    add_node(role_target, "human-approval-role", str(role_id), str(path.relative_to(root)))
                    add_edge(step_node, role_target, "requires-human-approval-role")
                else:
                    add_edge(step_node, role_target, "dispatches-role")
                    if role_id not in roles:
                        issues.append({"code": "unknown-role-reference", "consumer": step_node, "target": role_id})
            if skill_id:
                add_edge(step_node, "skill:" + str(skill_id), "invokes-skill")
                if skill_id not in skills:
                    issues.append({"code": "unknown-skill-reference", "consumer": step_node, "target": skill_id})

    tool_path = root / str(mapping["toolCatalog"])
    tool_data = _read_json(tool_path)
    if not tool_data:
        issues.append({"code": "consumer-source-file-missing-or-invalid", "source": str(mapping["toolCatalog"])})
    for item in tool_data.get("tools", []):
        tool_id = str(item.get("toolId", ""))
        if tool_id:
            node_id = "tool:" + tool_id
            tools[tool_id] = item
            add_node(node_id, "tool-contract", tool_id, str(tool_path.relative_to(root)))
    for edge in list(edges):
        if edge["target"].startswith("skill:") and edge["target"].split(":", 1)[1] not in skills:
            issues.append({"code": "unknown-skill-reference", "consumer": edge["source"], "target": edge["target"]})
        if edge["target"].startswith("tool:") and edge["target"].split(":", 1)[1] not in tools:
            issues.append({"code": "unknown-tool-reference", "consumer": edge["source"], "target": edge["target"]})

    for rel in mapping.get("contractFiles", []):
        path = root / str(rel)
        data = _read_json(path)
        if not data:
            issues.append({"code": "consumer-source-file-missing-or-invalid", "source": str(rel)})
        node_id = "contract:" + path.stem
        add_node(node_id, "json-contract", data.get("title", path.stem), str(rel))
        for value in sorted({str(x) for x in _walk_enums(data) if str(x) in classes}):
            add_edge("class:" + value, node_id, "constrains-entity-type")

    for name in sorted(classes):
        add_node("class:" + name, "ontology-class", name, "ontology/software-factory-ontology.json")
    return {
        "nodes": sorted(nodes.values(), key=lambda item: (item["kind"], item["id"])),
        "edges": sorted(edges, key=lambda item: (item["source"], item["relation"], item["target"])),
        "issues": issues,
        "summary": {
            "ontologyClasses": len(classes),
            "roles": len(roles),
            "skills": len(skills),
            "workflows": sum(1 for item in nodes.values() if item["kind"] == "workflow"),
            "workflowSteps": sum(1 for item in nodes.values() if item["kind"] == "workflow-step"),
            "tools": len(tools),
            "contracts": sum(1 for item in nodes.values() if item["kind"] == "json-contract"),
            "edges": len(edges),
            "issues": len(issues),
        },
        "referenceMap": mapping,
        "note": "依赖图来自角色/Skill 的输入输出实体类型、工具引用、工作流步骤引用及契约 enum；不从自然语言描述推测依赖。",
    }


def analyze_consumer_impact(changed_classes: list[str], graph: dict) -> dict:
    adjacency: dict[str, set[str]] = {}
    for edge in graph.get("edges", []):
        a, b = edge["source"], edge["target"]
        adjacency.setdefault(a, set()).add(b)
        adjacency.setdefault(b, set()).add(a)
    visited = {"class:" + name for name in changed_classes}
    frontier = list(visited)
    while frontier:
        current = frontier.pop()
        for neighbor in adjacency.get(current, set()):
            if neighbor not in visited:
                visited.add(neighbor)
                frontier.append(neighbor)
    node_map = {item["id"]: item for item in graph.get("nodes", [])}
    consumers = [node_map[item] for item in sorted(visited) if item in node_map and node_map[item]["kind"] != "ontology-class"]
    return {
        "changedClasses": sorted(set(changed_classes)),
        "affectedConsumers": consumers,
        "affectedConsumerCount": len(consumers),
        "reviewRequired": bool(changed_classes),
    }


def compatibility_report(before: dict, after: dict) -> dict:
    """Classify ontology changes conservatively; major bump is required for breaking changes."""
    diff = diff_snapshots(before, after)
    sections = diff["sections"]
    breaking: list[dict] = []
    review: list[dict] = []

    for section_name in ("coreClasses", "operationalClasses"):
        for item in sections[section_name]["removed"]:
            breaking.append({"kind": "class-removed", "section": section_name, "key": item["key"]})
        for item in sections[section_name]["changed"]:
            review.append({"kind": "class-definition-changed", "section": section_name, "key": item["key"]})

    for section_name in ("coreRelations", "operationalRelations"):
        for item in sections[section_name]["removed"]:
            breaking.append({"kind": "relation-removed", "section": section_name, "key": item["key"]})
        for item in sections[section_name]["changed"]:
            old, new = item["before"], item["after"]
            structural = ("source", "target", "field", "cardinality")
            if any(old.get(key) != new.get(key) for key in structural):
                breaking.append({"kind": "relation-contract-changed", "section": section_name, "key": item["key"], "before": old, "after": new})
            else:
                review.append({"kind": "relation-metadata-changed", "section": section_name, "key": item["key"]})

    for item in sections["controlledVocabularies"]["changed"]:
        old_values = set(item["before"].get("values", []))
        new_values = set(item["after"].get("values", []))
        removed = sorted(old_values - new_values)
        if removed:
            breaking.append({"kind": "vocabulary-values-removed", "key": item["key"], "values": removed})
        if new_values - old_values:
            review.append({"kind": "vocabulary-values-added", "key": item["key"], "values": sorted(new_values - old_values)})

    for item in sections["controlledVocabularies"]["removed"]:
        breaking.append({"kind": "vocabulary-removed", "key": item["key"]})
    for item in sections["mvpInvariants"]["removed"]:
        breaking.append({"kind": "invariant-removed", "key": item["key"]})
    for item in sections["mvpInvariants"]["added"]:
        review.append({"kind": "invariant-added", "key": item["key"]})

    old_version = before.get("ontologyVersion") or before.get("ontology", {}).get("ontologyVersion")
    new_version = after.get("ontologyVersion") or after.get("ontology", {}).get("ontologyVersion")
    old_semver, new_semver = _semver(old_version), _semver(new_version)
    major_bump = bool(old_semver and new_semver and new_semver[0] > old_semver[0])
    version_valid = bool(old_semver and new_semver and new_semver >= old_semver)
    if breaking and not major_bump:
        review.append({"kind": "major-version-bump-required", "from": old_version, "to": new_version})
    if not version_valid:
        review.append({"kind": "invalid-or-decreasing-semver", "from": old_version, "to": new_version})

    compatible = not breaking or major_bump
    return {
        "fromVersion": old_version,
        "toVersion": new_version,
        "compatible": compatible and version_valid,
        "breakingChanges": breaking,
        "reviewItems": review,
        "majorVersionBump": major_bump,
        "versionOrderValid": version_valid,
        "reviewRequired": bool(breaking or review),
        "summary": {
            "breakingChanges": len(breaking),
            "reviewItems": len(review),
            "addedClasses": len(sections["coreClasses"]["added"]) + len(sections["operationalClasses"]["added"]),
            "addedRelations": len(sections["coreRelations"]["added"]) + len(sections["operationalRelations"]["added"]),
        },
        "policy": "移除类/关系/词汇或放宽既有不变量按破坏性变更处理；关系端点、字段、基数变化需要主版本递增。新增项默认兼容但仍需评审。",
    }
