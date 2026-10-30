# Acceptance checklist — Articles 22–24 real LLM / Agent workflow

## Offline / deterministic checks

- [ ] Provider tests use injected fake clients; no API key needed.
- [ ] Agent role tool grants are the intersection of role-declared tools and registered tools.
- [ ] Path allowlist denies traversal, secrets, arbitrary writes and shell execution.
- [ ] All structured agent outputs validate against Pydantic models.
- [ ] Proposed code is saved only in isolated artifacts and is never automatically executed or applied.
- [ ] Workflow step success/failure is projected through Outbox/Inbox idempotently.
- [ ] A security result `blocked` prevents the workflow from reaching the human approval gate.
- [ ] Human approval/rejection is explicit and recorded as a separate action.

## Live checks (requires credentials)

- [ ] `OPENAI_API_KEY` is supplied through environment or an approved secret manager.
- [ ] `OPENAI_MODEL` is enabled for the API project.
- [ ] `python scripts/check_llm_connection.py` completes against the real Responses API.
- [ ] One requirement analysis Agent returns a valid structured result from the real Agents SDK.
- [ ] The persistent console completes each worker/relay cycle and persists the workflow run.
- [ ] Raw prompts, customer secrets and API credentials are absent from operational logs.
- [ ] Token usage, latency, model ID, run IDs and evidence hashes can be correlated.

## Security / production readiness

- [ ] Add authentication and RBAC before exposing any console beyond localhost.
- [ ] Add rate/concurrency limits and cost budgets.
- [ ] Add data-classification and regional/privacy review for model-bound inputs.
- [ ] Run actual SAST/SCA and tests in a disposable sandbox.
- [ ] Require independent approval before applying diffs, merging or deploying.
