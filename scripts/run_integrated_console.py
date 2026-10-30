#!/usr/bin/env python3
"""Local Article 21 console: workflow -> task -> worker -> outbox -> workflow inbox.

Demo-only handlers and localhost binding by default. No real LLM, CI runner or deployer.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, unquote

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from ontology_software_factory.integration import WorkflowOutboxRelay, demo_workflow_step_handler, enqueue_workflow_step  # noqa: E402
from ontology_software_factory.task_runtime import IdempotencyConflict, SQLiteTaskStore, TaskWorker  # noqa: E402
from ontology_software_factory.workflow_engine import WorkflowEngine, WorkflowError  # noqa: E402
from ontology_software_factory.workflow_store import SQLiteWorkflowStore  # noqa: E402


def load_definition() -> dict:
    path = ROOT / "workflows/definitions/software-delivery-v1.json"
    return json.loads(path.read_text(encoding="utf-8"))


class IntegratedConsoleHandler(BaseHTTPRequestHandler):
    engine: WorkflowEngine
    workflow_store: SQLiteWorkflowStore
    task_store: SQLiteTaskStore
    worker: TaskWorker
    relay: WorkflowOutboxRelay
    static_path: Path
    server_version = "OntologyClosedLoopConsole/0.1"

    def log_message(self, fmt, *args):
        super().log_message(fmt, *args)

    def _json(self, status: int, value: dict) -> None:
        body = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length > 65536:
            raise ValueError("request body too large")
        body = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
        if not isinstance(body, dict):
            raise ValueError("request body must be a JSON object")
        return body

    def do_GET(self):  # noqa: N802
        path = urlparse(self.path).path
        if path == "/api/health":
            runs = self.workflow_store.list_runs()
            tasks = self.task_store.list_tasks(500)
            outbox = self.task_store.list_outbox(1000)
            self._json(200, {
                "status": "ok", "mode": "demo", "runs": len(runs), "tasks": len(tasks),
                "outbox": dict(Counter(item["status"] for item in outbox)),
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
            self._json(200, {"tasks": self.task_store.list_tasks(300)})
            return
        if path.startswith("/api/tasks/"):
            task_id = unquote(path.removeprefix("/api/tasks/"))
            task = self.task_store.get_task(task_id)
            if task is None:
                self._json(404, {"error": "task not found"})
            else:
                self._json(200, {"task": task, "events": self.task_store.get_events(task_id)})
            return
        if path == "/api/outbox":
            self._json(200, {"events": self.task_store.list_outbox(500)})
            return
        if path in {"/", "/index.html"}:
            body = self.static_path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return
        self._json(404, {"error": "not found"})

    def do_POST(self):  # noqa: N802
        path = urlparse(self.path).path
        try:
            body = self._read_json()
            if path == "/api/runs":
                run = self.engine.create_run(str(body.get("title", "软件工厂闭环演示")),
                                             str(body.get("requestedBy", "local-operator")),
                                             str(body.get("environment", "test")))
                self._json(201, {"run": run})
                return
            if path.startswith("/api/runs/") and path.endswith("/dispatch"):
                run_id = unquote(path[len("/api/runs/"):-len("/dispatch")].strip("/"))
                run = self.engine.get_run(run_id)
                step = next((item for item in run["steps"] if item["id"] == run.get("currentStepId")), None)
                if not step:
                    self._json(409, {"error": "workflow has no current step to dispatch"})
                    return
                task, duplicate = enqueue_workflow_step(
                    self.task_store, run, step, body.get("input", {}),
                    worker_max_attempts=int(body.get("workerMaxAttempts", 3)),
                )
                self._json(200 if duplicate else 201, {"task": task, "deduplicated": duplicate,
                                                         "workflowRunId": run_id, "workflowStepId": step["id"]})
                return
            if path == "/api/worker/run-once":
                self._json(200, self.worker.run_once())
                return
            if path == "/api/relay/run-once":
                self._json(200, self.relay.run_once())
                return
            if path == "/api/relay/drain":
                self._json(200, self.relay.drain())
                return
            if path.startswith("/api/outbox/") and path.endswith("/replay"):
                event_id = unquote(path[len("/api/outbox/"):-len("/replay")].strip("/"))
                event = self.task_store.replay_outbox_event(event_id)
                if event is None:
                    self._json(404, {"error": "outbox event not found"})
                else:
                    self._json(200, {"event": event})
                return
            if path.startswith("/api/runs/") and path.endswith("/action"):
                run_id = unquote(path[len("/api/runs/"):-len("/action")].strip("/"))
                run = self.engine.apply_action(run_id, str(body.get("action", "")),
                                               step_id=body.get("stepId"), note=str(body.get("note", "")),
                                               actor=str(body.get("actor", "local-operator")))
                self._json(200, {"run": run})
                return
            self._json(404, {"error": "API endpoint not found"})
        except IdempotencyConflict as exc:
            self._json(409, {"error": str(exc)})
        except WorkflowError as exc:
            self._json(exc.status_code, {"error": str(exc)})
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            self._json(400, {"error": str(exc)})
        except Exception as exc:
            self._json(500, {"error": f"internal error: {type(exc).__name__}: {exc}"})


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the local workflow-worker closed-loop demo console")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8767)
    parser.add_argument("--db", default=str(ROOT / "data/integrated-console/software_factory.sqlite3"))
    parser.add_argument("--worker-id", default="local-integrated-demo-worker")
    parser.add_argument("--relay-id", default="local-integrated-demo-relay")
    args = parser.parse_args()

    # Separate logical stores share one SQLite file in the demo, while each keeps its own tables.
    workflow_store = SQLiteWorkflowStore(args.db)
    task_store = SQLiteTaskStore(args.db)
    engine = WorkflowEngine(workflow_store, load_definition())
    worker = TaskWorker(task_store, {"demo.workflow-step": demo_workflow_step_handler},
                        worker_id=args.worker_id, lease_seconds=10)
    relay = WorkflowOutboxRelay(task_store, engine, relay_id=args.relay_id, lease_seconds=10)
    IntegratedConsoleHandler.engine = engine
    IntegratedConsoleHandler.workflow_store = workflow_store
    IntegratedConsoleHandler.task_store = task_store
    IntegratedConsoleHandler.worker = worker
    IntegratedConsoleHandler.relay = relay
    IntegratedConsoleHandler.static_path = ROOT / "apps/integrated-console/index.html"
    try:
        server = ThreadingHTTPServer((args.host, args.port), IntegratedConsoleHandler)
    except OSError as exc:
        task_store.close()
        workflow_store.close()
        print(f"Cannot bind {args.host}:{args.port}: {exc}", file=sys.stderr)
        return 2
    print(f"Integrated Console (demo) running at http://{args.host}:{args.port}")
    print(f"Shared local SQLite database: {args.db}")
    print("Security note: localhost demo only; real LLM/CI/deploy integration is not enabled.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        server.server_close()
        task_store.close()
        workflow_store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
