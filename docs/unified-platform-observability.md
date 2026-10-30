# Unified Platform Observability

## Scope

The Factory Portal exposes a read-only aggregation endpoint at `GET /api/observability`. It combines:

- pipeline run records and evidence references under `.local-runs/`;
- local Portal Agent run state and runtime mode;
- Portal quality-run status;
- source synchronization history;
- ontology candidate and pending-change counts;
- recent governance events, with event payloads omitted.

The Portal overview renders the aggregate under **统一运行监控 · Platform Observability**.

## Real Agent Workflow / Worker store

The aggregate can also read the SQLite database used by `scripts/run_agent_workflow_console.py`. The default path is:

```
data/real-agent-workflow/agent_workflow.sqlite3
```

Override it with `FACTORY_AGENT_WORKFLOW_DB`. The Portal opens the database in SQLite read-only mode and reads only operational columns from `workflow_runs`, `workflow_events` and `worker_tasks`. It does not return workflow/task payload JSON, prompts, model responses, tool arguments, event payload JSON or error-message bodies.

The dashboard reports:
- real Workflow run counts and status distribution;
- recent run titles, IDs, step status and timestamps;
- Worker task counts and status distribution;
- sanitized workflow event headers.

A missing database is shown as **未连接**, not as zero successful runs. The runtime mode comes from the stored run payload when available; a workflow record alone is not proof that every stage completed a real model call. Inspect step-level runtime metadata and errors in the Agent Workflow Console when diagnosing model execution.

## Privacy and interpretation

The response deliberately excludes prompt text, model responses, credentials, raw tool arguments, raw scanner reports and event payloads. LLM usage records are sanitized by `JsonlUsageLedger`; cost is estimated only when an explicit model-rate configuration is supplied. Unknown model rates remain unknown rather than being guessed.

Agent runs are grouped by `runtimeMode`. In particular, `deterministic-fixture` and other fixture modes must not be interpreted as actual LLM executions. Pipeline run records and local Portal JSON state are separate data sources and are reported separately to avoid implying they are one transactional execution store.

## API example

```bash
curl http://127.0.0.1:8768/api/observability
```

Response sections:
- `summary`: pipeline run and quality-report aggregates;
- `llmUsage`: sanitized usage event counts and configured-rate cost estimates;
- `traceability`: run IDs, status, evidence paths and release eligibility;
- `platform.agentRuns`: local Agent run statuses, runtime modes and recent runs;
- `platform.qualityRuns`: local quality-run statuses;
- `platform.sourceSync`: local synchronization-history counts;
- `platform.ontology`: candidate and pending-change counts;
- `platform.recentEvents`: sanitized event headers only.

## Current limits

This is a local reference observability surface, not a production telemetry backend. It does not yet provide OpenTelemetry ingestion, distributed trace correlation across unrelated processes, metrics time-series storage, tenant isolation, alert routing, SLO evaluation, retention enforcement or tamper-evident audit storage. SQLite reads are local to the configured Agent Workflow database and do not constitute a remote telemetry collector. The 20-second Portal refresh is a UI polling interval, not a guaranteed event-delivery SLA.
