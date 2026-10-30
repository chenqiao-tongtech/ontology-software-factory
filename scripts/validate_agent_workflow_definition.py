#!/usr/bin/env python3
"""Validate the Article 24 persistent Agent workflow definition."""
from __future__ import annotations
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))


def main() -> int:
    definition_path = ROOT / "workflows/definitions/agent-proposal-v1.json"
    schema_path = ROOT / "workflows/schemas/workflow-definition.schema.json"
    try:
        definition = json.loads(definition_path.read_text(encoding="utf-8"))
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        import jsonschema
        jsonschema.validate(definition, schema)
        from ontology_software_factory.workflow_engine import WorkflowEngine
        from ontology_software_factory.workflow_store import SQLiteWorkflowStore
        engine = WorkflowEngine(SQLiteWorkflowStore(":memory:"), definition)
        # Creating a disposable run verifies that every declared step is accepted
        # by the runtime and that the human-review gate is registered as a gate.
        run = engine.create_run("validator probe", requested_by="validator", environment="review")
        steps = run["steps"]
        if len(steps) != 6:
            raise ValueError(f"expected six steps including human review; got {len(steps)}")
        if steps[-1]["executionMode"] != "human" or not steps[-1]["requiresApproval"]:
            raise ValueError("last step must be an explicit human-approval gate")
    except Exception as exc:
        print(f"Agent workflow definition validation: FAIL ({type(exc).__name__}: {exc})", file=sys.stderr)
        return 1
    print("Agent workflow definition validation: PASS")
    print(f"Workflow: {definition['id']}@{definition['version']}; steps: {len(definition['steps'])}; approval gate: explicit")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
