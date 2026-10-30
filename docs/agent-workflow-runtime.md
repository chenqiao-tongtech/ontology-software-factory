# Persistent real-Agent workflow runtime

## What this adds

`workflows/definitions/agent-proposal-v1.json` defines a durable sequence of Requirement Analyst, Solution Architect, Implementation Proposal, Test Strategy and Security Review nodes, followed by a human-review gate. `AgentWorkflowStepHandler` connects those nodes to the pre-existing SQLite Workflow Engine, Worker task store, Outbox Relay and Workflow Inbox.

Each model stage writes its typed JSON output and evidence under `data/real-agent-workflow/artifacts/<run-id>/...`. Proposed file contents are placed beneath a separate `proposed_changes/` folder. The checked-out source tree is never modified, and generated source is never executed. The security-review step can block the workflow before the approval gate.

## Install

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[agent-runtime]'
cp .env.example .env  # optional reference only; export environment values yourself
export OPENAI_API_KEY='your-key-from-a-secure-secret store'
export OPENAI_MODEL='gpt-6.1-sol'  # choose a model available to your API project
export AGENT_TRACE_ENABLED=false
```

Do not put real keys into `.env.example`, source control, browser local storage, or logs. This lightweight MVP does not load `.env` automatically; export the variables in your shell or use your secret manager.

## Run the persistent end-to-end console

```bash
python scripts/run_agent_workflow_console.py --host 127.0.0.1 --port 8769
```

Visit `http://127.0.0.1:8769`. Create a run from a software requirement, repeatedly dispatch the current node, run one Worker task, and drain the Outbox Relay. Repeat until the workflow reaches `needs_human_review`, `blocked`, or a terminal state. Use the explicit approval action only after reviewing all stage outputs. The human gate is not runnable as a Worker task.

This is intentionally manually stepped rather than an autonomous daemon so that the operator can inspect each state transition while validating the first live integration. The task dispatch, worker results, Outbox/Inbox projection and Workflow state are persisted in SQLite.

## Verification

Offline test suite:

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
python scripts/validate_agent_contracts.py
python scripts/validate_workflow_definition.py
python scripts/validate_agent_workflow_definition.py
```

Live API smoke test:

```bash
python scripts/check_llm_connection.py
```

The offline suite uses fake model/runtime objects and makes no external API calls. Live verification requires a valid `OPENAI_API_KEY`, outbound network access, API project permissions, and a selected model that is enabled for that project.

## Explicit limitations

- The browser server binds to loopback by default and has no user authentication. Do not expose it publicly.
- Model-assisted security review is not SAST, SCA or an independent security audit.
- Generated code is a proposal only: no shell, arbitrary source-tree write, test execution, protected merge or deployment tool is registered.
- A `demo` or `artifact://` evidence record documents what this MVP produced; it does not imply an external system attested to the artifact.
- For production, add authentication and authorization, tenant isolation, secret management, data retention controls, worker concurrency/rate limits, a dedicated artifact store, SAST/SCA, isolated CI, independent review and operational alerting.
