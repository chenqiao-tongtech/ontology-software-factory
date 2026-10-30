# Article 20 — Worker Runtime & Reliable Task Dispatch

This bundle adds an SQLite-backed task queue and Worker runtime on top of the Article 18/19 reference bundle.

## New files

- `src/ontology_software_factory/task_runtime.py`: enqueue, deduplication, lease claiming, retry/backoff, evidence validation, result and event persistence.
- `scripts/run_worker_console.py`: localhost-only demo API and browser console.
- `apps/worker-console/index.html`: task queue UI, task details, evidence and event history.
- `contracts/schemas/worker-task.schema.json`: task envelope schema.
- `tests/test_task_runtime.py`: idempotency, lease, retry, evidence, timeout and workflow dispatch tests.
- `docs/worker-runtime-and-reliable-dispatch.md`: architecture, boundaries and integration instructions.

## Quick start

```bash
python -m unittest discover -s tests -v
python scripts/run_worker_console.py --host 127.0.0.1 --port 8766
```

Open `http://127.0.0.1:8766`. Only `demo.echo` and `demo.generate-evidence` are registered. Evidence uses `demo://` and is not a real release artifact.

This runtime is a single-host reference implementation, not a production distributed queue. See `PATCH_NOTES_ARTICLE20.md` for safe merge instructions and `docs/worker-runtime-and-reliable-dispatch.md` for the exact guarantees and limitations.
