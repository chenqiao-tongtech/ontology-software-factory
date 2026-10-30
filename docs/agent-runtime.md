# Agent Runtime Adapter

## Scope

The optional `agent-runtime` extra uses the OpenAI Agents SDK for typed role execution. It does not replace the project's Workflow Engine, task queue, event ledger or outbox/inbox integration.

## Install

```bash
python -m pip install -e '.[agent-runtime]'
export OPENAI_API_KEY='...'
export OPENAI_MODEL='a model enabled for your account'
export AGENT_TRACE_ENABLED=false
```

## Execution policy

1. Load a role from `agents/roles/<role-id>.json`.
2. Load the assigned `skills/<skill-id>/SKILL.md` contents as agent instructions.
3. Build effective tools as declared role tools intersected with the tools actually registered in this runtime, excluding globally denied actions.
4. Require the role's registered Pydantic output model.
5. Return a JSON-compatible object and sanitized runtime metadata to the orchestrator.

The only tools registered in this MVP are `documents.read`, `catalog.read`, and `contract.validate`. `documents.read` allows only paths under `docs/`, `skills/`, `workflows/`, `agents/`, `contracts/`, and `policies/`; path traversal, absolute paths, paths outside the project root, and oversize files are rejected. There is no shell, arbitrary file write, secret read, protected branch merge, or production deployment tool.

## Observability and privacy

SDK tracing defaults to disabled. After review of data flows, operators may explicitly set `AGENT_TRACE_ENABLED=true`. This flag is not a substitute for access control, retention policy or sensitive-data minimization.

## Output models

The pipeline recognizes these typed outputs: `RequirementBrief`, `ArchitecturePlan`, `ImplementationPlan`, `TestStrategy`, and `SecurityReview`. Typed shape is necessary but not sufficient: business truth, source-code correctness and release readiness need independent checks.
