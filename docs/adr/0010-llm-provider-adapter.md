# ADR 0010: Add a provider-neutral LLM adapter

- Status: Accepted for the reference implementation
- Date: 2026-10-27

## Context

Agent and workflow code needs real model inference, but provider-specific API calls should not spread through roles, Skills and task handlers. Tests must stay network-free, and retries, timeouts, data minimization and usage telemetry need one policy boundary.

## Decision

Add `LLMProvider` and `OpenAIResponsesProvider` in `llm_provider.py`. Inject a client for deterministic tests; read production credentials from environment; disable SDK internal retries and apply a bounded retry policy in the adapter. Use strict JSON Schema plus local validation for structured outputs. Logs omit prompt bodies and credentials.

## Consequences

- One place to tune provider configuration and telemetry.
- Unit tests do not require credentials or network access.
- Provider-specific features remain behind an adapter; multi-provider support can add implementations later.
- Local schema validation must not be mistaken for semantic validation.
- Actual endpoint connectivity must be checked in a credentialed environment.
