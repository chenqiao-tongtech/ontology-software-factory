#!/usr/bin/env python3
"""Run the local Article 19 workflow console using only the Python standard library."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, unquote

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from ontology_software_factory.workflow_engine import WorkflowEngine, WorkflowError, now_iso  # noqa: E402
from ontology_software_factory.workflow_store import SQLiteWorkflowStore  # noqa: E402


def load_definition() -> dict:
    return json.loads((ROOT / "workflows/definitions/software-delivery-v1.json").read_text(encoding="utf-8"))


def _step_from_spec(spec: dict, status: str, *, started: str | None = None, finished: str | None = None,
                    attempt: int = 0, evidence: list[str] | None = None, error: str | None = None,
                    retryable: bool = False) -> dict:
    return {
        "id": spec["id"], "name": spec["name"], "roleId": spec["roleId"], "skillId": spec.get("skillId"),
        "executionMode": spec["executionMode"], "status": status, "attempt": attempt,
        "maxAttempts": spec["maxAttempts"], "dependsOn": list(spec.get("dependsOn", [])),
        "requiresApproval": bool(spec.get("requiresApproval")),
        "retryableErrorClasses": list(spec.get("retryableErrorClasses", [])),
        "requiredEvidence": list(spec.get("requiresEvidence", [])),
        "requiresIdempotencyKey": bool(spec.get("requiresIdempotencyKey", False)),
        "sideEffect": spec.get("sideEffect", "none"), "compensation": spec.get("compensation"),
        "retryable": retryable, "startedAt": started, "finishedAt": finished,
        "evidence": evidence or [], "error": error,
    }


def seed_demo_runs(store: SQLiteWorkflowStore, definition: dict) -> None:
    if store.list_runs():
        return
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc).replace(microsecond=0)
    specs = definition["steps"]

    def ts(minutes_ago: int) -> str:
        return (now - timedelta(minutes=minutes_ago)).isoformat()

    # A run waiting for a human release decision.
    steps = []
    for i, spec in enumerate(specs):
        if i < 5:
            steps.append(_step_from_spec(spec, "succeeded", started=ts(80-i*10), finished=ts(75-i*10), attempt=1,
                                         evidence=[f"演示证据：{spec['name']} 已完成；请接入真实产物引用"] ))
        elif i == 5:
            steps.append(_step_from_spec(spec, "waiting_approval", started=ts(20), attempt=0,
                                         evidence=["测试报告：PASS（演示占位）", "安全审查：PASS（演示占位）", "发布清单：release-manifest-demo"] ))
        else:
            steps.append(_step_from_spec(spec, "pending"))
    waiting = {"id": "RUN-1048", "workflowId": definition["id"], "workflowVersion": definition["version"],
               "title": "支付服务 · 版本 2.8.1 灰度发布", "status": "waiting_approval", "currentStepId": "release-approval",
               "createdAt": ts(90), "updatedAt": ts(2), "requestedBy": "ci-bot", "environment": "staging", "revision": 1, "steps": steps}
    store.seed_run(waiting, {"at": ts(2), "actor": "system", "action": "approval.waiting", "summary": "安全审查通过，等待发布审批", "payload": {"seed": True}})

    # A failed run whose test worker lost its heartbeat: retry is safe in this demo.
    steps = []
    for i, spec in enumerate(specs):
        if i < 3:
            steps.append(_step_from_spec(spec, "succeeded", started=ts(50-i*8), finished=ts(45-i*8), attempt=1,
                                         evidence=[f"演示证据：{spec['name']} 已完成"] ))
        elif i == 3:
            steps.append(_step_from_spec(spec, "failed", started=ts(12), finished=ts(5), attempt=1,
                                         evidence=[], error="CI Worker 心跳丢失，结果未完成持久化", retryable=True))
        else:
            steps.append(_step_from_spec(spec, "pending"))
    failed = {"id": "RUN-1047", "workflowId": definition["id"], "workflowVersion": definition["version"],
              "title": "用户中心 · 回归测试重跑", "status": "failed", "currentStepId": "test-suite",
              "createdAt": ts(55), "updatedAt": ts(5), "requestedBy": "dev-team", "environment": "test", "revision": 1, "steps": steps}
    store.seed_run(failed, {"at": ts(5), "actor": "test-worker", "action": "step.failed", "summary": "测试节点失败：CI Worker 心跳丢失，结果未完成持久化", "payload": {"seed": True, "stepId": "test-suite"}})

    # One successful run offers a completed audit view.
    steps = [_step_from_spec(spec, "succeeded", started=ts(240-i*4), finished=ts(236-i*4), attempt=1,
                             evidence=[f"演示证据：{spec['name']} 已完成；请替换为真实 artifact URI"] ) for i, spec in enumerate(specs)]
    done = {"id": "RUN-1046", "workflowId": definition["id"], "workflowVersion": definition["version"],
            "title": "内部工具 · v0.4.0 预发布", "status": "succeeded", "currentStepId": None,
            "createdAt": ts(260), "updatedAt": ts(210), "requestedBy": "release-bot", "environment": "staging", "revision": 1, "steps": steps}
    store.seed_run(done, {"at": ts(210), "actor": "release-bot", "action": "run.succeeded", "summary": "软件交付运行已完成（演示数据）", "payload": {"seed": True}})


class WorkflowConsoleHandler(SimpleHTTPRequestHandler):
    engine: WorkflowEngine
    static_dir: Path
    server_version = "OntologyWorkflowConsole/0.1"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(self.static_dir), **kwargs)

    def log_message(self, fmt, *args):
        # Keep request logs terse; production should use structured logging.
        super().log_message(fmt, *args)

    def _send_json(self, status: int, value: dict) -> None:
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
            raise WorkflowError("请求体太大", 413)
        if length == 0:
            return {}
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception as exc:
            raise WorkflowError("请求体必须是合法 JSON", 400) from exc
        if not isinstance(payload, dict):
            raise WorkflowError("请求体顶层必须是 JSON object", 400)
        return payload

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/health":
            return self._send_json(200, {"status": "ok", "mode": "demo", "time": now_iso()})
        if parsed.path == "/api/runs":
            return self._send_json(200, {"runs": self.engine.list_runs()})
        if parsed.path.startswith("/api/runs/"):
            run_id = unquote(parsed.path.removeprefix("/api/runs/"))
            try:
                return self._send_json(200, self.engine.get_run_detail(run_id))
            except WorkflowError as exc:
                return self._send_json(exc.status_code, {"error": str(exc)})
        if parsed.path == "/":
            self.path = "/index.html"
        return super().do_GET()

    def do_POST(self):
        parsed = urlparse(self.path)
        try:
            payload = self._read_json()
            if parsed.path == "/api/runs":
                title = str(payload.get("title", "新建软件交付运行"))
                requested_by = str(payload.get("requestedBy", "local-operator"))
                environment = str(payload.get("environment", "staging"))
                if environment not in {"dev", "test", "staging", "production"}:
                    raise WorkflowError("environment 必须是 dev/test/staging/production", 400)
                run = self.engine.create_run(title, requested_by, environment)
                return self._send_json(201, {"run": run})
            if parsed.path.startswith("/api/runs/") and parsed.path.endswith("/actions"):
                run_id = unquote(parsed.path[len("/api/runs/"):-len("/actions")].strip("/"))
                action = str(payload.get("action", ""))
                run = self.engine.apply_action(run_id, action, step_id=payload.get("stepId"),
                                               note=str(payload.get("note", "")), actor=str(payload.get("actor", "local-operator")))
                return self._send_json(200, {"run": run, "events": self.engine.store.get_events(run_id)})
            return self._send_json(404, {"error": "API endpoint not found"})
        except WorkflowError as exc:
            return self._send_json(exc.status_code, {"error": str(exc)})
        except Exception as exc:
            return self._send_json(500, {"error": f"internal error: {type(exc).__name__}"})


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the local software-factory workflow console")
    parser.add_argument("--host", default="127.0.0.1", help="Bind address; use localhost for this demo")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--db", default=str(ROOT / "data/workflow-console/workflow_console.sqlite3"), help="SQLite path")
    args = parser.parse_args()
    static_dir = ROOT / "apps/workflow-console"
    store = SQLiteWorkflowStore(args.db)
    definition = load_definition()
    seed_demo_runs(store, definition)
    engine = WorkflowEngine(store, definition)
    WorkflowConsoleHandler.engine = engine
    WorkflowConsoleHandler.static_dir = static_dir
    try:
        server = ThreadingHTTPServer((args.host, args.port), WorkflowConsoleHandler)
    except OSError as exc:
        print(f"Cannot bind {args.host}:{args.port}: {exc}", file=sys.stderr)
        store.close()
        return 2
    print(f"Workflow Console (demo) running at http://{args.host}:{args.port}")
    print(f"SQLite store: {args.db}")
    print("Security note: localhost-only demo; do not expose to a network without authentication and authorization.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        server.server_close()
        store.close()
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
