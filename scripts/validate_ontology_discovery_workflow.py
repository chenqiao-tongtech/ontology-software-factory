#!/usr/bin/env python3
"""Validate the ontology discovery team and workflow security invariants."""
from __future__ import annotations
import json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))
from validate_workflow_definition import validate as validate_workflow  # noqa: E402

def main() -> int:
    errors = []
    try:
        team = json.loads((ROOT / "agents/teams/ontology-discovery-mvp.json").read_text(encoding="utf-8"))
        workflow = json.loads((ROOT / "workflows/definitions/ontology-discovery-review-v1.json").read_text(encoding="utf-8"))
        roles = {json.loads(p.read_text(encoding="utf-8"))["roleId"]: json.loads(p.read_text(encoding="utf-8")) for p in (ROOT / "agents/roles").glob("*.json")}
        skills = {json.loads(p.read_text(encoding="utf-8"))["skillId"]: json.loads(p.read_text(encoding="utf-8")) for p in (ROOT / "skills").glob("*/skill.json")}
        catalog = json.loads((ROOT / "agents/tool-catalog.json").read_text(encoding="utf-8"))
        tool_ids = {x["toolId"] for x in catalog["tools"]}
    except Exception as exc:
        print(f"Ontology discovery architecture validation: FAIL ({type(exc).__name__}: {exc})")
        return 1
    if team.get("controller", {}).get("llmPowered") is not False:
        errors.append("ontology discovery controller must be deterministic")
    if team.get("handoffRules", {}).get("agentsMayPublishOntology") is not False:
        errors.append("agents must not publish ontology directly")
    if team.get("handoffRules", {}).get("agentsMayApproveOwnHighRiskResult") is not False:
        errors.append("agents must not approve their own results")
    role_ids = {x.get("roleId") for x in team.get("registeredRoles", [])}
    if role_ids != {"ontology-discovery-agent", "ontology-critic-agent"}:
        errors.append("ontology discovery team must include discovery and independent critic roles")
    for role_id in role_ids:
        if role_id not in roles:
            errors.append(f"unknown team role {role_id}")
    for role_id, role in roles.items():
        if role_id in role_ids:
            if "ontology.publish" not in role.get("forbiddenActions", []):
                errors.append(f"{role_id} must explicitly forbid ontology.publish")
            if set(role.get("toolIds", [])) - tool_ids:
                errors.append(f"{role_id} has undefined tool IDs")
            for skill_id in role.get("skillIds", []):
                if skill_id not in skills:
                    errors.append(f"{role_id} references unknown Skill {skill_id}")
                elif role_id not in skills[skill_id].get("compatibleRoleIds", []):
                    errors.append(f"Skill {skill_id} incompatible with {role_id}")
    errors.extend(validate_workflow(workflow))
    stages = {s.get("id"): s for s in workflow.get("steps", [])}
    if stages.get("human-domain-review", {}).get("executionMode") != "human":
        errors.append("human-domain-review must be a human step")
    if stages.get("human-domain-review", {}).get("requiresApproval") is not True:
        errors.append("human-domain-review must require approval")
    if any(s.get("sideEffect") == "external" for s in workflow.get("steps", [])):
        errors.append("ontology discovery workflow must not perform external production side effects")
    if not all(stage in stages for stage in ("independent-critic", "deterministic-validation", "benchmark-evaluation", "human-domain-review")):
        errors.append("required independent critic/validation/evaluation/human gate is missing")
    if errors:
        print(f"Ontology discovery architecture validation: FAIL ({len(errors)} issue(s))")
        for err in errors: print(f"- {err}")
        return 1
    print("Ontology discovery architecture validation: PASS")
    print(f"Roles: {len(role_ids)}; workflow steps: {len(workflow['steps'])}; direct production mutation: forbidden")
    return 0
if __name__ == "__main__":
    raise SystemExit(main())
