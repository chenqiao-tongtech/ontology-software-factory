# Article 18 patch notes

## Additive paths

- `agents/roles/*.json`, `agents/role-catalog.json`, `agents/tool-catalog.json`, `agents/schemas/role-definition.schema.json`
- `skills/schemas/skill-definition.schema.json`, `skills/<skill-id>/skill.json`, `skills/<skill-id>/SKILL.md`
- `contracts/schemas/agent-task.schema.json`, `contracts/schemas/agent-result.schema.json`
- `policies/agent-permissions.json`, `policies/context-policy.json`, `policies/agent-permission-matrix.md`
- `examples/agent-handoff/*`
- `src/ontology_software_factory/agent_contracts.py`
- `scripts/validate_agent_contracts.py`
- `tests/test_agent_contracts.py`
- `docs/agent-roles-and-skills.md`, `docs/adr/0006-agent-roles-skills-context-contracts.md`, `docs/acceptance/agent-role-skill-checklist.md`
- `article/通往AI之桥_本体论系列18_公众号发布稿.md`

## Merge procedure

1. Commit or back up the current repository.
2. Copy the additive paths to the repository root.
3. If an `ontology_software_factory` Python package already exists, merge `agent_contracts.py` into its existing package rather than replacing `__init__.py` or other modules.
4. Check that `jsonschema>=4.21,<5` is present in the project's dependencies.
5. Optionally add `python scripts/validate_agent_contracts.py` to the existing `make validate` target; do not replace existing checks.
6. Run the validator and tests; review `git diff` before committing.

This patch deliberately avoids modifying the existing MVP scope file, Makefile, or global README to reduce merge conflicts. Add the Article 18 acceptance IDs to your existing checklist if you use one.
