# Article 19 patch notes — workflow orchestration and console

## Intended merge model

This is an additive patch for the existing `ontology-software-factory` repository. It does not replace the repository-level `README.md`, `pyproject.toml`, `Makefile`, package `__init__.py`, or any existing Agent/Skill contracts from Article 18.

## New paths

- `workflows/definitions/software-delivery-v1.json`
- `workflows/definitions/README.md`
- `workflows/schemas/workflow-definition.schema.json`
- `workflows/schemas/workflow-run.schema.json`
- `src/ontology_software_factory/workflow_engine.py`
- `src/ontology_software_factory/workflow_store.py`
- `apps/workflow-console/index.html`
- `scripts/validate_workflow_definition.py`
- `scripts/run_workflow_console.py`
- `tests/test_workflow_engine.py`
- `docs/workflow-orchestration.md`
- `docs/adr/0007-workflow-state-machine-and-console.md`
- `docs/acceptance/workflow-runtime-checklist.md`
- `examples/workflow-runs/README.md`
- `data/workflow-console/.gitignore`, `data/workflow-console/README.md`
- `article/通往AI之桥_软件工厂工程实现线19_公众号发布稿.md`
- `README_ARTICLE19.md`

## Merge notes

1. Merge additive source files into the existing Python package; do not overwrite `src/ontology_software_factory/__init__.py`.
2. The console launcher assumes the existing package layout uses `src/ontology_software_factory/`. Adjust only the import bootstrap if the repository structure differs.
3. This add-on uses Python standard library only. Article 18's `jsonschema` dependency remains needed for its own validator, but not for the Article 19 validator/console.
4. Run the workflow validator and all tests after merge. If the repository already has a workflow model, reconcile identifiers and fields instead of maintaining two competing definitions.
5. Default binding is localhost. Do not expose the demo server to any network; it has no authentication, RBAC, or CSRF protection.
6. `data/workflow-console/workflow_console.sqlite3` is runtime state and should not be committed.

## Validation boundary

The included state machine enforces status transitions and persistence for demonstration purposes. It does not execute LLMs, dispatch real tasks to workers, enforce production IAM, or execute rollback. Production needs an authorized worker boundary, durable scheduling, an outbox or equivalent reliable dispatch, idempotency, timeouts, observability, and human identity integration.
