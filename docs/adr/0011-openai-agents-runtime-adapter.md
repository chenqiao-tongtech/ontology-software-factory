# ADR 0011: Use OpenAI Agents SDK behind a runtime adapter

- Status: Accepted for the first integration
- Date: 2026-10-27

## Context

The project already defines Agent roles, Skills, policies, workflow state and task events. A runtime is needed to execute real specialist agents, while the existing state machine should remain the system of record for workflow state.

## Decision

Wrap the OpenAI Agents SDK in `OpenAIAgentsRuntime`. Load role and Skill definitions from the repo, intersect role-declared tool IDs with an explicit runtime registry, reject plain-text output where a typed object is required, and default SDK tracing to disabled until reviewed.

Only three read/validation tools are registered. No arbitrary shell, source-tree write, repository merge, secret access or deployment tools are registered.

## Consequences

- Role and Skill assets influence live agent execution.
- The SDK is replaceable behind the adapter.
- Workflow persistence and business gates remain in the existing system.
- SDK version compatibility needs to be tested on dependency upgrades.
- Role declarations are not an authorization system; tool execution points still require authorization and audit.
