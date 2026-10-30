# Article 19 add-on: workflow state machine and runtime console

This add-on follows Article 18 (Agent Roles & Skills). It adds a seven-step software delivery workflow definition, a deterministic state machine, SQLite persistence and event history, an interactive browser console, tests, ADR, and acceptance guidance.

## Quick start

Python 3.11+; no third-party packages required for this add-on:

```bash
python scripts/validate_workflow_definition.py
python -m unittest discover -s tests -v
python scripts/run_workflow_console.py --host 127.0.0.1 --port 8765
```

Open `http://127.0.0.1:8765`. If you have merged Article 18 and Article 19 into your existing project, run from the project root. The default database is `data/workflow-console/workflow_console.sqlite3`.

## What the console does

- Lists persisted workflow runs and filters by status.
- Shows node progression, active gate, current attempt and evidence placeholders.
- Supports demo actions: complete/fail the current node, retry an eligible failure, approve/reject the human gate, pause/resume and cancel.
- Persists run state and event records in SQLite; optimistic revision checking rejects stale concurrent updates.

The browser console does not execute real agents, test commands, CI/CD or production deployment. This is a state-machine/UI prototype, not a production orchestrator.

## New files

See `PATCH_NOTES_ARTICLE19.md` for an additive merge map, `docs/workflow-orchestration.md` for the API/state model, and `docs/acceptance/workflow-runtime-checklist.md` for acceptance and production hardening items.
