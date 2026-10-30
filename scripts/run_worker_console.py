#!/usr/bin/env python3
"""Local demo console for the Article 20 Worker queue, stdlib-only."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, unquote

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from ontology_software_factory.task_runtime import (  # noqa: E402
    IdempotencyConflict, SQLiteTaskStore, TaskWorker, echo_handler, sample_evidence_handler,
)


class WorkerConsoleHandler(BaseHTTPRequestHandler):
    store: SQLiteTaskStore
    worker: TaskWorker
    static_path: Path
    server_version = "OntologyWorkerConsole/0.1"

    def log_message(self, fmt, *args):
        super().log_message(fmt, *args)

    def _json(self, status, value):
        body = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length > 65536:
            raise ValueError("request body too large")
        data = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
        if not isinstance(data, dict):
            raise ValueError("request body must be a JSON object")
        return data

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/health":
            return self._json(200, {"status": "ok", "mode": "demo"})
        if path == "/api/tasks":
            return self._json(200, {"tasks": self.store.list_tasks()})
        if path.startswith("/api/tasks/"):
            task_id = unquote(path.removeprefix("/api/tasks/"))
            task = self.store.get_task(task_id)
            if not task:
                return self._json(404, {"error": "task not found"})
            return self._json(200, {"task": task, "events": self.store.get_events(task_id)})
        if path == "/" or path == "/index.html":
            body = self.static_path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            return self.wfile.write(body)
        return self._json(404, {"error": "not found"})

    def do_POST(self):
        path = urlparse(self.path).path
        try:
            payload = self._read_json()
            if path == "/api/tasks":
                task_type = str(payload.get("taskType", "demo.generate-evidence"))
                if task_type not in {"demo.echo", "demo.generate-evidence"}:
                    return self._json(400, {"error": "demo console only permits demo.echo or demo.generate-evidence"})
                task_payload = payload.get("payload", {"message": "Article 20 demo"})
                if not isinstance(task_payload, dict):
                    return self._json(400, {"error": "payload must be a JSON object"})
                idempotency_key = str(payload.get("idempotencyKey", ""))
                if not idempotency_key:
                    return self._json(400, {"error": "idempotencyKey is required"})
                task, deduplicated = self.store.enqueue(task_type=task_type, payload=task_payload,
                    idempotency_key=idempotency_key, required_evidence=payload.get("requiredEvidence", []),
                    max_attempts=int(payload.get("maxAttempts", 4)), timeout_seconds=float(payload.get("timeoutSeconds", 30)))
                return self._json(200 if deduplicated else 201, {"task": task, "deduplicated": deduplicated})
            if path == "/api/worker/run-once":
                return self._json(200, self.worker.run_once())
            return self._json(404, {"error": "API endpoint not found"})
        except IdempotencyConflict as exc:
            return self._json(409, {"error": str(exc)})
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            return self._json(400, {"error": str(exc)})
        except Exception as exc:
            return self._json(500, {"error": f"internal error: {type(exc).__name__}: {exc}"})


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the local Worker task demo console")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--db", default=str(ROOT / "data/worker-runtime/worker_tasks.sqlite3"))
    parser.add_argument("--worker-id", default="local-demo-worker")
    args = parser.parse_args()
    store = SQLiteTaskStore(args.db)
    worker = TaskWorker(store, {"demo.echo": echo_handler, "demo.generate-evidence": sample_evidence_handler}, worker_id=args.worker_id)
    WorkerConsoleHandler.store = store
    WorkerConsoleHandler.worker = worker
    WorkerConsoleHandler.static_path = ROOT / "apps/worker-console/index.html"
    try:
        server = ThreadingHTTPServer((args.host, args.port), WorkerConsoleHandler)
    except OSError as exc:
        store.close()
        print(f"Cannot bind {args.host}:{args.port}: {exc}", file=sys.stderr)
        return 2
    print(f"Worker Console (demo) running at http://{args.host}:{args.port}")
    print(f"SQLite queue: {args.db}")
    print("Security note: demo handlers only; localhost-only; no authentication or production task execution.")
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
