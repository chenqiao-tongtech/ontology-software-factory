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
            CREATE TABLE IF NOT EXISTS factory_assignment_results (
                plan_id TEXT NOT NULL,
                assignment_id TEXT NOT NULL,
                run_id TEXT NOT NULL,
                task_id TEXT NOT NULL,
                status TEXT NOT NULL,
                output_json TEXT NOT NULL,
                evidence_json TEXT NOT NULL,
                error_json TEXT NOT NULL,
                event_id TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY(plan_id, assignment_id)
            );
            CREATE INDEX IF NOT EXISTS idx_factory_assignment_results_run
              ON factory_assignment_results(run_id, plan_id);
            CREATE TABLE IF NOT EXISTS factory_plan_approvals (
                plan_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, plan_digest TEXT NOT NULL,
                status TEXT NOT NULL, requested_at TEXT NOT NULL, decided_at TEXT, actor TEXT, reason TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_factory_plan_approvals_run
              ON factory_plan_approvals(run_id, requested_at);
            CREATE TABLE IF NOT EXISTS factory_plan_phases (
                plan_id TEXT NOT NULL, phase_id TEXT NOT NULL, run_id TEXT NOT NULL,
                status TEXT NOT NULL, started_at TEXT, finished_at TEXT,
                error_json TEXT NOT NULL DEFAULT '{}', updated_at TEXT NOT NULL,
                PRIMARY KEY(plan_id, phase_id)
            );
            CREATE INDEX IF NOT EXISTS idx_factory_plan_phases_run
              ON factory_plan_phases(run_id, plan_id);
            CREATE TABLE IF NOT EXISTS harness_run_usage (
                run_id TEXT PRIMARY KEY, tool_calls INTEGER NOT NULL DEFAULT 0,
                context_bytes INTEGER NOT NULL DEFAULT 0, input_tokens INTEGER NOT NULL DEFAULT 0,
                output_tokens INTEGER NOT NULL DEFAULT 0, updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS harness_usage_events (
                event_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, task_id TEXT NOT NULL,
                event_type TEXT NOT NULL, occurred_at TEXT NOT NULL, policy_version TEXT NOT NULL,
                provider TEXT, model TEXT, tool_id TEXT, input_tokens INTEGER NOT NULL DEFAULT 0,
                output_tokens INTEGER NOT NULL DEFAULT 0, tool_calls INTEGER NOT NULL DEFAULT 0,
                context_bytes INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL, metadata_json TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_harness_usage_events_run
              ON harness_usage_events(run_id, occurred_at);
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
                self._conn.execute(
                    "INSERT INTO factory_plan_approvals(plan_id,run_id,plan_digest,status,requested_at) VALUES(?,?,?,'pending',?)",
                    (plan_id, run_id, digest, event["at"]),
                )
                for phase in plan.get("phases", []):
                    self._conn.execute(
                        "INSERT INTO factory_plan_phases(plan_id,phase_id,run_id,status,updated_at) VALUES(?,?,?,'pending',?)",
                        (plan_id, phase["phaseId"], run_id, event["at"]),
                    )
                self._conn.execute(
                    "INSERT INTO factory_plan_approvals(plan_id,run_id,plan_digest,status,requested_at) VALUES(?,?,?,'pending',?)",
                    (plan_id, run_id, digest, event["at"]),
                )
                for phase in plan.get("phases", []):
                    self._conn.execute(
                        "INSERT INTO factory_plan_phases(plan_id,phase_id,run_id,status,updated_at) VALUES(?,?,?,'pending',?)",
                        (plan_id, phase["phaseId"], run_id, event["at"]),
                    )
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

    def get_factory_plan_approval(self, plan_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT plan_id,run_id,plan_digest,status,requested_at,decided_at,actor,reason "
                "FROM factory_plan_approvals WHERE plan_id=?", (plan_id,)
            ).fetchone()
        if row is None:
            return None
        return {
            "planId": row["plan_id"], "workflowRunId": row["run_id"],
            "planDigest": row["plan_digest"], "status": row["status"],
            "requestedAt": row["requested_at"], "decidedAt": row["decided_at"],
            "actor": row["actor"], "reason": row["reason"],
        }

    def list_factory_plan_approvals(self, run_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT plan_id,run_id,plan_digest,status,requested_at,decided_at,actor,reason "
                "FROM factory_plan_approvals WHERE run_id=? ORDER BY requested_at,plan_id", (run_id,)
            ).fetchall()
        return [{
            "planId": row["plan_id"], "workflowRunId": row["run_id"],
            "planDigest": row["plan_digest"], "status": row["status"],
            "requestedAt": row["requested_at"], "decidedAt": row["decided_at"],
            "actor": row["actor"], "reason": row["reason"],
        } for row in rows]

    def decide_factory_plan_approval(
        self, *, run_id: str, plan_id: str, decision: str, actor: str,
        reason: str, event: dict[str, Any],
    ) -> dict[str, Any]:
        if decision not in {"approved", "rejected"}:
            raise ValueError("approval decision must be approved or rejected")
        actor = str(actor).strip()
        reason = str(reason).strip()
        if not actor or actor == "factory-orchestrator":
            raise ValueError("an independent human or policy actor is required")
        if not reason:
            raise ValueError("approval decision requires an auditable reason")
        with self._lock:
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                row = self._conn.execute(
                    "SELECT run_id,plan_digest,status FROM factory_plan_approvals WHERE plan_id=?",
                    (plan_id,),
                ).fetchone()
                if row is None or row["run_id"] != run_id:
                    self._conn.rollback()
                    raise ValueError("plan approval record not found for this Workflow Run")
                if row["status"] != "pending":
                    self._conn.rollback()
                    raise ValueError(f"plan approval is already {row['status']}")
                self._conn.execute(
                    "UPDATE factory_plan_approvals SET status=?,decided_at=?,actor=?,reason=? WHERE plan_id=? AND status='pending'",
                    (decision, event["at"], actor, reason, plan_id),
                )
                self._insert_event(run_id, {
                    **event, "actor": actor,
                    "payload": {**event.get("payload", {}), "planId": plan_id,
                                "planDigest": row["plan_digest"], "decision": decision, "reason": reason},
                })
                self._conn.commit()
            except ValueError:
                raise
            except Exception:
                self._conn.rollback()
                raise
        result = self.get_factory_plan_approval(plan_id)
        assert result is not None
        return result

    def list_factory_plan_phases(self, run_id: str, plan_id: str | None = None) -> list[dict[str, Any]]:
        query = (
            "SELECT plan_id,phase_id,run_id,status,started_at,finished_at,error_json,updated_at "
            "FROM factory_plan_phases WHERE run_id=?"
        )
        params: tuple[Any, ...] = (run_id,)
        if plan_id is not None:
            query += " AND plan_id=?"
            params = (run_id, plan_id)
        query += " ORDER BY plan_id,phase_id"
        with self._lock:
            rows = self._conn.execute(query, params).fetchall()
        return [{
            "planId": row["plan_id"], "phaseId": row["phase_id"],
            "workflowRunId": row["run_id"], "status": row["status"],
            "startedAt": row["started_at"], "finishedAt": row["finished_at"],
            "error": json.loads(row["error_json"]), "updatedAt": row["updated_at"],
        } for row in rows]

    def mark_factory_phase_running(self, *, run_id: str, plan_id: str, phase_id: str,
                                   event: dict[str, Any]) -> bool:
        with self._lock:
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                row = self._conn.execute(
                    "SELECT status FROM factory_plan_phases WHERE plan_id=? AND phase_id=? AND run_id=?",
                    (plan_id, phase_id, run_id),
                ).fetchone()
                if row is None:
                    self._conn.rollback()
                    raise ValueError("unknown Factory Plan Phase")
                if row["status"] == "running":
                    self._conn.rollback()
                    return False
                if row["status"] != "pending":
                    self._conn.rollback()
                    raise ValueError(f"cannot start Factory Plan Phase from {row['status']}")
                self._conn.execute(
                    "UPDATE factory_plan_phases SET status='running',started_at=?,finished_at=NULL,error_json='{}',updated_at=? "
                    "WHERE plan_id=? AND phase_id=?",
                    (event["at"], event["at"], plan_id, phase_id),
                )
                self._insert_event(run_id, event)
                self._conn.commit()
                return True
            except ValueError:
                raise
            except Exception:
                self._conn.rollback()
                raise

    def record_harness_usage(
        self, *, event_id: str, run_id: str, task_id: str, event_type: str,
        policy_version: str, occurred_at: str, tool_calls: int = 0,
        context_bytes: int = 0, input_tokens: int = 0, output_tokens: int = 0,
        provider: str | None = None, model: str | None = None, tool_id: str | None = None,
        status: str = "recorded", metadata: dict[str, Any] | None = None,
        limits: dict[str, int] | None = None, enforce_limits: bool = False,
    ) -> dict[str, Any]:
        deltas = {
            "tool_calls": int(tool_calls), "context_bytes": int(context_bytes),
            "input_tokens": int(input_tokens), "output_tokens": int(output_tokens),
        }
        if any(value < 0 for value in deltas.values()):
            raise ValueError("Harness usage deltas must be non-negative")
        limits = limits or {}
        with self._lock:
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                existing = self._conn.execute(
                    "SELECT 1 FROM harness_usage_events WHERE event_id=?", (event_id,)
                ).fetchone()
                if existing:
                    self._conn.rollback()
                    return {"allowed": True, "usage": self.get_harness_usage(run_id)}
                row = self._conn.execute(
                    "SELECT tool_calls,context_bytes,input_tokens,output_tokens FROM harness_run_usage WHERE run_id=?",
                    (run_id,),
                ).fetchone()
                current = self._usage_row(row)
                proposed = {
                    "toolCalls": current["toolCalls"] + deltas["tool_calls"],
                    "contextBytes": current["contextBytes"] + deltas["context_bytes"],
                    "inputTokens": current["inputTokens"] + deltas["input_tokens"],
                    "outputTokens": current["outputTokens"] + deltas["output_tokens"],
                }
                over = [key for key, limit in limits.items()
                        if int(limit) >= 0 and proposed.get(key, 0) > int(limit)]
                allowed = not (enforce_limits and over)
                if allowed:
                    self._conn.execute(
                        """INSERT INTO harness_run_usage(run_id,tool_calls,context_bytes,input_tokens,output_tokens,updated_at)
                        VALUES(?,?,?,?,?,?) ON CONFLICT(run_id) DO UPDATE SET
                        tool_calls=excluded.tool_calls,context_bytes=excluded.context_bytes,
                        input_tokens=excluded.input_tokens,output_tokens=excluded.output_tokens,updated_at=excluded.updated_at""",
                        (run_id, proposed["toolCalls"], proposed["contextBytes"],
                         proposed["inputTokens"], proposed["outputTokens"], occurred_at),
                    )
                self._conn.execute(
                    """INSERT INTO harness_usage_events(
                    event_id,run_id,task_id,event_type,occurred_at,policy_version,provider,model,tool_id,
                    input_tokens,output_tokens,tool_calls,context_bytes,status,metadata_json
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (event_id, run_id, task_id, event_type, occurred_at, policy_version,
                     provider, model, tool_id, deltas["input_tokens"], deltas["output_tokens"],
                     deltas["tool_calls"], deltas["context_bytes"],
                     "budget_exceeded" if over and enforce_limits else status,
                     json.dumps(metadata or {}, ensure_ascii=False, sort_keys=True)),
                )
                self._conn.commit()
                return {"allowed": allowed, "exceeded": over, "usage": proposed if allowed else current}
            except Exception:
                self._conn.rollback()
                raise

    @staticmethod
    def _usage_row(row: sqlite3.Row | None) -> dict[str, int]:
        if row is None:
            return {"toolCalls": 0, "contextBytes": 0, "inputTokens": 0, "outputTokens": 0}
        return {
            "toolCalls": int(row["tool_calls"]), "contextBytes": int(row["context_bytes"]),
            "inputTokens": int(row["input_tokens"]), "outputTokens": int(row["output_tokens"]),
        }

    def get_harness_usage(self, run_id: str) -> dict[str, int]:
        with self._lock:
            row = self._conn.execute(
                "SELECT tool_calls,context_bytes,input_tokens,output_tokens FROM harness_run_usage WHERE run_id=?",
                (run_id,),
            ).fetchone()
        return self._usage_row(row)

    def list_harness_usage_events(self, run_id: str, limit: int = 200) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT event_id,task_id,event_type,occurred_at,policy_version,provider,model,tool_id,"
                "input_tokens,output_tokens,tool_calls,context_bytes,status,metadata_json "
                "FROM harness_usage_events WHERE run_id=? ORDER BY occurred_at,event_id LIMIT ?",
                (run_id, max(1, min(int(limit), 1000))),
            ).fetchall()
        return [{
            "eventId": row["event_id"], "taskId": row["task_id"], "eventType": row["event_type"],
            "occurredAt": row["occurred_at"], "policyVersion": row["policy_version"],
            "provider": row["provider"], "model": row["model"], "toolId": row["tool_id"],
            "inputTokens": row["input_tokens"], "outputTokens": row["output_tokens"],
            "toolCalls": row["tool_calls"], "contextBytes": row["context_bytes"],
            "status": row["status"], "metadata": json.loads(row["metadata_json"]),
        } for row in rows]

    def record_factory_assignment_result(
        self, *, run_id: str, plan_id: str, assignment_id: str, task_id: str,
        status: str, output: dict[str, Any], evidence: list[dict[str, Any]],
        error: dict[str, Any], event_id: str, event: dict[str, Any],
    ) -> bool:
        """Atomically persist a Factory Assignment result, workflow event and inbox receipt."""
        if status not in {"succeeded", "failed", "dead_letter"}:
            raise ValueError("Factory Assignment result must be terminal")
        with self._lock:
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                seen = self._conn.execute(
                    "SELECT 1 FROM workflow_inbox WHERE integration_event_id=?", (event_id,)
                ).fetchone()
                if seen:
                    self._conn.rollback()
                    return False
                plan = self._conn.execute(
                    "SELECT 1 FROM factory_orchestrator_plans WHERE plan_id=? AND run_id=?",
                    (plan_id, run_id),
                ).fetchone()
                if plan is None:
                    self._conn.rollback()
                    raise ValueError("Factory Assignment result references an unknown plan or Workflow Run")
                self._conn.execute(
                    """INSERT INTO factory_assignment_results(
                        plan_id,assignment_id,run_id,task_id,status,output_json,evidence_json,error_json,event_id,updated_at
                    ) VALUES(?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(plan_id,assignment_id) DO UPDATE SET
                        task_id=excluded.task_id,status=excluded.status,output_json=excluded.output_json,
                        evidence_json=excluded.evidence_json,error_json=excluded.error_json,
                        event_id=excluded.event_id,updated_at=excluded.updated_at""",
                    (plan_id, assignment_id, run_id, task_id, status,
                     json.dumps(output, ensure_ascii=False), json.dumps(evidence, ensure_ascii=False),
                     json.dumps(error, ensure_ascii=False), event_id, event["at"]),
                )
                self._insert_event(run_id, event)
                self._conn.execute(
                    "INSERT INTO workflow_inbox(integration_event_id,run_id,action,processed_at) VALUES(?,?,?,?)",
                    (event_id, run_id, event["action"], event["at"]),
                )
                plan_row = self._conn.execute(
                    "SELECT payload_json FROM factory_orchestrator_plans WHERE plan_id=?", (plan_id,)
                ).fetchone()
                plan_payload = json.loads(plan_row["payload_json"]) if plan_row else {}
                phase_id = str(event.get("payload", {}).get("phaseId", ""))
                phase_payload = next((item for item in plan_payload.get("phases", [])
                                      if item.get("phaseId") == phase_id), None)
                if phase_payload:
                    statuses = []
                    for assignment in phase_payload.get("assignments", []):
                        status_row = self._conn.execute(
                            "SELECT status FROM factory_assignment_results WHERE plan_id=? AND assignment_id=?",
                            (plan_id, assignment["assignmentId"]),
                        ).fetchone()
                        statuses.append(status_row["status"] if status_row else "pending")
                    phase_status = (
                        "succeeded" if statuses and all(value == "succeeded" for value in statuses)
                        else "failed" if any(value in {"failed", "dead_letter"} for value in statuses)
                        else "running"
                    )
                    old_phase = self._conn.execute(
                        "SELECT status FROM factory_plan_phases WHERE plan_id=? AND phase_id=?",
                        (plan_id, phase_id),
                    ).fetchone()
                    if old_phase and old_phase["status"] != phase_status:
                        self._conn.execute(
                            "UPDATE factory_plan_phases SET status=?,finished_at=?,error_json=?,updated_at=? "
                            "WHERE plan_id=? AND phase_id=?",
                            (phase_status, event["at"],
                             json.dumps(error, ensure_ascii=False) if phase_status == "failed" else "{}",
                             event["at"], plan_id, phase_id),
                        )
                        self._insert_event(run_id, {
                            **event, "action": f"factory.phase.{phase_status}",
                            "summary": f"Factory Phase {phase_id} is {phase_status}",
                            "payload": {"planId": plan_id, "phaseId": phase_id,
                                        "assignmentStatuses": statuses},
                        })
                self._conn.commit()
                return True
            except Exception:
                self._conn.rollback()
                raise

    def list_factory_assignment_results(self, run_id: str, plan_id: str | None = None) -> list[dict[str, Any]]:
        query = (
            "SELECT plan_id,assignment_id,run_id,task_id,status,output_json,evidence_json,error_json,event_id,updated_at "
            "FROM factory_assignment_results WHERE run_id=?"
        )
        params: tuple[Any, ...] = (run_id,)
        if plan_id is not None:
            query += " AND plan_id=?"
            params = (run_id, plan_id)
        query += " ORDER BY updated_at,assignment_id"
        with self._lock:
            rows = self._conn.execute(query, params).fetchall()
        return [{
            "planId": row["plan_id"], "assignmentId": row["assignment_id"],
            "workflowRunId": row["run_id"], "taskId": row["task_id"],
            "status": row["status"], "output": json.loads(row["output_json"]),
            "evidence": json.loads(row["evidence_json"]), "error": json.loads(row["error_json"]),
            "eventId": row["event_id"], "updatedAt": row["updated_at"],
        } for row in rows]

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
