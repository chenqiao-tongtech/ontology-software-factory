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

This is a local reference observability surface, not a production telemetry backend. It does not yet provide OpenTelemetry ingestion, distributed trace correlation across processes, metrics time-series storage, tenant isolation, alert routing, SLO evaluation, retention enforcement or tamper-evident audit storage. The 20-second Portal refresh is a UI polling interval, not a guaranteed event-delivery SLA.
