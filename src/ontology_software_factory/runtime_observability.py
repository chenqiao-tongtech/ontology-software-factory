"""Read-only projection of the real Agent Workflow SQLite store for Portal monitoring."""
from __future__ import annotations

import json
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _epoch_iso(value: Any) -> str | None:
    try:
        return datetime.fromtimestamp(float(value), timezone.utc).isoformat()
    except (TypeError, ValueError, OSError, OverflowError):
        return None


def _table_exists(connection: sqlite3.Connection, name: str) -> bool:
    return connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone() is not None


def read_agent_workflow_store(db_path: str | Path, *, run_limit: int = 30, event_limit: int = 50) -> dict[str, Any]:
    """Read selected operational columns only; never return task payloads or event payload JSON."""
    path = Path(db_path).expanduser().resolve()
    if not path.is_file():
        return {"available": False, "sourceMode": "read-only-sqlite", "reason": "workflow database file not found"}
    try:
        connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=2)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only=ON")
    except sqlite3.Error as exc:
        return {"available": False, "sourceMode": "read-only-sqlite", "reason": f"database unavailable ({type(exc).__name__})"}
    try:
        runs: list[dict[str, Any]] = []
        events: list[dict[str, Any]] = []
        tasks: list[dict[str, Any]] = []
        total_workflow_runs = 0
        total_worker_tasks = 0
        run_statuses: Counter[str] = Counter()
        step_statuses: Counter[str] = Counter()
        task_statuses: Counter[str] = Counter()
        if _table_exists(connection, "workflow_runs"):
            total_workflow_runs = int(connection.execute("SELECT COUNT(*) FROM workflow_runs").fetchone()[0])
            run_statuses.update({str(row[0] or "unknown"): int(row[1]) for row in connection.execute("SELECT status, COUNT(*) FROM workflow_runs GROUP BY status").fetchall()})
            rows = connection.execute(
                "SELECT run_id, revision, status, updated_at, payload FROM workflow_runs ORDER BY updated_at DESC LIMIT ?",
                (max(1, min(int(run_limit), 100)),),
            ).fetchall()
            for row in rows:
                try:
                    payload = json.loads(row["payload"])
                except (TypeError, json.JSONDecodeError):
                    payload = {}
                if not isinstance(payload, dict):
                    payload = {}
                steps = []
                for step in payload.get("steps", []) if isinstance(payload.get("steps", []), list) else []:
                    if not isinstance(step, dict):
                        continue
                    status = str(step.get("status", "unknown"))
                    step_statuses[status] += 1
                    steps.append({
                        "id": step.get("id"),
                        "name": step.get("name"),
                        "roleId": step.get("roleId"),
                        "status": status,
                        "attempt": step.get("attempt"),
                        "startedAt": step.get("startedAt"),
                        "finishedAt": step.get("finishedAt"),
                    })
                status = str(row["status"] or payload.get("status", "unknown"))
                runs.append({
                    "runId": row["run_id"],
                    "title": payload.get("title") or payload.get("name") or row["run_id"],
                    "status": status,
                    "revision": row["revision"],
                    "updatedAt": row["updated_at"],
                    "createdAt": payload.get("createdAt"),
                    "runtimeMode": payload.get("runtimeMode") or payload.get("executionMode") or "workflow-engine",
                    "steps": steps,
                    "stepCount": len(steps),
                    "currentStep": payload.get("currentStep"),
                })
        if _table_exists(connection, "workflow_events"):
            rows = connection.execute(
                "SELECT event_id, run_id, at, actor, action, summary FROM workflow_events ORDER BY event_id DESC LIMIT ?",
                (max(1, min(int(event_limit), 200)),),
            ).fetchall()
            events = [{
                "eventId": row["event_id"], "runId": row["run_id"], "at": row["at"],
                "actor": row["actor"], "action": row["action"], "summary": row["summary"],
            } for row in reversed(rows)]
        if _table_exists(connection, "worker_tasks"):
            total_worker_tasks = int(connection.execute("SELECT COUNT(*) FROM worker_tasks").fetchone()[0])
            task_statuses.update({str(row[0] or "unknown"): int(row[1]) for row in connection.execute("SELECT status, COUNT(*) FROM worker_tasks GROUP BY status").fetchall()})
            rows = connection.execute(
                "SELECT task_id, task_type, queue_name, status, attempts, max_attempts, created_at, updated_at, lease_owner, error_class "
                "FROM worker_tasks ORDER BY created_at DESC LIMIT 100"
            ).fetchall()
            for row in rows:
                status = str(row["status"] or "unknown")
                tasks.append({
                    "taskId": row["task_id"], "taskType": row["task_type"], "queue": row["queue_name"],
                    "status": status, "attempts": row["attempts"], "maxAttempts": row["max_attempts"],
                    "createdAt": _epoch_iso(row["created_at"]), "updatedAt": _epoch_iso(row["updated_at"]),
                    "leaseOwner": row["lease_owner"], "errorClass": row["error_class"],
                })
        return {
            "available": True,
            "sourceMode": "read-only-sqlite",
            "databaseName": path.name,
            "workflowRuns": {"total": total_workflow_runs, "byStatus": dict(run_statuses),
                             "stepStatuses": dict(step_statuses), "recent": runs},
            "workerTasks": {"total": total_worker_tasks, "byStatus": dict(task_statuses), "recent": tasks[:30]},
            "recentEvents": events,
            "privacy": "workflow/task payloads, model prompts, responses, raw tool arguments and event payload JSON are not returned",
        }
    except sqlite3.Error as exc:
        return {"available": False, "sourceMode": "read-only-sqlite", "reason": f"schema/query unavailable ({type(exc).__name__})"}
    finally:
        connection.close()
