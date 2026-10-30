"""JSON Schema validation for software-factory entity documents."""
from __future__ import annotations
import json
from pathlib import Path
from typing import Any
from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SCHEMA = ROOT / "contracts" / "schemas" / "entities.schema.json"


def load_entity_schema(path: Path = DEFAULT_SCHEMA) -> dict[str, Any]:
    """Load and meta-validate the JSON Schema contract."""
    with path.open("r", encoding="utf-8") as stream:
        schema = json.load(stream)
    Draft202012Validator.check_schema(schema)
    return schema


def validate_entity(entity: dict[str, Any], schema: dict[str, Any] | None = None) -> list[str]:
    """Return structural contract errors for one entity. Empty means valid shape."""
    loaded_schema = schema if schema is not None else load_entity_schema()
    target_schema = loaded_schema
    entity_type = entity.get("entityType") if isinstance(entity, dict) else None
    if isinstance(entity_type, str) and entity_type in loaded_schema.get("$defs", {}):
        # Restrict the union to the declared type so errors point to useful fields,
        # rather than only reporting a generic oneOf failure.
        target_schema = dict(loaded_schema)
        target_schema["oneOf"] = [{"$ref": f"#/$defs/{entity_type}"}]
    validator = Draft202012Validator(target_schema, format_checker=FormatChecker())
    errors = []

    def flatten(error):
        if error.context and error.validator in ("oneOf", "anyOf", "allOf"):
            for child in error.context:
                yield from flatten(child)
        else:
            yield error

    for top_error in validator.iter_errors(entity):
        for error in flatten(top_error):
            path = ".".join(str(part) for part in error.absolute_path) or "$"
            errors.append(f"{path}: {error.message}")
    return sorted(set(errors))
