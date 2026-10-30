# Article 24 · Multi-Agent Pipeline and Persistent Workflow

Adds five typed Agent stages (requirements, architecture, implementation proposal, test strategy, security review), isolated proposed files, a fast one-shot console, and a persistent Workflow → Worker → Outbox/Inbox console with a human approval gate.

```bash
python -m pip install -e '.[agent-runtime]'
export OPENAI_API_KEY='...'
export OPENAI_MODEL='gpt-6.1-sol'  # or a model enabled for your API project
export AGENT_TRACE_ENABLED=false

# Fast vertical slice
python scripts/run_ai_runtime_console.py --host 127.0.0.1 --port 8768

# Persistent stage-by-stage Workflow/Worker/outbox/inbox loop
python scripts/run_agent_workflow_console.py --host 127.0.0.1 --port 8769
```

The persistent console stores its SQLite run state under `data/real-agent-workflow/` and generated candidates under its ignored artifact directory. Model output is a proposal only: files are not executed or applied to the repository; security Agent output is not a substitute for SAST/SCA or human review.

Offline tests use injected fake runtime objects. A real end-to-end run requires an API key, network access, a model enabled for the project, and API quota. The console binds to localhost by default and must not be exposed publicly without authentication/authorization.
