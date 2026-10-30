"""Versioned Skill registry with schema, role/tool compatibility and content locks."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator


class SkillRegistryError(ValueError):
    """A Skill definition or compatibility lock is invalid."""


@dataclass(frozen=True)
class SkillDescriptor:
    skill_id: str
    version: str
    title: str
    description: str
    compatible_role_ids: tuple[str, ...]
    required_tool_ids: tuple[str, ...]
    input_entity_types: tuple[str, ...]
    output_entity_types: tuple[str, ...]
    acceptance_criteria: tuple[str, ...]
    failure_conditions: tuple[str, ...]
    human_review_required: bool
    digest: str
    definition_path: str
    instruction_path: str


class SkillRegistry:
    """Loads Skills as immutable, content-addressed task procedures."""

    def __init__(self, project_root: str | Path):
        self.root = Path(project_root).resolve()
        schema_path = self.root / "skills/schemas/skill-definition.schema.json"
        self.schema = json.loads(schema_path.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(self.schema)
        self._roles = {
            item["roleId"]: item
            for item in (
                json.loads(path.read_text(encoding="utf-8"))
                for path in sorted((self.root / "agents/roles").glob("*.json"))
            )
        }
        self._tool_ids = {
            item["toolId"]
            for item in json.loads((self.root / "tools/registry.json").read_text(encoding="utf-8"))["tools"]
        }
        self._items: dict[str, SkillDescriptor] = {}
        self._definitions: dict[str, dict[str, Any]] = {}
        self._load_all()

    @staticmethod
    def _digest(definition: bytes, instructions: bytes) -> str:
        h = hashlib.sha256()
        h.update(b"skill-definition\0")
        h.update(definition)
        h.update(b"\0skill-instructions\0")
        h.update(instructions)
        return h.hexdigest()

    def _load_all(self) -> None:
        for directory in sorted((self.root / "skills").iterdir()):
            if not directory.is_dir() or directory.name == "schemas":
                continue
            definition_path = directory / "skill.json"
            instruction_path = directory / "SKILL.md"
            if not definition_path.is_file() or not instruction_path.is_file():
                raise SkillRegistryError(f"Skill {directory.name!r} requires skill.json and SKILL.md")
            raw = definition_path.read_bytes()
            instructions = instruction_path.read_bytes()
            try:
                definition = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise SkillRegistryError(f"invalid JSON in {definition_path}") from exc
            errors = list(Draft202012Validator(self.schema).iter_errors(definition))
            if errors:
                raise SkillRegistryError(f"invalid Skill {directory.name!r}: {errors[0].message}")
            skill_id = definition["skillId"]
            if skill_id != directory.name:
                raise SkillRegistryError(f"Skill directory and skillId differ: {directory.name!r}")
            if skill_id in self._items:
                raise SkillRegistryError(f"duplicate Skill ID: {skill_id}")
            for role_id in definition["compatibleRoleIds"]:
                role = self._roles.get(role_id)
                if role is None:
                    raise SkillRegistryError(f"Skill {skill_id!r} references unknown role {role_id!r}")
                missing_tools = set(definition["requiredToolIds"]) - set(role.get("toolIds", []))
                if missing_tools:
                    raise SkillRegistryError(
                        f"Skill {skill_id!r} requires tools unavailable to role {role_id!r}: {sorted(missing_tools)}"
                    )
            missing_registry_tools = set(definition["requiredToolIds"]) - self._tool_ids
            if missing_registry_tools:
                raise SkillRegistryError(f"Skill {skill_id!r} references unknown tools: {sorted(missing_registry_tools)}")
            version = definition["version"]
            if not re.fullmatch(r"\d+\.\d+\.\d+", version):
                raise SkillRegistryError(f"Skill {skill_id!r} has invalid semantic version")
            descriptor = SkillDescriptor(
                skill_id=skill_id, version=version, title=definition["title"],
                description=definition["description"],
                compatible_role_ids=tuple(definition["compatibleRoleIds"]),
                required_tool_ids=tuple(definition["requiredToolIds"]),
                input_entity_types=tuple(definition["inputEntityTypes"]),
                output_entity_types=tuple(definition["outputEntityTypes"]),
                acceptance_criteria=tuple(definition["acceptanceCriteria"]),
                failure_conditions=tuple(definition["failureConditions"]),
                human_review_required=bool(definition["humanReviewRequired"]),
                digest=self._digest(raw, instructions),
                definition_path=str(definition_path.relative_to(self.root)),
                instruction_path=str(instruction_path.relative_to(self.root)),
            )
            self._items[skill_id] = descriptor
            self._definitions[skill_id] = definition

    def list_skills(self, *, role_id: str | None = None) -> list[SkillDescriptor]:
        values = self._items.values()
        if role_id is not None:
            values = (item for item in values if role_id in item.compatible_role_ids)
        return sorted(values, key=lambda item: item.skill_id)

    def get(self, skill_id: str, *, role_id: str | None = None) -> SkillDescriptor:
        item = self._items.get(skill_id)
        if item is None:
            raise SkillRegistryError(f"unknown Skill: {skill_id}")
        if role_id is not None and role_id not in item.compatible_role_ids:
            raise SkillRegistryError(f"Skill {skill_id!r} is not compatible with role {role_id!r}")
        return item

    def load_instructions(self, skill_id: str, *, role_id: str) -> str:
        item = self.get(skill_id, role_id=role_id)
        path = (self.root / item.instruction_path).resolve()
        if self.root not in path.parents:
            raise SkillRegistryError("Skill instruction path escaped project root")
        return path.read_text(encoding="utf-8")

    def create_lock(self, skill_ids: list[str], *, role_id: str) -> dict[str, Any]:
        locked = []
        for skill_id in sorted(set(skill_ids)):
            item = self.get(skill_id, role_id=role_id)
            locked.append({"skillId": item.skill_id, "version": item.version, "digest": item.digest})
        return {"schemaVersion": "1.0.0", "roleId": role_id, "skills": locked}

    def verify_lock(self, lock: dict[str, Any]) -> bool:
        if lock.get("schemaVersion") != "1.0.0" or not isinstance(lock.get("skills"), list):
            return False
        role_id = lock.get("roleId")
        for expected in lock["skills"]:
            if not isinstance(expected, dict):
                return False
            try:
                current = self.get(str(expected.get("skillId")), role_id=role_id)
            except SkillRegistryError:
                return False
            if expected.get("version") != current.version or expected.get("digest") != current.digest:
                return False
        return True
