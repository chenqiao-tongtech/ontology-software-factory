"""P1 governance primitives: independent tool approvals, invocation idempotency and evidence provenance.

SQLite-backed local reference implementation. Production deployments should use a shared
transactional database and a trusted identity provider; actor strings are not authentication.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Callable


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def payload_digest(payload: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


class ApprovalError(PermissionError):
    pass


class ApprovalStore:
    """Persist approvals bound to the exact Run/Task/Tenant/Tool/payload digest."""

    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.db_path, timeout=10, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys=ON")
        if self.db_path != ":memory:":
            self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("""CREATE TABLE IF NOT EXISTS tool_approvals (
            approval_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, task_id TEXT NOT NULL,
            tenant_id TEXT NOT NULL, tool_id TEXT NOT NULL, payload_sha256 TEXT NOT NULL,
            requested_by TEXT NOT NULL, requested_at REAL NOT NULL, expires_at REAL NOT NULL,
            status TEXT NOT NULL, decided_by TEXT, decided_at REAL, reason TEXT,
            consumed_at REAL
        )""")
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_tool_approvals_binding ON tool_approvals(run_id,task_id,tool_id,status)")
        self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def request(self, *, approval_id: str, run_id: str, task_id: str, tenant_id: str,
                tool_id: str, payload: dict[str, Any], requested_by: str,
                ttl_seconds: int = 900, now: float | None = None) -> dict[str, Any]:
        actor = str(requested_by).strip()
        if not all(str(x).strip() for x in (approval_id, run_id, task_id, tenant_id, tool_id, actor)):
            raise ApprovalError("approval binding fields and requester are required")
        if not 1 <= int(ttl_seconds) <= 86400:
            raise ApprovalError("approval TTL must be between 1 and 86400 seconds")
        current = time.time() if now is None else float(now)
        digest = payload_digest(payload)
        with self._lock:
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                self._conn.execute("""INSERT INTO tool_approvals
                    (approval_id,run_id,task_id,tenant_id,tool_id,payload_sha256,requested_by,
                     requested_at,expires_at,status) VALUES(?,?,?,?,?,?,?,?,?,'pending')""",
                    (approval_id, run_id, task_id, tenant_id, tool_id, digest, actor,
                     current, current + int(ttl_seconds)))
                self._conn.commit()
            except sqlite3.IntegrityError as exc:
                self._conn.rollback()
                raise ApprovalError("approval ID already exists") from exc
            except Exception:
                self._conn.rollback()
                raise
        return self.get(approval_id)  # type: ignore[return-value]

    def get(self, approval_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM tool_approvals WHERE approval_id=?", (approval_id,)).fetchone()
        return self._as_dict(row) if row else None

    @staticmethod
    def _as_dict(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "approvalId": row["approval_id"], "runId": row["run_id"], "taskId": row["task_id"],
            "tenantId": row["tenant_id"], "toolId": row["tool_id"], "payloadSha256": row["payload_sha256"],
            "requestedBy": row["requested_by"], "requestedAt": row["requested_at"],
            "expiresAt": row["expires_at"], "status": row["status"], "decidedBy": row["decided_by"],
            "decidedAt": row["decided_at"], "reason": row["reason"], "consumedAt": row["consumed_at"],
        }

    def decide(self, approval_id: str, *, decision: str, actor: str, reason: str,
               now: float | None = None) -> dict[str, Any]:
        if decision not in {"approved", "rejected"}:
            raise ApprovalError("decision must be approved or rejected")
        actor, reason = str(actor).strip(), str(reason).strip()
        if not actor or not reason:
            raise ApprovalError("approver and auditable reason are required")
        current = time.time() if now is None else float(now)
        with self._lock:
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                row = self._conn.execute("SELECT * FROM tool_approvals WHERE approval_id=?", (approval_id,)).fetchone()
                if row is None or row["status"] != "pending":
                    self._conn.rollback()
                    raise ApprovalError("pending approval record not found")
                if row["expires_at"] <= current:
                    self._conn.execute("UPDATE tool_approvals SET status='expired' WHERE approval_id=?", (approval_id,))
                    self._conn.commit()
                    raise ApprovalError("approval request has expired")
                if actor.casefold() == row["requested_by"].casefold():
                    self._conn.rollback()
                    raise ApprovalError("requester cannot approve their own tool invocation")
                self._conn.execute("""UPDATE tool_approvals SET status=?,decided_by=?,decided_at=?,reason=?
                    WHERE approval_id=? AND status='pending'""",
                    (decision, actor, current, reason, approval_id))
                self._conn.commit()
            except ApprovalError:
                raise
            except Exception:
                self._conn.rollback()
                raise
        return self.get(approval_id)  # type: ignore[return-value]

    def consume(self, approval_id: str, *, run_id: str, task_id: str, tenant_id: str,
                tool_id: str, payload: dict[str, Any], executor: str,
                now: float | None = None) -> dict[str, Any]:
        """Atomically validate and consume an approval exactly once before dispatch."""
        current = time.time() if now is None else float(now)
        digest = payload_digest(payload)
        with self._lock:
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                row = self._conn.execute("SELECT * FROM tool_approvals WHERE approval_id=?", (approval_id,)).fetchone()
                if row is None:
                    raise ApprovalError("approval record does not exist")
                expected = (run_id, task_id, tenant_id, tool_id, digest)
                actual = (row["run_id"], row["task_id"], row["tenant_id"], row["tool_id"], row["payload_sha256"])
                if actual != expected:
                    raise ApprovalError("approval binding does not match this invocation")
                if row["status"] != "approved" or row["consumed_at"] is not None:
                    raise ApprovalError("approval is not approved or has already been consumed")
                if row["expires_at"] <= current:
                    self._conn.execute("UPDATE tool_approvals SET status='expired' WHERE approval_id=?", (approval_id,))
                    self._conn.commit()
                    raise ApprovalError("approval has expired")
                if not executor or executor.casefold() in {row["requested_by"].casefold(), str(row["decided_by"]).casefold()}:
                    raise ApprovalError("executor must be distinct from requester and approver")
                self._conn.execute("UPDATE tool_approvals SET consumed_at=? WHERE approval_id=? AND consumed_at IS NULL",
                                   (current, approval_id))
                self._conn.commit()
            except ApprovalError:
                if self._conn.in_transaction:
                    self._conn.rollback()
                raise
            except Exception:
                self._conn.rollback()
                raise
        return self.get(approval_id)  # type: ignore[return-value]


class InvocationError(RuntimeError):
    pass


class SQLiteInvocationLedger:
    """At-most-once dispatch gate; 'started' records fail closed after process crashes."""

    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.db_path, timeout=10, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        if self.db_path != ":memory:":
            self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("""CREATE TABLE IF NOT EXISTS tool_invocations (
            idempotency_key TEXT PRIMARY KEY, run_id TEXT NOT NULL, task_id TEXT NOT NULL,
            tool_id TEXT NOT NULL, payload_sha256 TEXT NOT NULL, status TEXT NOT NULL,
            result_json TEXT, result_sha256 TEXT, created_at REAL NOT NULL, updated_at REAL NOT NULL
        )""")
        self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def begin(self, *, key: str, run_id: str, task_id: str, tool_id: str,
              payload: dict[str, Any], now: float | None = None) -> tuple[bool, Any]:
        if not key or len(key) > 200:
            raise InvocationError("idempotency key must contain 1..200 characters")
        current = time.time() if now is None else float(now)
        digest = payload_digest(payload)
        with self._lock:
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                row = self._conn.execute("SELECT * FROM tool_invocations WHERE idempotency_key=?", (key,)).fetchone()
                if row:
                    binding = (row["run_id"], row["task_id"], row["tool_id"], row["payload_sha256"])
                    if binding != (run_id, task_id, tool_id, digest):
                        raise InvocationError("idempotency key was reused with a different invocation")
                    if row["status"] == "completed":
                        result = json.loads(row["result_json"])
                        self._conn.commit()
                        return False, result
                    raise InvocationError("invocation is already started or requires reconciliation; refusing duplicate dispatch")
                self._conn.execute("""INSERT INTO tool_invocations
                    (idempotency_key,run_id,task_id,tool_id,payload_sha256,status,created_at,updated_at)
                    VALUES(?,?,?,?,?,'started',?,?)""",
                    (key, run_id, task_id, tool_id, digest, current, current))
                self._conn.commit()
                return True, None
            except InvocationError:
                if self._conn.in_transaction:
                    self._conn.rollback()
                raise
            except Exception:
                self._conn.rollback()
                raise

    def complete(self, key: str, result: Any, *, now: float | None = None) -> None:
        current = time.time() if now is None else float(now)
        encoded = canonical_json(result)
        digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        with self._lock:
            cur = self._conn.execute("""UPDATE tool_invocations SET status='completed',result_json=?,
                result_sha256=?,updated_at=? WHERE idempotency_key=? AND status='started'""",
                (encoded, digest, current, key))
            self._conn.commit()
            if cur.rowcount != 1:
                raise InvocationError("cannot complete an invocation that is not started")

    def fail(self, key: str, *, now: float | None = None) -> None:
        current = time.time() if now is None else float(now)
        with self._lock:
            self._conn.execute("UPDATE tool_invocations SET status='failed',updated_at=? WHERE idempotency_key=? AND status='started'",
                               (current, key))
            self._conn.commit()


class ToolGateway:
    """Single local invocation boundary for tools; adapters are registered as trusted handlers."""

    def __init__(self, harness: Any, ledger: SQLiteInvocationLedger):
        self.harness = harness
        self.ledger = ledger

    def invoke(self, principal: Any, *, run_id: str, task_id: str, tool_id: str,
               payload: dict[str, Any], idempotency_key: str, approval_ref: str | None = None) -> Any:
        dispatch, cached = self.ledger.begin(
            key=idempotency_key, run_id=run_id, task_id=task_id, tool_id=tool_id, payload=payload
        )
        if not dispatch:
            return cached
        try:
            result = self.harness.invoke_tool(
                principal, run_id=run_id, task_id=task_id, tool_id=tool_id,
                payload=payload, approval_ref=approval_ref, idempotency_key=idempotency_key,
            )
            try:
                self.ledger.complete(idempotency_key, result)
            except (TypeError, ValueError):
                # Non-JSON tool results cannot be safely replayed; retain fail-closed started state.
                raise InvocationError("tool result is not JSON serializable; manual reconciliation required")
            return result
        except Exception:
            self.ledger.fail(idempotency_key)
            raise


class EvidenceContractError(ValueError):
    pass


def validate_evidence_contract(contract: dict[str, Any], evidence: list[dict[str, Any]]) -> None:
    """Validate provenance fields when a task opts into versioned evidence contracts."""
    required = ("contractVersion", "runId", "taskId", "inputSha256", "toolVersion", "exitCode", "reportSha256")
    missing = [key for key in required if key not in contract]
    if missing:
        raise EvidenceContractError(f"evidence contract missing fields: {missing}")
    for key in ("inputSha256", "reportSha256"):
        value = str(contract[key]).lower()
        if len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value):
            raise EvidenceContractError(f"{key} must be a SHA-256 hex digest")
    if not isinstance(contract["exitCode"], int):
        raise EvidenceContractError("exitCode must be an integer")
    if not isinstance(evidence, list) or not evidence:
        raise EvidenceContractError("versioned evidence contract requires at least one evidence item")
    matched = False
    for index, item in enumerate(evidence):
        if not isinstance(item, dict):
            raise EvidenceContractError(f"evidence[{index}] must be an object")
        provenance = item.get("provenance")
        if not isinstance(provenance, dict):
            raise EvidenceContractError(f"evidence[{index}] requires provenance")
        for key in ("runId", "taskId", "inputSha256", "toolVersion", "exitCode", "reportSha256"):
            if provenance.get(key) != contract[key]:
                raise EvidenceContractError(f"evidence[{index}] provenance mismatch for {key}")
        matched = True
    if not matched:
        raise EvidenceContractError("no evidence item matches the declared contract")
