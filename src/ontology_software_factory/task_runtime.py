"""SQLite-backed task dispatch and Worker runtime for Article 20.

This is an educational, single-host reference implementation. Delivery is at-least-once;
external side effects still require their own idempotency key and reconciliation strategy.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .governance import validate_evidence_contract
from uuid import uuid4

TERMINAL_STATUSES = {"succeeded", "failed", "dead_letter", "cancelled"}
DEFAULT_RETRYABLE_ERRORS = ["transient", "timeout", "worker_lost", "rate_limited"]


def utc_iso(epoch: float | None = None) -> str:
    dt = datetime.fromtimestamp(epoch if epoch is not None else time.time(), timezone.utc)
    return dt.replace(microsecond=0).isoformat()


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _as_epoch(value: float | None) -> float | None:
    return float(value) if value is not None else None


def _task_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["task_id"],
        "idempotencyKey": row["idempotency_key"],
        "taskType": row["task_type"],
        "queue": row["queue_name"],
        "payload": json.loads(row["payload_json"]),
        "payloadSha256": row["payload_sha256"],
        "status": row["status"],
        "attempts": row["attempts"],
        "maxAttempts": row["max_attempts"],
        "timeoutSeconds": row["timeout_seconds"],
        "retryableErrorClasses": json.loads(row["retryable_errors_json"]),
        "requiredEvidence": json.loads(row["required_evidence_json"]),
        "createdAt": utc_iso(row["created_at"]),
        "updatedAt": utc_iso(row["updated_at"]),
        "availableAt": utc_iso(row["available_at"]),
        "availableAtEpoch": row["available_at"],
        "leaseOwner": row["lease_owner"],
        "leaseExpiresAt": utc_iso(row["lease_expires_at"]) if row["lease_expires_at"] is not None else None,
        "leaseExpiresAtEpoch": row["lease_expires_at"],
        "output": json.loads(row["output_json"]) if row["output_json"] else None,
        "evidence": json.loads(row["evidence_json"]),
        "errorClass": row["error_class"],
        "errorMessage": row["error_message"],
        "backoffBaseSeconds": row["backoff_base_seconds"],
        "backoffMaxSeconds": row["backoff_max_seconds"],
        "revision": row["revision"],
    }


class TaskRuntimeError(RuntimeError):
    pass


class IdempotencyConflict(TaskRuntimeError):
    """The same idempotency key was reused for a different payload."""


class LeaseLost(TaskRuntimeError):
    """A Worker no longer owns a valid lease for the task."""


class EvidenceContractError(TaskRuntimeError):
    """A result does not satisfy the task's evidence contract."""


class TransientTaskError(TaskRuntimeError):
    """A known retryable failure raised by a handler."""


class PermanentTaskError(TaskRuntimeError):
    """A known non-retryable failure raised by a handler."""


class TaskTimeoutError(TransientTaskError):
    """The handler exceeded the task deadline or cooperatively detected it."""


class SQLiteTaskStore:
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
            CREATE TABLE IF NOT EXISTS worker_tasks (
                task_id TEXT PRIMARY KEY,
                idempotency_key TEXT NOT NULL UNIQUE,
                task_type TEXT NOT NULL,
                queue_name TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                payload_sha256 TEXT NOT NULL,
                status TEXT NOT NULL,
                attempts INTEGER NOT NULL,
                max_attempts INTEGER NOT NULL,
                timeout_seconds REAL NOT NULL,
                retryable_errors_json TEXT NOT NULL,
                required_evidence_json TEXT NOT NULL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                available_at REAL NOT NULL,
                lease_owner TEXT,
                lease_expires_at REAL,
                output_json TEXT,
                evidence_json TEXT NOT NULL,
                error_class TEXT,
                error_message TEXT,
                backoff_base_seconds REAL NOT NULL,
                backoff_max_seconds REAL NOT NULL,
                revision INTEGER NOT NULL DEFAULT 1
            );
            CREATE INDEX IF NOT EXISTS idx_worker_tasks_poll
              ON worker_tasks(queue_name, status, available_at, created_at);
            CREATE INDEX IF NOT EXISTS idx_worker_tasks_lease
              ON worker_tasks(status, lease_expires_at);
            CREATE TABLE IF NOT EXISTS worker_task_events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL,
                at REAL NOT NULL,
                actor TEXT NOT NULL,
                action TEXT NOT NULL,
                summary TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                FOREIGN KEY(task_id) REFERENCES worker_tasks(task_id)
            );
            CREATE INDEX IF NOT EXISTS idx_worker_task_events_task
              ON worker_task_events(task_id, event_id);
            CREATE TABLE IF NOT EXISTS worker_task_results (
                idempotency_key TEXT PRIMARY KEY,
                payload_sha256 TEXT NOT NULL,
                output_json TEXT NOT NULL,
                evidence_json TEXT NOT NULL,
                created_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS integration_outbox (
                event_id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at REAL NOT NULL,
                available_at REAL NOT NULL,
                locked_by TEXT,
                locked_until REAL,
                delivery_attempts INTEGER NOT NULL DEFAULT 0,
                last_error TEXT,
                delivered_at REAL,
                FOREIGN KEY(task_id) REFERENCES worker_tasks(task_id)
            );
            CREATE INDEX IF NOT EXISTS idx_integration_outbox_poll
              ON integration_outbox(status, available_at, created_at);
        """)
        self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def enqueue(self, *, task_type: str, payload: dict[str, Any], idempotency_key: str,
                queue: str = "default", max_attempts: int = 4, timeout_seconds: float = 60,
                retryable_error_classes: list[str] | None = None, required_evidence: list[str] | None = None,
                backoff_base_seconds: float = 1.0, backoff_max_seconds: float = 60.0) -> tuple[dict[str, Any], bool]:
        if not task_type.strip():
            raise ValueError("task_type must be non-empty")
        if not isinstance(payload, dict):
            raise ValueError("payload must be a JSON object")
        if not idempotency_key or len(idempotency_key) > 200:
            raise ValueError("idempotency_key must contain 1..200 characters")
        if not 1 <= int(max_attempts) <= 20:
            raise ValueError("max_attempts must be between 1 and 20")
        if not 0.1 <= float(timeout_seconds) <= 86400:
            raise ValueError("timeout_seconds must be between 0.1 and 86400")
        if float(backoff_base_seconds) < 0 or float(backoff_max_seconds) < float(backoff_base_seconds):
            raise ValueError("backoff requires 0 <= base <= max")
        retryable = sorted(set(DEFAULT_RETRYABLE_ERRORS if retryable_error_classes is None else retryable_error_classes))
        evidence_types = sorted(set(required_evidence or []))
        payload_json = _canonical_json(payload)
        payload_hash = _sha256(payload_json)
        now = time.time()
        with self._lock:
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                existing = self._conn.execute("SELECT * FROM worker_tasks WHERE idempotency_key=?", (idempotency_key,)).fetchone()
                if existing:
                    if existing["payload_sha256"] != payload_hash or existing["task_type"] != task_type or existing["queue_name"] != queue:
                        self._conn.rollback()
                        raise IdempotencyConflict("idempotency key already exists with a different task definition")
                    self._conn.commit()
                    return _task_from_row(existing), True
                task_id = f"TASK-{uuid4().hex[:12].upper()}"
                evidence_contract = payload.get("evidenceContract")
                if isinstance(evidence_contract, dict) and evidence_contract.get("taskId") == "$TASK_ID":
                    payload = {**payload, "evidenceContract": {**evidence_contract, "taskId": task_id}}
                    payload_json = _canonical_json(payload)
                    payload_hash = _sha256(payload_json)
                self._conn.execute("""INSERT INTO worker_tasks(
                    task_id,idempotency_key,task_type,queue_name,payload_json,payload_sha256,status,attempts,
                    max_attempts,timeout_seconds,retryable_errors_json,required_evidence_json,created_at,updated_at,
                    available_at,lease_owner,lease_expires_at,output_json,evidence_json,error_class,error_message,
                    backoff_base_seconds,backoff_max_seconds,revision
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (task_id,idempotency_key,task_type,queue,payload_json,payload_hash,"queued",0,int(max_attempts),
                     float(timeout_seconds),_canonical_json(retryable),_canonical_json(evidence_types),now,now,now,
                     None,None,None,"[]",None,None,float(backoff_base_seconds),float(backoff_max_seconds),1))
                self._event_locked(task_id, now, "dispatcher", "task.enqueued", "任务已进入队列", {
                    "taskType": task_type, "queue": queue, "idempotencyKey": idempotency_key,
                    "requiredEvidence": evidence_types,
                })
                row = self._conn.execute("SELECT * FROM worker_tasks WHERE task_id=?", (task_id,)).fetchone()
                self._conn.commit()
                return _task_from_row(row), False
            except IdempotencyConflict:
                raise
            except Exception:
                self._conn.rollback()
                raise

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM worker_tasks WHERE task_id=?", (task_id,)).fetchone()
        return _task_from_row(row) if row else None

    def cancel(self, task_id: str, *, actor: str, reason: str = "cancelled by operator",
               now: float | None = None) -> dict[str, Any]:
        """Cancel a queued/running task and fence off any late Worker completion.

        A running Python handler is cooperative: this method cannot safely kill its
        thread or reverse an external side effect. Clearing the lease and moving the
        task to a terminal state ensures its eventual complete()/fail() call is rejected.
        """
        if not actor or not actor.strip():
            raise ValueError("actor must be non-empty")
        current = time.time() if now is None else float(now)
        with self._lock:
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                row = self._conn.execute("SELECT * FROM worker_tasks WHERE task_id=?", (task_id,)).fetchone()
                if row is None:
                    self._conn.rollback()
                    raise TaskRuntimeError(f"unknown task: {task_id}")
                task = _task_from_row(row)
                if task["status"] in TERMINAL_STATUSES:
                    self._conn.commit()
                    return task
                self._conn.execute(
                    """UPDATE worker_tasks SET status='cancelled', updated_at=?,
                       lease_owner=NULL, lease_expires_at=NULL, error_class='cancelled',
                       error_message=?, revision=revision+1 WHERE task_id=?""",
                    (current, (reason or "cancelled")[:4000], task_id),
                )
                self._event_locked(task_id, current, actor, "task.cancelled",
                    "任务被取消；后续迟到的 Worker 结果将被拒绝",
                    {"reason": (reason or "cancelled")[:1000], "previousStatus": task["status"],
                     "previousWorker": task["leaseOwner"]})
                updated = self._conn.execute("SELECT * FROM worker_tasks WHERE task_id=?", (task_id,)).fetchone()
                self._conn.commit()
                return _task_from_row(updated)
            except TaskRuntimeError:
                raise
            except Exception:
                self._conn.rollback()
                raise

    def list_tasks(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM worker_tasks ORDER BY updated_at DESC LIMIT ?", (max(1, min(limit, 500)),)).fetchall()
        return [_task_from_row(row) for row in rows]

    def get_events(self, task_id: str, limit: int = 200) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute("""SELECT event_id,at,actor,action,summary,payload_json
                FROM worker_task_events WHERE task_id=? ORDER BY event_id DESC LIMIT ?""", (task_id, limit)).fetchall()
        return [{"eventId": row["event_id"], "at": utc_iso(row["at"]), "actor": row["actor"],
                 "action": row["action"], "summary": row["summary"], "payload": json.loads(row["payload_json"])}
                for row in reversed(rows)]

    def claim(self, worker_id: str, *, queue: str = "default", lease_seconds: float = 90,
              now: float | None = None) -> dict[str, Any] | None:
        if not worker_id.strip():
            raise ValueError("worker_id must be non-empty")
        if lease_seconds < 1:
            raise ValueError("lease_seconds must be >= 1")
        current = time.time() if now is None else float(now)
        with self._lock:
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                expired = self._conn.execute("SELECT * FROM worker_tasks WHERE status='running' AND lease_expires_at<=?", (current,)).fetchall()
                for row in expired:
                    task = _task_from_row(row)
                    retry_at = current + self._backoff(task, task["attempts"])
                    if task["attempts"] >= task["maxAttempts"]:
                        status = "dead_letter"
                        self._conn.execute("""UPDATE worker_tasks SET status=?,lease_owner=NULL,lease_expires_at=NULL,
                            updated_at=?,error_class='worker_lost',error_message='worker lease expired; attempts exhausted',revision=revision+1
                            WHERE task_id=?""", (status,current,task["id"]))
                    else:
                        status = "retry_wait"
                        self._conn.execute("""UPDATE worker_tasks SET status=?,available_at=?,lease_owner=NULL,lease_expires_at=NULL,
                            updated_at=?,error_class='worker_lost',error_message='worker lease expired; awaiting retry',revision=revision+1
                            WHERE task_id=?""", (status,retry_at,current,task["id"]))
                    self._event_locked(task["id"], current, "dispatcher", "task.lease_expired",
                                       f"Worker 租约过期，任务转为 {status}", {"previousWorker": task["leaseOwner"], "attempts": task["attempts"], "availableAt": utc_iso(retry_at)})
                row = self._conn.execute("""SELECT * FROM worker_tasks
                    WHERE queue_name=? AND status IN ('queued','retry_wait') AND available_at<=?
                    ORDER BY available_at ASC,created_at ASC LIMIT 1""", (queue,current)).fetchone()
                if not row:
                    self._conn.commit()
                    return None
                task = _task_from_row(row)
                new_attempt = task["attempts"] + 1
                lease_expiry = current + lease_seconds
                self._conn.execute("""UPDATE worker_tasks SET status='running',attempts=?,lease_owner=?,lease_expires_at=?,
                    updated_at=?,error_class=NULL,error_message=NULL,revision=revision+1 WHERE task_id=?""",
                    (new_attempt,worker_id,lease_expiry,current,task["id"]))
                self._event_locked(task["id"], current, worker_id, "task.claimed", f"Worker 已领取任务（尝试 {new_attempt}）",
                                   {"attempt": new_attempt, "leaseExpiresAt": utc_iso(lease_expiry)})
                claimed = self._conn.execute("SELECT * FROM worker_tasks WHERE task_id=?", (task["id"],)).fetchone()
                self._conn.commit()
                return _task_from_row(claimed)
            except Exception:
                self._conn.rollback()
                raise

    def heartbeat(self, task_id: str, worker_id: str, *, lease_seconds: float = 90,
                  now: float | None = None) -> dict[str, Any]:
        current = time.time() if now is None else float(now)
        expiry = current + lease_seconds
        with self._lock:
            cur = self._conn.execute("""UPDATE worker_tasks SET lease_expires_at=?,updated_at=?,revision=revision+1
                WHERE task_id=? AND status='running' AND lease_owner=? AND lease_expires_at>?""",
                (expiry,current,task_id,worker_id,current))
            self._conn.commit()
            if cur.rowcount != 1:
                raise LeaseLost("cannot heartbeat: lease is missing, expired or owned by another Worker")
            return self.get_task(task_id)  # type: ignore[return-value]

    def complete(self, task_id: str, worker_id: str, *, output: dict[str, Any], evidence: list[dict[str, Any]],
                 now: float | None = None) -> dict[str, Any]:
        current = time.time() if now is None else float(now)
        with self._lock:
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                row = self._conn.execute("SELECT * FROM worker_tasks WHERE task_id=?", (task_id,)).fetchone()
                if not row or row["status"] != "running" or row["lease_owner"] != worker_id or row["lease_expires_at"] <= current:
                    self._conn.rollback()
                    raise LeaseLost("cannot complete: Worker lease is missing, expired or no longer owned")
                task = _task_from_row(row)
                self._validate_evidence(task["requiredEvidence"], evidence)
                evidence_contract = task.get("payload", {}).get("evidenceContract")
                if evidence_contract is not None:
                    if not isinstance(evidence_contract, dict):
                        raise EvidenceContractError("task evidenceContract must be an object")
                    try:
                        validate_evidence_contract(evidence_contract, evidence)
                    except ValueError as exc:
                        raise EvidenceContractError(str(exc)) from exc
                    if evidence_contract.get("taskId") != task_id:
                        raise EvidenceContractError("evidence contract taskId does not match the current Task")
                existing = self._conn.execute("SELECT * FROM worker_task_results WHERE idempotency_key=?", (task["idempotencyKey"],)).fetchone()
                if existing:
                    if existing["payload_sha256"] != task["payloadSha256"]:
                        self._conn.rollback()
                        raise IdempotencyConflict("stored result payload hash does not match task")
                    stored_output = existing["output_json"]
                    stored_evidence = existing["evidence_json"]
                    action = "task.result_reused"
                    summary = "重用同一幂等键的既有结果"
                else:
                    stored_output = _canonical_json(output)
                    stored_evidence = _canonical_json(evidence)
                    self._conn.execute("INSERT INTO worker_task_results(idempotency_key,payload_sha256,output_json,evidence_json,created_at) VALUES(?,?,?,?,?)",
                        (task["idempotencyKey"],task["payloadSha256"],stored_output,stored_evidence,current))
                    action = "task.succeeded"
                    summary = "任务执行成功，结果和证据已持久化"
                self._conn.execute("""UPDATE worker_tasks SET status='succeeded',updated_at=?,lease_owner=NULL,lease_expires_at=NULL,
                    output_json=?,evidence_json=?,error_class=NULL,error_message=NULL,revision=revision+1 WHERE task_id=?""",
                    (current,stored_output,stored_evidence,task_id))
                self._event_locked(task_id,current,worker_id,action,summary,
                                   {"attempt":task["attempts"],"evidenceTypes":[e.get("type") for e in json.loads(stored_evidence)]})
                if action == "task.succeeded":
                    self._write_workflow_outbox_locked(task, "workflow.step.execution_succeeded", {
                        "taskStatus": "succeeded", "attempt": task["attempts"],
                        "output": json.loads(stored_output), "evidence": json.loads(stored_evidence),
                    }, current)
                result = self._conn.execute("SELECT * FROM worker_tasks WHERE task_id=?", (task_id,)).fetchone()
                self._conn.commit()
                return _task_from_row(result)
            except (LeaseLost, IdempotencyConflict, EvidenceContractError):
                raise
            except Exception:
                self._conn.rollback()
                raise

    def fail(self, task_id: str, worker_id: str, *, error_class: str, error_message: str,
             now: float | None = None) -> dict[str, Any]:
        current = time.time() if now is None else float(now)
        with self._lock:
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                row = self._conn.execute("SELECT * FROM worker_tasks WHERE task_id=?", (task_id,)).fetchone()
                if not row or row["status"] != "running" or row["lease_owner"] != worker_id or row["lease_expires_at"] <= current:
                    self._conn.rollback()
                    raise LeaseLost("cannot fail task: Worker lease is missing, expired or no longer owned")
                task = _task_from_row(row)
                retryable = error_class in task["retryableErrorClasses"]
                if retryable and task["attempts"] < task["maxAttempts"]:
                    status = "retry_wait"
                    available_at = current + self._backoff(task, task["attempts"])
                elif retryable:
                    status = "dead_letter"
                    available_at = current
                else:
                    status = "failed"
                    available_at = current
                self._conn.execute("""UPDATE worker_tasks SET status=?,updated_at=?,available_at=?,lease_owner=NULL,
                    lease_expires_at=NULL,error_class=?,error_message=?,revision=revision+1 WHERE task_id=?""",
                    (status,current,available_at,error_class,(error_message or "")[:4000],task_id))
                self._event_locked(task_id,current,worker_id,"task.failed" if status == "failed" else "task.retry_scheduled" if status == "retry_wait" else "task.dead_lettered",
                    f"任务失败：{error_class}；状态={status}", {"errorClass":error_class,"message":(error_message or "")[:1000],
                    "attempt":task["attempts"],"maxAttempts":task["maxAttempts"],"availableAt":utc_iso(available_at)})
                if status in {"failed", "dead_letter"}:
                    self._write_workflow_outbox_locked(task, "workflow.step.execution_failed", {
                        "taskStatus": status, "attempt": task["attempts"],
                        "errorClass": error_class, "errorMessage": (error_message or "")[:4000],
                        "maxAttempts": task["maxAttempts"],
                    }, current)
                result = self._conn.execute("SELECT * FROM worker_tasks WHERE task_id=?", (task_id,)).fetchone()
                self._conn.commit()
                return _task_from_row(result)
            except LeaseLost:
                raise
            except Exception:
                self._conn.rollback()
                raise

    def _write_workflow_outbox_locked(self, task: dict[str, Any], event_type: str,
                                      result_payload: dict[str, Any], now: float) -> None:
        """Persist a workflow result event in the same DB transaction as the task transition."""
        business = task.get("payload", {})
        run_id = business.get("workflowRunId")
        step_id = business.get("workflowStepId")
        factory_assignment_id = business.get("factoryAssignmentId")
        if not run_id or not (step_id or factory_assignment_id):
            return  # A standalone task has no workflow consumer.
        event_id = f"EVT-{uuid4().hex.upper()}"
        payload = {
            "eventId": event_id, "eventType": event_type, "taskId": task["id"],
            "idempotencyKey": task["idempotencyKey"], "taskType": task["taskType"],
            "workflowRunId": run_id, "workflowStepId": step_id,
            "workflowId": business.get("workflowId"), "workflowVersion": business.get("workflowVersion"),
            "workflowAttempt": business.get("workflowAttempt"),
            "businessOperationId": business.get("businessOperationId"),
            "factoryPlanId": business.get("factoryPlanId"),
            "factoryPhaseId": business.get("factoryPhaseId"),
            "factoryPhaseAttempt": business.get("factoryPhaseAttempt", 1),
            "factoryAssignmentId": factory_assignment_id,
            "roleId": business.get("roleId"), "skillId": business.get("skillId"),
            **result_payload,
        }
        self._conn.execute("""INSERT INTO integration_outbox(
            event_id,task_id,event_type,payload_json,status,created_at,available_at,
            locked_by,locked_until,delivery_attempts,last_error,delivered_at
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
            (event_id, task["id"], event_type, _canonical_json(payload), "pending", now, now,
             None, None, 0, None, None))

    def list_outbox(self, limit: int = 200) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM integration_outbox ORDER BY created_at DESC LIMIT ?",
                                      (max(1, min(int(limit), 1000)),)).fetchall()
        return [self._outbox_from_row(row) for row in rows]

    @staticmethod
    def _outbox_from_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "eventId": row["event_id"], "taskId": row["task_id"], "eventType": row["event_type"],
            "payload": json.loads(row["payload_json"]), "status": row["status"],
            "createdAt": utc_iso(row["created_at"]), "availableAt": utc_iso(row["available_at"]),
            "lockedBy": row["locked_by"], "lockedUntil": utc_iso(row["locked_until"]) if row["locked_until"] else None,
            "deliveryAttempts": row["delivery_attempts"], "lastError": row["last_error"],
            "deliveredAt": utc_iso(row["delivered_at"]) if row["delivered_at"] else None,
        }

    def claim_outbox(self, relay_id: str, *, limit: int = 20, lease_seconds: float = 30,
                     now: float | None = None) -> list[dict[str, Any]]:
        if not relay_id.strip():
            raise ValueError("relay_id must be non-empty")
        if lease_seconds < 1:
            raise ValueError("lease_seconds must be >= 1")
        current = time.time() if now is None else float(now)
        batch_limit = max(1, min(int(limit), 100))
        with self._lock:
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                rows = self._conn.execute("""SELECT * FROM integration_outbox
                    WHERE status IN ('pending','leased') AND available_at<=?
                    AND (status='pending' OR locked_until IS NULL OR locked_until<=?)
                    ORDER BY created_at ASC LIMIT ?""", (current, current, batch_limit)).fetchall()
                claimed = []
                for row in rows:
                    self._conn.execute("""UPDATE integration_outbox SET status='leased',locked_by=?,locked_until=?,
                        delivery_attempts=delivery_attempts+1 WHERE event_id=?""",
                        (relay_id, current + lease_seconds, row["event_id"]))
                    updated = self._conn.execute("SELECT * FROM integration_outbox WHERE event_id=?", (row["event_id"],)).fetchone()
                    claimed.append(self._outbox_from_row(updated))
                self._conn.commit()
                return claimed
            except Exception:
                self._conn.rollback()
                raise

    def mark_outbox_delivered(self, event_id: str, relay_id: str, *, now: float | None = None) -> bool:
        current = time.time() if now is None else float(now)
        with self._lock:
            cur = self._conn.execute("""UPDATE integration_outbox SET status='delivered',delivered_at=?,
                locked_by=NULL,locked_until=NULL,last_error=NULL WHERE event_id=? AND status='leased' AND locked_by=?""",
                (current, event_id, relay_id))
            self._conn.commit()
            return cur.rowcount == 1

    def release_outbox(self, event_id: str, relay_id: str, error: str, *, delay_seconds: float = 1.0,
                       max_delivery_attempts: int = 12, now: float | None = None) -> str:
        current = time.time() if now is None else float(now)
        with self._lock:
            row = self._conn.execute("SELECT delivery_attempts FROM integration_outbox WHERE event_id=? AND status='leased' AND locked_by=?",
                                     (event_id, relay_id)).fetchone()
            if not row:
                return "lease_lost"
            dead = int(row["delivery_attempts"]) >= int(max_delivery_attempts)
            status = "dead_letter" if dead else "pending"
            self._conn.execute("""UPDATE integration_outbox SET status=?,available_at=?,locked_by=NULL,locked_until=NULL,
                last_error=? WHERE event_id=? AND status='leased' AND locked_by=?""",
                (status, current + (0 if dead else max(0, float(delay_seconds))), str(error)[:2000], event_id, relay_id))
            self._conn.commit()
            return status

    def replay_outbox_event(self, event_id: str) -> dict[str, Any] | None:
        with self._lock:
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                row = self._conn.execute("SELECT * FROM integration_outbox WHERE event_id=?", (event_id,)).fetchone()
                if row is None:
                    self._conn.rollback()
                    return None
                self._conn.execute("""UPDATE integration_outbox SET status='pending',available_at=?,locked_by=NULL,
                    locked_until=NULL,last_error=NULL,delivered_at=NULL WHERE event_id=?""", (time.time(), event_id))
                self._conn.commit()
                return self._outbox_from_row(self._conn.execute("SELECT * FROM integration_outbox WHERE event_id=?", (event_id,)).fetchone())
            except Exception:
                self._conn.rollback()
                raise

    def defer_outbox(self, event_id: str, relay_id: str, reason: str, *,
                     delay_seconds: float = 2.0, now: float | None = None) -> str:
        """Return a leased event to pending without counting a business-delivery failure.

        A paused workflow is a deliberate consumer deferral, not a poisoned event; it must
        not be dead-lettered just because an operator pauses a run for an extended period.
        """
        current = time.time() if now is None else float(now)
        with self._lock:
            cur = self._conn.execute("""UPDATE integration_outbox SET status='pending',available_at=?,
                locked_by=NULL,locked_until=NULL,last_error=?,delivery_attempts=MAX(0,delivery_attempts-1)
                WHERE event_id=? AND status='leased' AND locked_by=?""",
                (current + max(0.0, float(delay_seconds)), str(reason)[:2000], event_id, relay_id))
            self._conn.commit()
            return "pending" if cur.rowcount == 1 else "lease_lost"

    @staticmethod
    def _validate_evidence(required: list[str], evidence: list[dict[str, Any]]) -> None:
        if not isinstance(evidence, list):
            raise EvidenceContractError("evidence must be a list")
        actual_types: set[str] = set()
        for index, item in enumerate(evidence):
            if not isinstance(item, dict):
                raise EvidenceContractError(f"evidence[{index}] must be an object")
            if not item.get("type") or not item.get("uri"):
                raise EvidenceContractError(f"evidence[{index}] requires type and uri")
            digest = str(item.get("sha256", ""))
            if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest.lower()):
                raise EvidenceContractError(f"evidence[{index}].sha256 must be a 64-character SHA-256 hex digest")
            actual_types.add(str(item["type"]))
        missing = sorted(set(required) - actual_types)
        if missing:
            raise EvidenceContractError(f"missing required evidence types: {missing}")

    @staticmethod
    def _backoff(task: dict[str, Any], attempt: int) -> float:
        base = float(task["backoffBaseSeconds"])
        maximum = float(task["backoffMaxSeconds"])
        return min(maximum, base * (2 ** max(0, int(attempt) - 1)))

    def _event_locked(self, task_id: str, at: float, actor: str, action: str, summary: str, payload: dict[str, Any]) -> None:
        self._conn.execute("INSERT INTO worker_task_events(task_id,at,actor,action,summary,payload_json) VALUES(?,?,?,?,?,?)",
            (task_id,at,actor,action,summary,_canonical_json(payload)))


@dataclass(frozen=True)
class TaskContext:
    task_id: str
    idempotency_key: str
    worker_id: str
    attempt: int
    deadline_epoch: float
    required_evidence: tuple[str, ...]

    def check_deadline(self) -> None:
        if time.time() > self.deadline_epoch:
            raise TaskTimeoutError(f"task deadline exceeded at attempt {self.attempt}")


Handler = Callable[[dict[str, Any], TaskContext], dict[str, Any]]


class TaskWorker:
    def __init__(self, store: SQLiteTaskStore, handlers: dict[str, Handler], *, worker_id: str,
                 queue: str = "default", lease_seconds: float = 90):
        self.store = store
        self.handlers = handlers
        self.worker_id = worker_id
        self.queue = queue
        self.lease_seconds = lease_seconds

    def run_once(self) -> dict[str, Any]:
        task = self.store.claim(self.worker_id, queue=self.queue, lease_seconds=self.lease_seconds)
        if task is None:
            return {"status": "idle", "workerId": self.worker_id}
        handler = self.handlers.get(task["taskType"])
        if handler is None:
            failed = self.store.fail(task["id"], self.worker_id, error_class="unknown_handler",
                                     error_message=f"no handler registered for {task['taskType']}")
            return {"status": failed["status"], "task": failed}
        context = TaskContext(task_id=task["id"], idempotency_key=task["idempotencyKey"],
            worker_id=self.worker_id, attempt=task["attempts"], deadline_epoch=time.time()+task["timeoutSeconds"],
            required_evidence=tuple(task["requiredEvidence"]))
        stop_heartbeat = threading.Event()

        def renew_lease() -> None:
            interval = max(0.25, self.lease_seconds / 3.0)
            while not stop_heartbeat.wait(interval):
                try:
                    self.store.heartbeat(task["id"], self.worker_id, lease_seconds=self.lease_seconds)
                except LeaseLost:
                    return

        heartbeat_thread = threading.Thread(target=renew_lease, name=f"lease-heartbeat-{task['id']}", daemon=True)
        heartbeat_thread.start()
        try:
            started = time.monotonic()
            try:
                result = handler(task["payload"], context)
                if not isinstance(result, dict):
                    raise PermanentTaskError("handler result must be a JSON object")
                elapsed = time.monotonic() - started
                if elapsed > task["timeoutSeconds"]:
                    raise TaskTimeoutError(f"handler elapsed {elapsed:.3f}s > timeout {task['timeoutSeconds']:.3f}s")
                context.check_deadline()
            except TaskTimeoutError as exc:
                failed = self.store.fail(task["id"], self.worker_id, error_class="timeout", error_message=str(exc))
                return {"status": failed["status"], "task": failed}
            except TransientTaskError as exc:
                failed = self.store.fail(task["id"], self.worker_id, error_class="transient", error_message=str(exc))
                return {"status": failed["status"], "task": failed}
            except PermanentTaskError as exc:
                failed = self.store.fail(task["id"], self.worker_id, error_class="permanent", error_message=str(exc))
                return {"status": failed["status"], "task": failed}
            except Exception as exc:
                failed = self.store.fail(task["id"], self.worker_id, error_class="handler_error",
                                         error_message=f"{type(exc).__name__}: {exc}")
                return {"status": failed["status"], "task": failed}
            output = result.get("output", {})
            evidence = result.get("evidence", [])
            if not isinstance(output, dict) or not isinstance(evidence, list):
                failed = self.store.fail(task["id"], self.worker_id, error_class="permanent",
                                         error_message="handler must return {output: object, evidence: list}")
                return {"status": failed["status"], "task": failed}
            try:
                completed = self.store.complete(task["id"], self.worker_id, output=output, evidence=evidence)
                return {"status": completed["status"], "task": completed}
            except EvidenceContractError as exc:
                failed = self.store.fail(task["id"], self.worker_id, error_class="invalid_evidence", error_message=str(exc))
                return {"status": failed["status"], "task": failed}
            except LeaseLost as exc:
                return {"status": "lease_lost", "taskId": task["id"], "message": str(exc)}
        finally:
            stop_heartbeat.set()
            heartbeat_thread.join(timeout=max(1.0, self.lease_seconds / 2.0))


def enqueue_workflow_step(store: SQLiteTaskStore, run: dict[str, Any], step: dict[str, Any],
                          input_payload: dict[str, Any], *, queue: str = "default") -> tuple[dict[str, Any], bool]:
    """Translate a running Article 19 step into a Worker task envelope.

    The task key deduplicates dispatches for the same workflow attempt. The stable
    businessOperationId is passed separately to downstream systems for side-effect dedupe.
    """
    if run.get("status") != "running" or step.get("status") != "running":
        raise ValueError("only the current running workflow step can be dispatched")
    run_id, step_id = str(run["id"]), str(step["id"])
    attempt = int(step.get("attempt", 1))
    task_payload = {
        "workflowId": run.get("workflowId"), "workflowVersion": run.get("workflowVersion"),
        "runId": run_id, "stepId": step_id, "workflowAttempt": attempt,
        "businessOperationId": f"{run_id}:{step_id}", "input": input_payload,
    }
    return store.enqueue(task_type=f"workflow.step.{step_id}", payload=task_payload,
        idempotency_key=f"workflow:{run_id}:{step_id}:attempt:{attempt}", queue=queue,
        max_attempts=int(step.get("maxAttempts", 3)), timeout_seconds=float(step.get("timeoutSeconds", 60)),
        retryable_error_classes=list(step.get("retryableErrorClasses", DEFAULT_RETRYABLE_ERRORS)),
        required_evidence=list(step.get("requiredEvidence", [])))


def sample_evidence_handler(payload: dict[str, Any], context: TaskContext) -> dict[str, Any]:
    """Demo-only handler: emits evidence descriptors with demo:// URIs, not real artifacts."""
    items = []
    for evidence_type in context.required_evidence:
        material = _canonical_json({"taskId": context.task_id, "type": evidence_type, "demo": True})
        items.append({"type": evidence_type, "uri": f"demo://{context.task_id}/{evidence_type}",
                      "sha256": _sha256(material), "createdAt": utc_iso(), "mediaType": "application/json"})
    return {"output": {"message": str(payload.get("message", "demo worker completed")), "demo": True,
                       "businessOperationId": payload.get("businessOperationId")}, "evidence": items}


def echo_handler(payload: dict[str, Any], context: TaskContext) -> dict[str, Any]:
    context.check_deadline()
    return {"output": {"echo": payload.get("message", "hello"), "taskId": context.task_id,
                       "idempotencyKey": context.idempotency_key, "demo": True}, "evidence": []}
