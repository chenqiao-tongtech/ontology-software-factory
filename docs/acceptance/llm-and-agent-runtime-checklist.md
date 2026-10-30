# Acceptance checklist: LLM provider and Agent Runtime

- [ ] `OPENAI_API_KEY` is present in the process environment and is never written to Git.
- [ ] A credentialed environment runs `scripts/check_llm_connection.py` successfully against an enabled model.
- [ ] Local tests pass without network access.
- [ ] Timeouts, retryable errors and deterministic validation errors are classified as expected.
- [ ] Structured model response is validated against JSON Schema before being returned.
- [ ] Role declarations are intersected with a bounded tool registry.
- [ ] Path traversal and access to `.env`/outside-project paths are rejected.
- [ ] SDK tracing remains disabled until data flow and access policy are reviewed.
- [ ] No source-write, shell, protected merge or production deploy tools exist in the MVP registry.
