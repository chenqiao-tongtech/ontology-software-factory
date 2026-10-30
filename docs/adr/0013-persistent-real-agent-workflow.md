# ADR 0013: Persisted workflow for real Agent execution

- Status: Accepted for the MVP
- Context: Articles 22–23 introduce a real LLM provider adapter and a typed Agent runtime. A direct sequential Python pipeline is useful for a first vertical slice, but by itself it is not durable across process failure and does not exercise the existing Worker/Outbox/Inbox path.
- Decision: Use the existing Workflow Engine, SQLite task store and Outbox/Inbox integration to dispatch each Agent stage as a task. Store typed stage outputs and evidence in an isolated artifact workspace. Leave the final approval as a human-controlled workflow action. A security result marked `blocked` raises a permanent task failure, which projects a blocked workflow result.
- Consequences: The operator can inspect a stage-by-stage persisted workflow and retry eligible transient errors. The MVP still uses SQLite, a manually stepped local console and model-assisted security review; it is not a production-grade autonomous coding/deployment factory.
- Safety boundaries: no arbitrary shell, no write to source checkout, no automatic test execution, merge or deploy. API key is only read from the process environment. SDK tracing defaults off.
