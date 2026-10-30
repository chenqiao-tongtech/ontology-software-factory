# ADR-0018: Factory Plan Approval and Persisted Phase State

- **Status:** Accepted
- **Date:** 2026-10-30
- **Decision owners:** Software Factory Architecture
- **Related:** ADR-0003, ADR-0007, ADR-0008, ADR-0009, ADR-0013, ADR-0016

## Context

The Factory Orchestrator can propose a structured AgentPlan, while the deterministic control plane validates and persists it. A plan proposal is not authorization to create Worker tasks. Approval must be independently recorded and bound to the exact immutable plan. Phase progress also needs a durable source of truth so that a completed Worker task cannot unblock downstream work before its result has been accepted by the Workflow Inbox.

## Decision

1. Invoke the Orchestrator through an explicit plan-generation API. Generation, approval and dispatch remain separate operations.
2. Persist one approval record per Plan ID and canonical SHA-256 digest. New plans enter `pending`; only `approved` plans can be dispatched.
3. Record the plan submitter label and reject an approval/rejection decision from the same submitter. Every decision requires a non-empty actor label and reason and is written to the Workflow event ledger.
4. Treat actor labels as audit metadata only. The local console does not authenticate them; production must bind approval decisions to an authenticated identity/policy principal and enforce separation of duties.
5. Persist Phase states as `pending`, `running`, `succeeded` or `failed`, plus an attempt number. Phase start is recorded when work is enqueued; terminal state is updated transactionally with the Assignment result and Workflow event projection.
6. Use persisted Phase state, not Worker queue status alone, to gate downstream Phase dispatch. A Worker completion that has not passed through the Workflow Inbox does not satisfy a dependency.
7. Allow an independent operator to retry a failed Phase up to three Phase attempts. A retry gets a new idempotency key and isolated artifact directory; results from a superseded attempt are recorded as ignored and cannot mutate the current Phase.

## Consequences

- Plan generation cannot silently start execution.
- Approval is tamper-evident through the Plan digest and Workflow event history.
- Rejected or pending plans fail closed at dispatch.
- Phase dependency evaluation has a durable Workflow-owned source of truth.
- Plan cancellation propagation, multi-process scheduling and authenticated enterprise approval remain future work.
