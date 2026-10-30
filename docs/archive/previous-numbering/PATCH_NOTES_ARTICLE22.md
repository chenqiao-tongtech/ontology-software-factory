# Incremental patch notes · Article 22

Baseline: Article 21 project.

Adds: `llm_provider.py`, the real connectivity-check script, fake-client unit tests, JSON Schema example, `.env.example`, LLM guide and ADR 0010, plus the Article 22 Markdown.

Dependency metadata: the full reference project includes optional extras for `llm` and `agent-runtime`. To avoid overwriting a customized `pyproject.toml` in the destination repository, the incremental patch provides `docs/dependency-extras.toml`; manually merge those two entries into the existing `[project.optional-dependencies]` block. The current official Agents SDK release notes specify `openai>=3.0.0,<4`; the agent extra uses `openai-agents>=0.21.0,<1` plus Pydantic v2. Do not copy actual API keys into `.env.example`.

Validation: run `PYTHONPATH=src python -m unittest tests.test_llm_provider -v`. The dependency range reflects the current official Agents SDK release line. The live connection check requires credentials, account access to the selected model, and network access.
