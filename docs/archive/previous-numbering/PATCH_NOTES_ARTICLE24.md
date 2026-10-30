# Incremental patch notes · Article 24

Baseline: Articles 21 + 22 + 23.

Adds: the five-stage `SoftwareFactoryPipeline`, isolated proposed-file output, a quick multi-Agent console, persistent Workflow → Worker → Outbox/Inbox runtime and console, definition validator, integration tests, ADRs 0012–0013, acceptance checklists, runtime docs/data directory docs and Article 24 Markdown.

The pipeline writes only under `data/agent-pipeline/runs/<run_id>/`; it refuses path traversal, duplicate paths, oversized or unsupported proposals, and a small set of secret-like patterns. These checks are guardrails, not SAST/DLP. Proposed code is never executed, applied to the source tree, committed, merged or deployed.

Validation: `PYTHONPATH=src python -m unittest tests.test_software_factory_pipeline -v`. To use real Agents SDK, install the `agent-runtime` extra and configure environment credentials.

Workflow schema: the incremental patch also extends `workflows/schemas/workflow-definition.schema.json` with `artifact-write`, which distinguishes writes to the isolated artifact workspace from writes to the checked-out source repository. Review this additive enum change when merging.

Run the real persisted workflow using `python scripts/run_agent_workflow_console.py --host 127.0.0.1 --port 8769`. The UI intentionally requires manual dispatch/worker/relay steps to keep execution inspectable. This runner requires the optional Agents SDK and real model credentials for model-powered stages.
