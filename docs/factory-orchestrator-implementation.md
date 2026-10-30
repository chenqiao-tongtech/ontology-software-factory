# Factory Orchestrator and Modular Ontology: implementation increment 4

**Date:** 2026-10-30  
**Status:** autonomous plan proposal through OpenAI Agents Runtime, deterministic intake, independent plan approval, dependency-aware Assignment dispatch, persisted Phase state, durable result projection and OpenAI Agent Harness Run-usage ledger are implemented. Enterprise identity, distributed scheduling and cross-Provider/Connector mediation remain pending.

## Delivered

### Factory Orchestrator foundation

- Registered `factory-orchestrator` as a bounded planner role in the existing team topology.
- Added the `factory-orchestration` Skill contract and operating instructions.
- Added a strict JSON Schema for `AgentPlan` and a sample plan.
- Added a typed Pydantic output model to the optional Agent Runtime model registry.
- Added a read-only tool allowlist. The role cannot dispatch tasks, mutate Workflow state, grant permissions, approve its own plan, publish ontology, merge protected branches or deploy production.
- Added deterministic validation for phase dependencies, cycles, Role/Skill registration, output entity types, assignment counts, parallelism and topology limits.

### Persistent plan intake

- Added a `factory_orchestrator_plans` SQLite table with immutable plan payload, canonical SHA-256 digest, plan ID uniqueness and Workflow Run association.
- Added `WorkflowEngine.submit_factory_orchestrator_plan()`: verifies the target Run, checks the plan Run ID, validates against the Run-pinned ontology binding, and persists the plan plus `factory.plan.submitted` event in one SQLite transaction.
- Repeated submission of the same `planId` and identical payload is idempotent. Reusing the ID with a different Run or payload is rejected.
- Added `POST /api/runs/{runId}/orchestrator-plan`; `GET /api/runs/{runId}` now includes `orchestratorPlans`.
- Added tests for valid persistence, Run/ontology mismatch, idempotent replay and plan-ID payload conflicts.

### Autonomous plan generation

- Added `FactoryOrchestratorService`, which invokes the locked `factory-orchestrator` Role and `factory-orchestration` Skill through the existing Agent Runtime.
- The service uses the Workflow Run's immutable ontology snapshot and Role/Skill lock. The model receives the saved requirement, acceptance guidance and bounded planning limits.
- The control plane replaces the model-supplied Plan ID, Workflow Run ID and ontology binding with trusted values before deterministic plan validation and persistence.
- Added `POST /api/runs/{runId}/orchestrator-plan/generate`. The endpoint requires the optional OpenAI Agents SDK runtime and a configured model/API key. It creates a proposal only; it does not dispatch Worker tasks.

### Independent plan approval

- Added `factory_plan_approvals` with one approval record per immutable Plan digest, including the submitter identity label. New plans start in `pending`; the submitter cannot approve or reject their own Plan.
- Added `WorkflowEngine.decide_factory_orchestrator_plan()` and `POST /api/runs/{runId}/orchestrator-plan/approval`. Approval/rejection decisions require a non-empty actor and reason, are written with the Plan digest to the Workflow event ledger, and enforce submitter/approver separation using normalized actor labels.
- Dispatcher fails closed when the approval record is missing, its digest does not match the Plan, or the decision is pending/rejected. Approval is required for every Plan, including low-risk proposals.
- The local console does not authenticate the supplied actor label. A production deployment must bind decisions to an authenticated human/policy principal and enforce separation of duties outside this local reference implementation.
- Added plan-generation, approval/rejection and approved-plan dispatch controls to `apps/agent-workflow-console/index.html`; the panel displays the selected plan's approval and persisted Phase statuses.

### Persisted Phase state

- Added `factory_plan_phases` with `pending`, `running`, `succeeded` and `failed` states, timestamps and error metadata.
- Dispatch records Phase start; the transactional Assignment result projector updates the Phase when all its Assignments reach terminal outcomes and appends `factory.phase.*` events.
- Run detail exposes `factoryPlanApprovals` and `factoryPlanPhases`. Phase dependency checks use persisted state; Worker retry/backoff remains managed by Task Runtime.
- Added `WorkflowEngine.retry_factory_orchestrator_phase()` and `POST /api/runs/{runId}/orchestrator-plan/retry-phase`. Only a failed Phase in an approved Plan can be retried; the operator must provide an independent actor label and reason. Phase attempts are capped at three.
- Plan cancellation propagation and multi-process scheduler coordination are not yet implemented.

### Assignment dispatch and Worker execution

- Added `FactoryPlanDispatcher` to instantiate plan Assignments as idempotent `agent.factory-assignment` Worker tasks.
- The dispatcher checks the Workflow Run binding, immutable Role/Skill lock, plan approval requirement, Phase dependency completion and `maxParallelAssignments` before enqueueing work. It rechecks the persisted plan digest and schema/role/Skill contract, verifies output classes against the Run-pinned ontology snapshot, and requires at least one tool-budget unit per Assignment.
- Added `FactoryAssignmentHandler`, which validates the pinned Role, selected Skill, Agent Task contract and assignment output entity types; invokes the Agent Runtime with only the assigned Skill instructions; and writes output artifacts, an Agent Result contract and SHA-256 evidence.
- Added `additional_role_ids` support to the Workflow Run Role/Skill lock builder. The real Agent console locks all registered team Roles at Run creation so later plan assignments cannot silently pick up changed Role/Skill definitions.
- Added `POST /api/runs/{runId}/orchestrator-plan/dispatch`. Run detail includes a derived `factoryPlanExecutions` view with Phase/Assignment status, task IDs, outputs and evidence references.
- Extended the transactional Worker Outbox to emit terminal Factory Assignment results. `WorkflowOutboxRelay` routes these events to `WorkflowEngine.apply_factory_assignment_event()`; the Workflow Inbox deduplicates deliveries.
- Added `factory_assignment_results` persistence and `factory.assignment.succeeded` / `factory.assignment.failed` / `factory.assignment.dead_letter` Workflow events. Event payloads retain identifiers, evidence types and artifact digests; result payloads and evidence descriptors are stored separately.
- Paused Workflow Runs defer result delivery; terminal Workflow Runs consume late results as ignored events without reviving the run.

### Harness Tool Gateway integration

- `OpenAIAgentsRuntime` now constructs a per-execution `ToolRegistry` and `HarnessRuntime` using trusted in-process handlers. Agent-visible tool functions call the Harness gateway; they no longer execute their handler body directly.
- Tool availability is the intersection of Role declarations, runtime tool implementations and `policies/tool-permissions.json`. ToolRegistry validates each input against `tools/registry.json` before invoking the trusted handler.
- The gateway applies per-Agent-task tool-call budgets, approval checks, the configured file Kill Switch and metadata-only audit records. Shared context fields are assembled under the Role context allowlist and included in the pinned Agent context.
- The gateway covers the tools exposed by the OpenAI Agents SDK adapter, including workspace tools when an isolated workspace is present. Other Agent providers and non-Agent connector execution paths are not yet routed through this gateway.
- Added a Workflow SQLite usage ledger for Run-level tool calls, context bytes, input tokens and output tokens. Tool-call reservations are checked transactionally across Agent executions; token usage is recorded from the OpenAI Agents SDK result usage object when supplied. Missing provider usage remains unknown.
- Added Tool permission policy version and SHA-256 digest to the immutable Workflow Run Role/Skill lock. A changed policy version or digest prevents further Agent execution under that old Run lock. Workflow Runs created before this lock field was introduced do not have a policy snapshot and fail closed at Agent initialization; create a new Run rather than silently upgrading its permissions.
- Per-Agent task tool-call limits remain in place; the AgentPlan Run-level `maxToolCalls` limit is enforced across Assignment executions. Default Run token limits are 100,000 input and 40,000 output tokens.
- Harness usage events and totals are exposed in Workflow Run detail. The default audit path is `.local-runs/harness-audit.jsonl`; `FACTORY_HARNESS_AUDIT` and `FACTORY_HARNESS_KILL_SWITCH` can override the audit and Kill Switch paths.
- Existing fixed-stage Agent Proposal workflow and its outbox/inbox path remain unchanged.

### Ontology module baseline

- Advanced the core ontology version to `1.1.0` and the operational extension version to `1.2.0`.
- Added the orchestration, Workflow Run, Tool/Connector, source-system and ontology lifecycle concepts.
- Added `ontology/module-manifest.json` and its JSON Schema.
- Added a validator that requires every canonical class and relation to be assigned to exactly one logical module, with no unknown references or invalid relation endpoints.

The module manifest is a logical partition over `ontology/software-factory-ontology.json`. It is intentionally not a second ontology definition store. The canonical JSON remains the only authoritative definition until a future migration creates separately versioned module files and a deterministic composition/publishing pipeline.

## Architecture decisions

- [ADR-0018: Factory Plan Approval and Persisted Phase State](adr/0018-factory-plan-approval-and-phase-state.md)
- [ADR-0019: Run-Level Harness Budget Ledger and Tool Policy Lock](adr/0019-harness-run-budget-and-policy-lock.md)

## Validation commands

```bash
make orchestrator-plan
make ontology-modules
make agent-contracts
make multi-agent
make ontology-consumers
make validate
make test
```

## Explicit implementation boundaries

The `factory-orchestrator` is now invoked through an explicit plan-generation API; it does not run automatically at Workflow Run creation. Every Plan requires a separate approval decision before dispatch. Phase state and Run-level Harness usage are persisted in the local SQLite store. The approval actor field is an audit label rather than an authenticated identity. Multi-process scheduling coordination, plan cancellation propagation, enterprise identity/PDP, Secret Broker, distributed budget coordination, model-cost pricing and mediation for non-OpenAI Agent/Connector execution paths remain pending. Plan generation, approval and dispatch remain separate operations.

The ontology module manifest is not yet a module package manager. It does not independently publish module releases, resolve external module dependencies, migrate instances or update a graph database. Existing ontology snapshots, digest approvals and consumer-impact analysis remain the operational governance mechanisms.

Automatic discovery remains candidate-only. Source cursor management, reliable incremental scans, complete-scan deletion detection and one-click promotion into the canonical ontology are not claimed as completed by this increment.
