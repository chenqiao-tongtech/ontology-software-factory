# Article 21 — Workflow Execution Closed Loop

This extension closes the integration loop across the Article 19 workflow engine and Article 20 worker runtime.

## What's added

- `src/ontology_software_factory/integration.py`: workflow step dispatch, demo handler, transactional-outbox relay and at-least-once delivery.
- Updates to `task_runtime.py`: result-state and integration-outbox writes share the producer transaction.
- Updates to `workflow_store.py` / `workflow_engine.py`: workflow inbox deduplication, revision-guarded result projection, stale/late-attempt fencing.
- `scripts/run_integrated_console.py` and `apps/integrated-console/index.html`: local end-to-end demo console.
- `contracts/schemas/workflow-integration-event.schema.json`: versionable integration event contract.
- `tests/test_workflow_integration.py`: failure, duplicate delivery, retry, lease recovery and stale-result cases.
- Architecture Decision Record, operations docs, acceptance checklist and the Article 21 WeChat Markdown.

## Quick start

```bash
python -m unittest discover -s tests -v
python scripts/run_integrated_console.py --host 127.0.0.1 --port 8767
```

Open `http://127.0.0.1:8767`. The registered handler is demo-only and creates `demo://` evidence; no real LLM, CI, repository write or deployment is enabled. The console has no authentication, so keep the service bound to localhost.

## Semantics

The producer transaction writes task terminal status + task event + outbox. The consumer transaction writes Workflow Run + workflow event + inbox dedupe record. Between them, the relay offers at-least-once delivery. The solution does not claim end-to-end exactly-once execution for external side effects; those require business idempotency keys and reconciliation.
