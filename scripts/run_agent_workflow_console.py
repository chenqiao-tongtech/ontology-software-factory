#!/usr/bin/env python3
"""Run the real Agent steps through persistent Workflow -> Worker -> Outbox -> Inbox."""
from __future__ import annotations

import json
import os
import re
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from ontology_software_factory.agent_runtime import OpenAIAgentsRuntime  # noqa: E402
from ontology_software_factory.agent_workflow import AgentWorkflowStepHandler  # noqa: E402
from ontology_software_factory.integration import WorkflowOutboxRelay, enqueue_workflow_step  # noqa: E402
from ontology_software_factory.task_runtime import IdempotencyConflict, SQLiteTaskStore, TaskWorker  # noqa: E402
from ontology_software_factory.workflow_engine import WorkflowEngine, WorkflowError  # noqa: E402
from ontology_software_factory.workflow_store import SQLiteWorkflowStore  # noqa: E402


def load_definition() -> dict:
    return json.loads((ROOT / "workflows/definitions/agent-proposal-v1.json").read_text(encoding="utf-8"))


def safe_id(value: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,100}", value))


class AgentWorkflowConsoleHandler(BaseHTTPRequestHandler):
    engine: WorkflowEngine
    workflow_store: SQLiteWorkflowStore
    task_store: SQLiteTaskStore
    worker: TaskWorker
    relay: WorkflowOutboxRelay
    static_path: Path
    input_root: Path

    def _json(self, status: int, value: dict) -> None:
        body = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length < 1 or length > 40_000:
            raise ValueError("request body too large or empty")
        value = json.loads(self.rfile.read(length).decode("utf-8"))
        if not isinstance(value, dict):
            raise ValueError("request body must be a JSON object")
        return value

    def _run_input(self, run_id: str) -> dict:
        if not safe_id(run_id):
            raise ValueError("invalid run ID")
        path = (self.input_root / f"{run_id}.json").resolve()
        if self.input_root.resolve() not in path.parents or not path.is_file():
            raise FileNotFoundError("workflow input was not found")
        return json.loads(path.read_text(encoding="utf-8"))

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/api/status":
            self._json(200, {
                "mode": "real-agent-workflow",
                "api_key_configured": bool(os.getenv("OPENAI_API_KEY")),
                "model": os.getenv("OPENAI_MODEL", "gpt-6.1-sol"),
                "runs": len(self.engine.list_runs()),
                "tasks": len(self.task_store.list_tasks(1000)),
                "outbox_pending": sum(1 for item in self.task_store.list_outbox(1000) if item.get("status") != "delivered"),
                "sdk_tracing_enabled": os.getenv("AGENT_TRACE_ENABLED", "false").lower() in {"1", "true", "yes"},
            })
            return
        if path == "/api/runs":
            self._json(200, {"runs": self.engine.list_runs()})
            return
        if path.startswith("/api/runs/"):
            run_id = unquote(path.removeprefix("/api/runs/"))
            try:
                self._json(200, self.engine.get_run_detail(run_id))
            except WorkflowError as exc:
                self._json(exc.status_code, {"error": str(exc)})
            return
        if path == "/api/tasks":
            self._json(200, {"tasks": self.task_store.list_tasks(250)})
            return
        if path == "/api/outbox":
            self._json(200, {"events": self.task_store.list_outbox(250)})
            return
        if path in {"/", "/index.html"}:
            data = self.static_path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)
            return
        self._json(404, {"error": "not_found"})

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        try:
            body = self._read_body()
            if path == "/api/runs":
                requirement = body.get("requirement")
                if not isinstance(requirement, str) or not requirement.strip() or len(requirement) > 30_000:
                    self._json(400, {"error": "requirement must be non-empty and <= 30000 characters"})
                    return
                run = self.engine.create_run(str(body.get("title", "真实多 Agent 软件提案")),
                                             str(body.get("requestedBy", "local-operator")), "review")
                self.input_root.mkdir(parents=True, exist_ok=True)
                target = self.input_root / f"{run['id']}.json"
                target.write_text(json.dumps({"requirement": requirement.strip()}, ensure_ascii=False, indent=2), encoding="utf-8")
                self._json(201, {"run": run})
                return
            if path.endswith("/dispatch") and path.startswith("/api/runs/"):
                run_id = unquote(path[len("/api/runs/"):-len("/dispatch")].strip("/"))
                run = self.engine.get_run(run_id)
                step = next((item for item in run["steps"] if item["id"] == run.get("currentStepId")), None)
                if not step or step.get("requiresApproval") or step.get("executionMode") == "human":
                    self._json(409, {"error": "current step is not a Worker-dispatchable Agent step"})
                    return
                user_input = self._run_input(run_id)
                task, duplicate = enqueue_workflow_step(
                    self.task_store, run, step, user_input,
                    task_type=f"agent.workflow-step.{step['id']}",
                    worker_max_attempts=int(step.get("maxAttempts", 3)),
                )
                self._json(200 if duplicate else 201, {"task": task, "deduplicated": duplicate})
                return
            if path == "/api/worker/run-once":
                self._json(200, self.worker.run_once())
                return
            if path == "/api/relay/drain":
                self._json(200, self.relay.drain())
                return
            if path.endswith("/action") and path.startswith("/api/runs/"):
                run_id = unquote(path[len("/api/runs/"):-len("/action")].strip("/"))
                run = self.engine.apply_action(run_id, str(body.get("action", "")),
                                               step_id=body.get("stepId"), note=str(body.get("note", "")),
                                               actor=str(body.get("actor", "local-operator")))
                self._json(200, {"run": run})
                return
            self._json(404, {"error": "not_found"})
        except IdempotencyConflict as exc:
            self._json(409, {"error": str(exc)})
        except WorkflowError as exc:
            self._json(exc.status_code, {"error": str(exc)})
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            self._json(400, {"error": str(exc)})
        except FileNotFoundError:
            self._json(404, {"error": "workflow input not found"})
        except Exception as exc:
            self._json(500, {"error_type": type(exc).__name__, "message": "request failed; raw details omitted"})

    def log_message(self, fmt: str, *args) -> None:
        print("[real-agent-workflow] " + fmt % args)


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8769)
    parser.add_argument("--db", default=str(ROOT / "data/real-agent-workflow/agent_workflow.sqlite3"))
    args = parser.parse_args()
    if args.host not in {"127.0.0.1", "localhost", "::1"}:
        print("WARNING: unauthenticated console is exposed on a non-loopback interface", file=sys.stderr)
    db_path = Path(args.db)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    workflow_store = SQLiteWorkflowStore(db_path)
    task_store = SQLiteTaskStore(db_path)
    engine = WorkflowEngine(workflow_store, load_definition())
    runtime = OpenAIAgentsRuntime(project_root=ROOT)
    artifact_root = ROOT / "data" / "real-agent-workflow" / "artifacts"
    step_handler = AgentWorkflowStepHandler(runtime, artifact_root=artifact_root)
    handlers = {f"agent.workflow-step.{step_id}": step_handler
                for step_id in AgentWorkflowStepHandler.STAGE_TO_ROLE}
    worker = TaskWorker(task_store, handlers, worker_id="real-agent-worker", lease_seconds=120)
    relay = WorkflowOutboxRelay(task_store, engine, relay_id="real-agent-relay")
    AgentWorkflowConsoleHandler.engine = engine
    AgentWorkflowConsoleHandler.workflow_store = workflow_store
    AgentWorkflowConsoleHandler.task_store = task_store
    AgentWorkflowConsoleHandler.worker = worker
    AgentWorkflowConsoleHandler.relay = relay
    AgentWorkflowConsoleHandler.static_path = ROOT / "apps" / "agent-workflow-console" / "index.html"
    AgentWorkflowConsoleHandler.input_root = ROOT / "data" / "real-agent-workflow" / "inputs"
    server = ThreadingHTTPServer((args.host, args.port), AgentWorkflowConsoleHandler)
    print(f"Real Agent Workflow Console: http://{args.host}:{args.port}")
    print("Credentials are read from OPENAI_API_KEY; never paste them into the web UI.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        task_store.close()
        workflow_store.close()
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
