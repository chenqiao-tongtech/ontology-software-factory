"""Validate role, Skill, tool and Agent handoff contracts without executing agents."""
from __future__ import annotations
import json
from pathlib import Path
from typing import Any
from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[2]
ENTITY_TYPES = {"Requirement","Product","Component","Version","Artifact","Build","TestRun","Vulnerability","Release","Deployment","Incident","OntologyCandidate","OntologyTermCandidate","OntologyRelationCandidate","OntologyConstraintCandidate","CompetencyQuestion","OntologySourceEvidence","OntologyEvaluation","OntologyApproval","OntologyRevision"}

def read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as stream:
        return json.load(stream)

def schema_errors(instance: Any, schema: dict[str, Any], label: str) -> list[str]:
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    result=[]
    for error in validator.iter_errors(instance):
        path=".".join(str(part) for part in error.absolute_path) or "$"
        result.append(f"{label} {path}: {error.message}")
    return result

def _load_roles(root: Path) -> tuple[list[dict[str, Any]], list[str]]:
    errors=[]; roles=[]
    path=root/"agents"/"schemas"/"role-definition.schema.json"
    try: schema=read_json(path); Draft202012Validator.check_schema(schema)
    except Exception as exc: return [], [f"cannot load role schema: {exc}"]
    files=sorted((root/"agents"/"roles").glob("*.json"))
    for file in files:
        try: role=read_json(file)
        except Exception as exc: errors.append(f"cannot load role {file.name}: {exc}"); continue
        errors.extend(schema_errors(role,schema,file.name))
        if isinstance(role,dict): roles.append(role)
    if not roles: errors.append("no role definitions found under agents/roles")
    ids=[r.get("roleId") for r in roles]
    if len(ids)!=len(set(ids)): errors.append("duplicate roleId found")
    return roles,errors

def _load_skills(root: Path) -> tuple[list[dict[str, Any]], list[str]]:
    errors=[]; skills=[]
    try:
        schema=read_json(root/"skills"/"schemas"/"skill-definition.schema.json")
        Draft202012Validator.check_schema(schema)
    except Exception as exc: return [], [f"cannot load Skill schema: {exc}"]
    for file in sorted((root/"skills").glob("*/skill.json")):
        try: skill=read_json(file)
        except Exception as exc: errors.append(f"cannot load Skill {file}: {exc}"); continue
        errors.extend(schema_errors(skill,schema,str(file.relative_to(root))))
        if isinstance(skill,dict):
            skills.append(skill)
            instructions=file.parent/"SKILL.md"
            if not instructions.is_file(): errors.append(f"{skill.get('skillId')}: missing SKILL.md instructions")
    ids=[s.get("skillId") for s in skills]
    if len(ids)!=len(set(ids)): errors.append("duplicate skillId found")
    return skills,errors

def validate_agent_catalog(root: Path = ROOT) -> list[str]:
    errors=[]
    try:
        tool_doc=read_json(root/"agents"/"tool-catalog.json")
        permission=read_json(root/"policies"/"agent-permissions.json")
        context_policy=read_json(root/"policies"/"context-policy.json")
    except Exception as exc: return [f"cannot load tool/policy configuration: {exc}"]
    tools=tool_doc.get("tools",[])
    tool_ids=[t.get("toolId") for t in tools if isinstance(t,dict)]
    if len(tool_ids)!=len(set(tool_ids)): errors.append("duplicate toolId found")
    tool_by_id={t.get("toolId"):t for t in tools if isinstance(t,dict)}
    global_denied_tools=set(permission.get("globallyDeniedToolIds",[]))
    global_denied_actions=set(permission.get("globallyDeniedActions",[]))
    roles,role_errors=_load_roles(root); errors.extend(role_errors)
    skills,skill_errors=_load_skills(root); errors.extend(skill_errors)
    role_by_id={r.get("roleId"):r for r in roles if isinstance(r,dict)}
    skill_by_id={s.get("skillId"):s for s in skills if isinstance(s,dict)}
    for role in roles:
        role_id=role.get("roleId","<unknown-role>")
        role_tools=set(role.get("toolIds",[])); role_skills=set(role.get("skillIds",[]))
        for tool_id in sorted(role_tools):
            tool=tool_by_id.get(tool_id)
            if not tool:
                errors.append(f"{role_id}: unknown toolId {tool_id}"); continue
            if not tool.get("mvpEnabled",False): errors.append(f"{role_id}: tool {tool_id} is not enabled in MVP")
            if tool_id in global_denied_tools: errors.append(f"{role_id}: globally denied tool {tool_id} must not be granted")
        conflict=sorted(set(role.get("allowedActions",[])) & set(role.get("forbiddenActions",[])))
        if conflict: errors.append(f"{role_id}: actions both allowed and forbidden: {', '.join(conflict)}")
        blocked=sorted(set(role.get("allowedActions",[])) & global_denied_actions)
        if blocked: errors.append(f"{role_id}: globally denied actions must not be allowed: {', '.join(blocked)}")
        for required in global_denied_actions:
            # Explicit prohibition is documented for critical controls; permission engine remains authoritative.
            if required in {"production.deploy","secrets.read.raw","agent.approve_self","cross_tenant.read"} and required not in set(role.get("forbiddenActions",[])):
                errors.append(f"{role_id}: must explicitly list {required} as forbidden")
        for skill_id in sorted(role_skills):
            skill=skill_by_id.get(skill_id)
            if not skill:
                errors.append(f"{role_id}: references missing Skill {skill_id}"); continue
            if role_id not in skill.get("compatibleRoleIds",[]):
                errors.append(f"{role_id}: Skill {skill_id} is not compatible with this role")
            missing=set(skill.get("requiredToolIds",[]))-role_tools
            if missing: errors.append(f"{role_id}: Skill {skill_id} requires tools not granted to role: {', '.join(sorted(missing))}")
        for skill in skills:
            if role_id in skill.get("compatibleRoleIds",[]) and skill.get("skillId") not in role_skills:
                errors.append(f"{role_id}: Skill {skill.get('skillId')} lists this role as compatible but role does not reference it")
        ctx=role.get("contextPolicy",{})
        shared=set(ctx.get("sharedContextFields",[])); local=set(ctx.get("taskLocalContextFields",[])); restricted=set(ctx.get("restrictedContextFields",[]))
        if shared & restricted: errors.append(f"{role_id}: context fields both shared and restricted: {', '.join(sorted(shared & restricted))}")
        if local & restricted: errors.append(f"{role_id}: context fields both task-local and restricted: {', '.join(sorted(local & restricted))}")
        if not {"raw_passwords","API_keys","production_credentials"}.issubset(restricted):
            errors.append(f"{role_id}: restricted context must exclude raw_passwords, API_keys and production_credentials")
        if not ctx.get("untrustedInputs"): errors.append(f"{role_id}: untrustedInputs must be declared")
        expected_instructions=role.get("handoffRequirements",[])
        if not expected_instructions: errors.append(f"{role_id}: handoffRequirements cannot be empty")
    # Validate handoff examples and ensure task/result role and output types align.
    task_schema=read_json(root/"contracts"/"schemas"/"agent-task.schema.json")
    result_schema=read_json(root/"contracts"/"schemas"/"agent-result.schema.json")
    task=read_json(root/"examples"/"agent-handoff"/"requirement-task.json")
    result=read_json(root/"examples"/"agent-handoff"/"requirement-result.json")
    errors.extend(schema_errors(task,task_schema,"example task"))
    errors.extend(schema_errors(result,result_schema,"example result"))
    if task.get("taskId") != result.get("taskId"): errors.append("example result taskId does not match task")
    if task.get("roleId") != result.get("roleId"): errors.append("example result roleId does not match task")
    for field in ("ontologyVersion", "ontologySnapshotId", "ontologyDigest", "ontologySchemaVersion", "roleDigest", "skillRefs"):
        if task.get(field) != result.get(field): errors.append(f"example result {field} does not match task")
    role=role_by_id.get(task.get("roleId"))
    if role:
        allowed=set(role.get("outputEntityTypes",[]))
        for output in result.get("outputs",[]):
            if output.get("entityType") not in allowed:
                errors.append(f"example result output type {output.get('entityType')} is not allowed for role {role.get('roleId')}")
    status=result.get("status")
    if status=="succeeded" and (not result.get("outputs") or not result.get("evidenceRefs")):
        errors.append("succeeded result requires at least one output and evidence reference")
    if status=="blocked" and not result.get("blockedReasons"):
        errors.append("blocked result requires blockedReasons")
    if status=="needs_human_review" and not result.get("humanReviewRequired"):
        errors.append("needs_human_review status requires humanReviewRequired=true")
    # Sanity check central context policy is aligned with the role declarations.
    restricted_names={name for klass in context_policy.get("contextClasses",[]) if klass.get("class")=="restricted-context" for name in klass.get("examples",[])}
    if not {"raw_passwords","API_keys","production_credentials"}.issubset(restricted_names):
        errors.append("central context policy must classify secrets and production credentials as restricted")
    return sorted(set(errors))

def main_validation_summary(root: Path = ROOT) -> tuple[list[str],dict[str,int]]:
    errors=validate_agent_catalog(root)
    try:
        roles=len(list((root/"agents"/"roles").glob("*.json")))
        skills=len(list((root/"skills").glob("*/skill.json")))
        tools=len(read_json(root/"agents"/"tool-catalog.json").get("tools",[]))
    except Exception:
        roles=skills=tools=0
    return errors,{"roles":roles,"skills":skills,"tools":tools}
