# Article 23 · Real Agent Runtime

Adds the optional OpenAI Agents SDK adapter with role/Skill loading, Pydantic typed outputs and tool allowlisting.

```bash
# Merge dependency extras from docs/dependency-extras.toml if not already present.
python -m pip install -e '.[agent-runtime]'
export OPENAI_API_KEY='...'
export OPENAI_MODEL='gpt-6.1-sol'  # or a model enabled for your API project
export AGENT_TRACE_ENABLED=false
python scripts/run_requirement_agent.py --requirement 'Define a health endpoint for a Python service'
```

Only `documents.read`, `catalog.read`, and `contract.validate` are registered. No shell, arbitrary source-tree write, secret read, protected-branch merge or deployment tools are included. SDK tracing is disabled by default.
