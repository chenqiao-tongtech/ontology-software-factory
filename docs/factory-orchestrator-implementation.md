# Factory Orchestrator and Modular Ontology: implementation increment 3

**Date:** 2026-10-30  
**Status:** validated plan intake, dependency-aware Assignment dispatch, Agent Worker execution and durable Workflow event projection are implemented; independent approval workflow and Harness-wide tool mediation remain pending.

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

### Assignment dispatch and Worker execution

- Added `FactoryPlanDispatcher` to instantiate plan Assignments as idempotent `agent.factory-assignment` Worker tasks.
- The dispatcher checks the Workflow Run binding, immutable Role/Skill lock, plan approval requirement, Phase dependency completion and `maxParallelAssignments` before enqueueing work.
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
- Current budgets are in-memory and scoped to an Agent execution. Actual provider token usage is not yet sampled into Harness, and budget usage is not shared across multiple Assignments in one Workflow Run. The default audit path is `.local-runs/harness-audit.jsonl`; `FACTORY_HARNESS_AUDIT` and `FACTORY_HARNESS_KILL_SWITCH` can override the audit and Kill Switch paths.
- High/critical plans or any plan with `requiresHumanApproval=true` are not dispatched by this endpoint. A separate independent approval workflow is still required before such plans can execute.
- Existing fixed-stage Agent Proposal workflow and its outbox/inbox path remain unchanged.

### Ontology module baseline

- Advanced the core ontology version to `1.1.0` and the operational extension version to `1.2.0`.
- Added the orchestration, Workflow Run, Tool/Connector, source-system and ontology lifecycle concepts.
- Added `ontology/module-manifest.json` and its JSON Schema.
- Added a validator that requires every canonical class and relation to be assigned to exactly one logical module, with no unknown references or invalid relation endpoints.

The module manifest is a logical partition over `ontology/software-factory-ontology.json`. It is intentionally not a second ontology definition store. The canonical JSON remains the only authoritative definition until a future migration creates separately versioned module files and a deterministic composition/publishing pipeline.

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

The `factory-orchestrator` Agent Role is not yet automatically invoked to produce a plan. A submitted plan can now instantiate Assignment Worker tasks through an explicit dispatch API. The dispatcher derives Phase progress from Worker task records; Phase state is not yet an independently persisted Workflow state machine. Multi-process scheduling coordination, automated plan generation, independent approval records, cross-Agent persistent budgets, actual model token accounting and mediation for non-OpenAI Agent/connector execution paths remain pending. Plan submission is a recorded planning artifact; it is not an approval or authorization to execute.

The ontology module manifest is not yet a module package manager. It does not independently publish module releases, resolve external module dependencies, migrate instances or update a graph database. Existing ontology snapshots, digest approvals and consumer-impact analysis remain the operational governance mechanisms.

Automatic discovery remains candidate-only. Source cursor management, reliable incremental scans, complete-scan deletion detection and one-click promotion into the canonical ontology are not claimed as completed by this increment.
