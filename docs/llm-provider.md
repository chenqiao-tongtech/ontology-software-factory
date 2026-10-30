# LLM Provider Adapter

## Purpose

`llm_provider.py` provides a provider-neutral request model and an OpenAI Responses API implementation. The adapter owns timeout, bounded retry, structured-response validation, latency/usage metadata and sanitized logs. It does not own workflow transitions or business authorization.

## Install and configure

```bash
python -m pip install -e '.[llm]'
export OPENAI_API_KEY='...'
export OPENAI_MODEL='a model enabled for your account'
python scripts/check_llm_connection.py
```

The example currently defaults to `gpt-6.1-sol`, a current model listed in the official API model catalog as of 2026-10-27. The default is configurable and may not be enabled for every account. Set `OPENAI_MODEL` to a model available in your project. Keep credentials out of the repo and logs.

## Retry policy

- Retry candidates: network/connection/timeout errors, 408, 409, 429 and 5xx status codes.
- Do not retry deterministic argument, authentication/authorization, JSON parsing or schema-validation errors automatically.
- Maximum configured retries is capped in code; backoff uses jitter.
- The official SDK internal retries are disabled for this adapter, to avoid accidental multiplicative retries.
- For operations with side effects, use a business idempotency key independently of LLM retry logic.

## Structured output

`generate_structured()` passes strict JSON Schema formatting to Responses API and validates the returned JSON locally with `jsonschema`. Structural validity is not semantic correctness; downstream domain and ontology checks remain necessary.

## Data handling

Logs include provider, model, response ID, latency, token usage and attempt number. They omit API keys and full prompts. `store=False` is set for the sample Responses request; this is not a universal compliance statement. Review current product policies, account settings, regional rules and data retention before sending sensitive payloads.
