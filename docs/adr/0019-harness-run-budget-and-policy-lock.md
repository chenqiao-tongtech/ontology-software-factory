# ADR-0019: Run-Level Harness Budget Ledger and Tool Policy Lock

- **Status:** Accepted
- **Date:** 2026-10-30
- **Decision owners:** Software Factory Architecture
- **Related:** ADR-0006, ADR-0008, ADR-0010, ADR-0011, ADR-0013

## Context

A per-Agent in-memory tool budget resets when a new Assignment Agent starts and therefore cannot enforce a Workflow Run budget. Tool permission policy may also change while a Run is active, which can change the effective tool set unless the policy is pinned.

## Decision

1. Persist Run-level tool-call reservations, assembled context bytes, input tokens and output tokens in the Workflow SQLite database.
2. Reserve tool calls and context bytes in SQLite transactions before allowing the corresponding action. Actual model token usage is recorded after the provider response because the exact usage is not known before the call.
3. Read token usage from the OpenAI Agents SDK result usage object when present. Missing usage remains unknown; do not estimate or fabricate token counts.
4. Store usage events with Run ID, Task ID, event type, timestamp, provider/model metadata, policy version and policy digest. Do not store prompts, model responses, raw tool payloads or credentials in this ledger.
5. Include the Tool permission policy version and canonical SHA-256 digest in the immutable Workflow Run Runtime Contract Lock. Reject Agent execution if the current policy no longer matches the lock.
6. Retain the existing per-Agent task limits in addition to the Run-level budget. The local SQLite implementation is the single-node reference implementation.

## Consequences

- Tool-call budgets are shared across Agent Assignments within one Workflow Run and checked transactionally.
- Token usage is auditable when the provider returns it; an overrun is recorded before the execution is rejected.
- A policy change requires a new Workflow Run rather than silently changing permissions for an existing Run.
- Multi-node distributed budget coordination, enterprise PDP, Secret Broker, cross-Provider usage normalization and monetary cost pricing remain future work.
