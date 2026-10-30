# Workflow Definitions

The JSON files in this folder describe workflow semantics, not worker implementations. `software-delivery-v1.json` is a linear seven-step demonstration with an explicit human release-approval gate.

Run `python scripts/validate_workflow_definition.py` to validate required fields, unique step IDs, declared dependencies, and DAG acyclicity. A production workflow should also pin the exact versions of role, Skill, output Schema and policy references used by each step.
