"""SQLite persistence for workflow runs and immutable event records.

This small store is designed for a local engineering demo. For multi-process or
multi-node deployments, use a production database and transactional outbox.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from pathlib import Path
from typing import Any


class ConcurrentWorkflowUpdate(RuntimeError):
    """Raised when an update used a stale revision."""


class SQLiteWorkflowStore:
    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.db_path, timeout=10, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        if self.db_path != ":memory:":
            self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS workflow_runs (
                run_id TEXT PRIMARY KEY,
                revision INTEGER NOT NULL,
                status TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                payload TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS workflow_events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                at TEXT NOT NULL,
                actor TEXT NOT NULL,
                action TEXT NOT NULL,
                summary TEXT NOT NULL,
                payload TEXT NOT NULL,
                FOREIGN KEY(run_id) REFERENCES workflow_runs(run_id)
            );
            CREATE INDEX IF NOT EXISTS idx_workflow_events_run_id_event_id
              ON workflow_events(run_id, event_id);
            CREATE TABLE IF NOT EXISTS workflow_inbox (
                integration_event_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                action TEXT NOT NULL,
                processed_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_workflow_inbox_run ON workflow_inbox(run_id, processed_at);
            CREATE TABLE IF NOT EXISTS factory_orchestrator_plans (
                plan_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                payload_sha256 TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_factory_plans_run ON factory_orchestrator_plans(run_id, created_at);
        """)
        self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def list_runs(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT payload, revision FROM workflow_runs ORDER BY updated_at DESC"
            ).fetchall()
        result = []
        for row in rows:
            item = json.loads(row["payload"])
            item["revision"] = row["revision"]
            result.append(item)
        return result

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT payload, revision FROM workflow_runs WHERE run_id = ?", (run_id,)
            ).fetchone()
        if row is None:
            return None
        item = json.loads(row["payload"])
        item["revision"] = row["revision"]
        return item

    def get_events(self, run_id: str, limit: int = 200) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT event_id, at, actor, action, summary, payload FROM workflow_events "
                "WHERE run_id = ? ORDER BY event_id DESC LIMIT ?", (run_id, limit)
            ).fetchall()
        events = []
        for row in reversed(rows):
            events.append({
                "eventId": row["event_id"], "at": row["at"], "actor": row["actor"],
                "action": row["action"], "summary": row["summary"],
                "payload": json.loads(row["payload"]),
            })
        return events

    def seed_run(self, run: dict[str, Any], event: dict[str, Any]) -> None:
        """Insert a sample run once; never overwrite existing operator activity."""
        payload = dict(run)
        revision = int(payload.get("revision", 1))
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            exists = self._conn.execute(
                "SELECT 1 FROM workflow_runs WHERE run_id = ?", (payload["id"],)
            ).fetchone()
            if exists:
                self._conn.rollback()
                return
            self._conn.execute(
                "INSERT INTO workflow_runs(run_id, revision, status, updated_at, payload) VALUES(?,?,?,?,?)",
                (payload["id"], revision, payload["status"], payload["updatedAt"], json.dumps(payload, ensure_ascii=False)),
            )
            self._insert_event(payload["id"], event)
            self._conn.commit()

    def insert_new_run(self, run: dict[str, Any], event: dict[str, Any]) -> None:
        payload = dict(run)
        revision = int(payload.get("revision", 1))
        with self._lock:
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                self._conn.execute(
                    "INSERT INTO workflow_runs(run_id, revision, status, updated_at, payload) VALUES(?,?,?,?,?)",
                    (payload["id"], revision, payload["status"], payload["updatedAt"], json.dumps(payload, ensure_ascii=False)),
                )
                self._insert_event(payload["id"], event)
                self._conn.commit()
            except sqlite3.IntegrityError as exc:
                self._conn.rollback()
                raise ConcurrentWorkflowUpdate("Workflow run ID already exists") from exc
            except Exception:
                self._conn.rollback()
                raise

    def save_updated_run(self, run: dict[str, Any], event: dict[str, Any], expected_revision: int) -> None:
        payload = dict(run)
        revision = int(payload["revision"])
        with self._lock:
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                cursor = self._conn.execute(
                    "UPDATE workflow_runs SET revision = ?, status = ?, updated_at = ?, payload = ? "
                    "WHERE run_id = ? AND revision = ?",
                    (revision, payload["status"], payload["updatedAt"], json.dumps(payload, ensure_ascii=False), payload["id"], expected_revision),
                )
                if cursor.rowcount != 1:
                    self._conn.rollback()
                    raise ConcurrentWorkflowUpdate(
                        f"Stale run revision: expected {expected_revision}; reload before retrying"
                    )
                self._insert_event(payload["id"], event)
                self._conn.commit()
            except ConcurrentWorkflowUpdate:
                raise
            except Exception:
                self._conn.rollback()
                raise

    def insert_factory_orchestrator_plan(self, run_id: str, plan: dict[str, Any], event: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        """Persist an immutable validated plan and its workflow event in one transaction."""
        plan_json = json.dumps(plan, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(plan_json.encode("utf-8")).hexdigest()
        plan_id = str(plan.get("planId", ""))
        with self._lock:
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                existing = self._conn.execute("SELECT run_id, payload_sha256, payload_json, created_at FROM factory_orchestrator_plans WHERE plan_id=?", (plan_id,)).fetchone()
                if existing:
                    self._conn.rollback()
                    if existing["run_id"] != run_id or existing["payload_sha256"] != digest:
                        raise ValueError("planId already exists with a different run or payload")
                    return {"planId": plan_id, "workflowRunId": run_id, "status": "submitted", "digest": digest, "createdAt": existing["created_at"], "plan": json.loads(existing["payload_json"])}, False
                self._conn.execute("INSERT INTO factory_orchestrator_plans(plan_id,run_id,payload_sha256,payload_json,created_at) VALUES(?,?,?,?,?)", (plan_id, run_id, digest, plan_json, event["at"]))
                persisted_event = dict(event)
                persisted_event["payload"] = {**event.get("payload", {}), "planDigest": digest}
                self._insert_event(run_id, persisted_event)
                self._conn.commit()
                return {"planId": plan_id, "workflowRunId": run_id, "status": "submitted", "digest": digest, "createdAt": event["at"], "plan": json.loads(plan_json)}, True
            except ValueError:
                raise
            except Exception:
                self._conn.rollback()
                raise

    def get_factory_orchestrator_plan(self, plan_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute("SELECT plan_id,run_id,payload_sha256,payload_json,created_at FROM factory_orchestrator_plans WHERE plan_id=?", (plan_id,)).fetchone()
        if row is None:
            return None
        return {"planId": row["plan_id"], "workflowRunId": row["run_id"], "status": "submitted", "digest": row["payload_sha256"], "createdAt": row["created_at"], "plan": json.loads(row["payload_json"])}

    def list_factory_orchestrator_plans(self, run_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute("SELECT plan_id,run_id,payload_sha256,payload_json,created_at FROM factory_orchestrator_plans WHERE run_id=? ORDER BY created_at,plan_id", (run_id,)).fetchall()
        return [{"planId": row["plan_id"], "workflowRunId": row["run_id"], "status": "submitted", "digest": row["payload_sha256"], "createdAt": row["created_at"], "plan": json.loads(row["payload_json"])} for row in rows]

    def has_processed_integration_event(self, event_id: str) -> bool:
        with self._lock:
            row = self._conn.execute("SELECT 1 FROM workflow_inbox WHERE integration_event_id=?", (event_id,)).fetchone()
        return row is not None

    def save_worker_result(self, run: dict[str, Any], event: dict[str, Any], *,
                           expected_revision: int, integration_event_id: str) -> bool:
        """Atomically mutate the run, append its event, and consume the integration event."""
        payload = dict(run)
        with self._lock:
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                seen = self._conn.execute("SELECT 1 FROM workflow_inbox WHERE integration_event_id=?",
                                          (integration_event_id,)).fetchone()
                if seen:
                    self._conn.rollback()
                    return False
                cursor = self._conn.execute(
                    "UPDATE workflow_runs SET revision=?,status=?,updated_at=?,payload=? WHERE run_id=? AND revision=?",
                    (int(payload["revision"]), payload["status"], payload["updatedAt"],
                     json.dumps(payload, ensure_ascii=False), payload["id"], expected_revision),
                )
                if cursor.rowcount != 1:
                    self._conn.rollback()
                    raise ConcurrentWorkflowUpdate(
                        f"Stale run revision while applying worker result: expected {expected_revision}; reload before retrying"
                    )
                self._insert_event(payload["id"], event)
                self._conn.execute(
                    "INSERT INTO workflow_inbox(integration_event_id,run_id,action,processed_at) VALUES(?,?,?,?)",
                    (integration_event_id, payload["id"], event["action"], event["at"]),
                )
                self._conn.commit()
                return True
            except ConcurrentWorkflowUpdate:
                raise
            except sqlite3.IntegrityError:
                self._conn.rollback()
                # A concurrent consumer may have inserted this event first.
                if self.has_processed_integration_event(integration_event_id):
                    return False
                raise
            except Exception:
                self._conn.rollback()
                raise

    def record_ignored_integration_event(self, run_id: str, event: dict[str, Any], integration_event_id: str,
                                         reason: str) -> bool:
        """Consume stale/late events and keep an audit row without reviving terminal runs."""
        with self._lock:
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                seen = self._conn.execute("SELECT 1 FROM workflow_inbox WHERE integration_event_id=?",
                                          (integration_event_id,)).fetchone()
                if seen:
                    self._conn.rollback()
                    return False
                self._insert_event(run_id, {
                    **event, "action": "worker.result_ignored",
                    "summary": f"忽略过期或不适用的 Worker 结果：{reason}",
                    "payload": {**event.get("payload", {}), "ignoreReason": reason,
                                "integrationEventId": integration_event_id},
                })
                self._conn.execute(
                    "INSERT INTO workflow_inbox(integration_event_id,run_id,action,processed_at) VALUES(?,?,?,?)",
                    (integration_event_id, run_id, "worker.result_ignored", event["at"]),
                )
                self._conn.commit()
                return True
            except Exception:
                self._conn.rollback()
                raise

    def _insert_event(self, run_id: str, event: dict[str, Any]) -> None:
        self._conn.execute(
            "INSERT INTO workflow_events(run_id, at, actor, action, summary, payload) VALUES(?,?,?,?,?,?)",
            (run_id, event["at"], event.get("actor", "system"), event["action"], event["summary"],
             json.dumps(event.get("payload", {}), ensure_ascii=False)),
        )
