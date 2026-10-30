# Factory Orchestrator and Modular Ontology: implementation increment 3

**Date:** 2026-10-30  
**Status:** validated plan intake, dependency-aware Assignment dispatch and Agent Worker execution are implemented; durable Workflow-level result projection and Harness-wide tool mediation remain pending.

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

The `factory-orchestrator` Agent Role is not yet automatically invoked to produce a plan. A submitted plan can now instantiate Assignment Worker tasks through an explicit dispatch API. The dispatcher derives Phase progress from Worker task records; this progress is not yet a separate Workflow Engine state machine, and Assignment result events are not yet projected into the Workflow event ledger. Multi-process scheduling coordination, automated plan generation, independent approval records and Harness-wide tool-call mediation remain pending. Plan submission is a recorded planning artifact; it is not an approval or authorization to execute.

The ontology module manifest is not yet a module package manager. It does not independently publish module releases, resolve external module dependencies, migrate instances or update a graph database. Existing ontology snapshots, digest approvals and consumer-impact analysis remain the operational governance mechanisms.

Automatic discovery remains candidate-only. Source cursor management, reliable incremental scans, complete-scan deletion detection and one-click promotion into the canonical ontology are not claimed as completed by this increment.
