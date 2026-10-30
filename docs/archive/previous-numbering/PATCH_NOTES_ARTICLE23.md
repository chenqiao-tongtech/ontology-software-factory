# Incremental patch notes · Article 23

Baseline: Articles 21 + 22.

Adds: typed Pydantic outputs in `agent_models.py`, `OpenAIAgentsRuntime` in `agent_runtime.py`, a direct one-Agent demo script, policy tests, Agent Runtime guide, ADR 0011, acceptance checklist, and Article 23 Markdown.

Prerequisite: merge `docs/dependency-extras.toml` into your existing project metadata if not yet done, then install the `agent-runtime` extra: `python -m pip install -e '.[agent-runtime]'`. Current official SDK release notes specify `openai>=3.0.0,<4` and this bundle tracks `openai-agents>=0.21.0,<1`.

Tool policy: Only read/validation tools (`documents.read`, `catalog.read`, `contract.validate`) are registered. The role JSON can declare other tools but they are unavailable unless separately implemented and reviewed. Never treat role JSON as authorization on its own.

Validation: `PYTHONPATH=src python -m unittest tests.test_agent_runtime_policy -v`. The actual SDK/API run requires a key, network, and an enabled model.
