"""Durable content-addressed ontology snapshot registry with optimistic activation."""
from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any

from .ontology_versioning import canonical_json, ontology_digest


class OntologyRegistryError(RuntimeError):
    pass


class SQLiteOntologyRegistry:
    """SQLite-backed append-only snapshot catalog and mutable active-version pointer."""

    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)
        if self.db_path != ":memory:":
            Path(self.db_path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(self.db_path, timeout=10, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys=ON")
        if self.db_path != ":memory:":
            self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.executescript("""
            CREATE TABLE IF NOT EXISTS ontology_snapshots (
                snapshot_id TEXT PRIMARY KEY,
                ontology_id TEXT NOT NULL,
                ontology_version TEXT NOT NULL,
                schema_version TEXT NOT NULL,
                digest TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL,
                created_by TEXT NOT NULL,
                reason TEXT NOT NULL,
                snapshot_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS ontology_active_pointers (
                ontology_id TEXT PRIMARY KEY,
                snapshot_id TEXT NOT NULL,
                activated_at TEXT NOT NULL,
                activated_by TEXT NOT NULL,
                approval_ref TEXT NOT NULL,
                proposal_id TEXT,
                previous_snapshot_id TEXT,
                FOREIGN KEY(snapshot_id) REFERENCES ontology_snapshots(snapshot_id)
            );
            CREATE TABLE IF NOT EXISTS ontology_registry_events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                ontology_id TEXT NOT NULL,
                snapshot_id TEXT NOT NULL,
                action TEXT NOT NULL,
                actor TEXT NOT NULL,
                approval_ref TEXT,
                proposal_id TEXT,
                occurred_at TEXT NOT NULL,
                payload_json TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_ontology_registry_events_ontology
              ON ontology_registry_events(ontology_id, event_id);
            CREATE TRIGGER IF NOT EXISTS ontology_snapshots_no_update
              BEFORE UPDATE ON ontology_snapshots BEGIN
                SELECT RAISE(ABORT, 'ontology snapshots are immutable');
              END;
            CREATE TRIGGER IF NOT EXISTS ontology_snapshots_no_delete
              BEFORE DELETE ON ontology_snapshots BEGIN
                SELECT RAISE(ABORT, 'ontology snapshots are immutable');
              END;
            CREATE TRIGGER IF NOT EXISTS ontology_registry_events_no_update
              BEFORE UPDATE ON ontology_registry_events BEGIN
                SELECT RAISE(ABORT, 'ontology registry events are append-only');
              END;
            CREATE TRIGGER IF NOT EXISTS ontology_registry_events_no_delete
              BEFORE DELETE ON ontology_registry_events BEGIN
                SELECT RAISE(ABORT, 'ontology registry events are append-only');
              END;
        """)
        self._connection.commit()

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()

    def register_snapshot(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        ontology = snapshot.get("ontology")
        if not isinstance(ontology, dict):
            raise OntologyRegistryError("snapshot ontology must be an object")
        digest = ontology_digest(ontology)
        if digest != snapshot.get("digest"):
            raise OntologyRegistryError("snapshot digest does not match ontology content")
        snapshot_id = str(snapshot.get("snapshotId", ""))
        if snapshot_id != "ont-" + digest[:16]:
            raise OntologyRegistryError("snapshot ID does not match content digest")
        required = ("ontologyId", "ontologyVersion", "schemaVersion", "createdAt", "actor", "reason")
        if any(not str(snapshot.get(key, "")).strip() for key in required):
            raise OntologyRegistryError("snapshot metadata is incomplete")
        payload = canonical_json(snapshot)
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                inserted = self._connection.execute(
                    "INSERT OR IGNORE INTO ontology_snapshots(snapshot_id,ontology_id,ontology_version,schema_version,digest,created_at,created_by,reason,snapshot_json) VALUES(?,?,?,?,?,?,?,?,?)",
                    (snapshot_id, str(snapshot["ontologyId"]), str(snapshot["ontologyVersion"]),
                     str(snapshot["schemaVersion"]), digest, str(snapshot["createdAt"]),
                     str(snapshot["actor"]), str(snapshot["reason"]), payload),
                ).rowcount == 1
                row = self._connection.execute(
                    "SELECT digest,snapshot_json FROM ontology_snapshots WHERE snapshot_id=?", (snapshot_id,)
                ).fetchone()
                if row is None or row["digest"] != digest:
                    raise OntologyRegistryError("snapshot ID collision")
                stored = json.loads(row["snapshot_json"])
                if ontology_digest(stored.get("ontology", {})) != digest:
                    raise OntologyRegistryError("stored snapshot integrity check failed")
                if inserted:
                    self._connection.execute(
                        "INSERT INTO ontology_registry_events(ontology_id,snapshot_id,action,actor,approval_ref,proposal_id,occurred_at,payload_json) VALUES(?,?,?,?,?,?,?,?)",
                        (str(snapshot["ontologyId"]), snapshot_id, "snapshot-registered", str(snapshot["actor"]), None, None,
                         str(snapshot["createdAt"]), json.dumps({"digest": digest, "ontologyVersion": snapshot["ontologyVersion"]}, ensure_ascii=False)),
                    )
                self._connection.commit()
            except Exception:
                self._connection.rollback()
                raise
        return {"snapshotId": snapshot_id, "digest": digest, "created": inserted}

    def get_snapshot(self, snapshot_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT snapshot_json FROM ontology_snapshots WHERE snapshot_id=?", (snapshot_id,)
            ).fetchone()
        if row is None:
            return None
        value = json.loads(row["snapshot_json"])
        if ontology_digest(value.get("ontology", {})) != value.get("digest"):
            raise OntologyRegistryError("snapshot integrity check failed")
        return value

    def list_snapshots(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT snapshot_id,ontology_id,ontology_version,schema_version,digest,created_at,created_by,reason "
                "FROM ontology_snapshots ORDER BY created_at DESC LIMIT ?", (max(1, min(int(limit), 500)),)
            ).fetchall()
        return [{
            "snapshotId": row["snapshot_id"], "ontologyId": row["ontology_id"],
            "ontologyVersion": row["ontology_version"], "schemaVersion": row["schema_version"],
            "digest": row["digest"], "createdAt": row["created_at"],
            "actor": row["created_by"], "reason": row["reason"],
        } for row in rows]

    def get_active_pointer(self, ontology_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT ontology_id,snapshot_id,activated_at,activated_by,approval_ref,proposal_id,previous_snapshot_id "
                "FROM ontology_active_pointers WHERE ontology_id=?", (ontology_id,)
            ).fetchone()
        return dict(row) if row else None

    def import_legacy_active(self, ontology_id: str, snapshot_id: str, *, imported_by: str = "legacy-state-migration") -> bool:
        snapshot = self.get_snapshot(snapshot_id)
        if snapshot is None:
            raise OntologyRegistryError("legacy active snapshot is not registered")
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                existing = self._connection.execute(
                    "SELECT snapshot_id FROM ontology_active_pointers WHERE ontology_id=?", (ontology_id,)
                ).fetchone()
                if existing:
                    self._connection.rollback()
                    return False
                occurred = snapshot.get("createdAt", "")
                self._connection.execute(
                    "INSERT INTO ontology_active_pointers VALUES(?,?,?,?,?,?,?)",
                    (ontology_id, snapshot_id, occurred, imported_by, "legacy-state-import", None, None),
                )
                self._connection.execute(
                    "INSERT INTO ontology_registry_events(ontology_id,snapshot_id,action,actor,approval_ref,proposal_id,occurred_at,payload_json) VALUES(?,?,?,?,?,?,?,?)",
                    (ontology_id, snapshot_id, "legacy-import", imported_by, "legacy-state-import", None, occurred, "{}"),
                )
                self._connection.commit()
                return True
            except Exception:
                self._connection.rollback()
                raise

    def activate_snapshot(
        self,
        snapshot_id: str,
        *,
        ontology_id: str,
        expected_active_snapshot_id: str | None,
        actor: str,
        approval_ref: str,
        proposal_id: str,
        occurred_at: str,
    ) -> dict[str, Any]:
        if not actor.strip() or not approval_ref.strip() or not proposal_id.strip():
            raise OntologyRegistryError("actor, approval reference and proposal ID are required")
        snapshot = self.get_snapshot(snapshot_id)
        if snapshot is None or snapshot.get("ontologyId") != ontology_id:
            raise OntologyRegistryError("target snapshot is not registered for this ontology")
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                row = self._connection.execute(
                    "SELECT snapshot_id FROM ontology_active_pointers WHERE ontology_id=?", (ontology_id,)
                ).fetchone()
                current = row["snapshot_id"] if row else None
                if current != expected_active_snapshot_id:
                    raise OntologyRegistryError("active snapshot changed concurrently; create a fresh proposal")
                self._connection.execute(
                    "INSERT INTO ontology_active_pointers(ontology_id,snapshot_id,activated_at,activated_by,approval_ref,proposal_id,previous_snapshot_id) "
                    "VALUES(?,?,?,?,?,?,?) ON CONFLICT(ontology_id) DO UPDATE SET "
                    "snapshot_id=excluded.snapshot_id,activated_at=excluded.activated_at,activated_by=excluded.activated_by,"
                    "approval_ref=excluded.approval_ref,proposal_id=excluded.proposal_id,previous_snapshot_id=excluded.previous_snapshot_id",
                    (ontology_id, snapshot_id, occurred_at, actor[:100], approval_ref[:200], proposal_id, current),
                )
                self._connection.execute(
                    "INSERT INTO ontology_registry_events(ontology_id,snapshot_id,action,actor,approval_ref,proposal_id,occurred_at,payload_json) VALUES(?,?,?,?,?,?,?,?)",
                    (ontology_id, snapshot_id, "activate", actor[:100], approval_ref[:200], proposal_id, occurred_at,
                     json.dumps({"previousSnapshotId": current}, ensure_ascii=False)),
                )
                self._connection.commit()
                return {"ontologyId": ontology_id, "snapshotId": snapshot_id, "previousSnapshotId": current,
                        "activatedAt": occurred_at, "activatedBy": actor[:100], "approvalRef": approval_ref[:200],
                        "proposalId": proposal_id}
            except Exception:
                self._connection.rollback()
                raise

    def list_events(self, ontology_id: str, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT event_id,snapshot_id,action,actor,approval_ref,proposal_id,occurred_at,payload_json "
                "FROM ontology_registry_events WHERE ontology_id=? ORDER BY event_id DESC LIMIT ?",
                (ontology_id, max(1, min(int(limit), 500))),
            ).fetchall()
        return [{
            "eventId": row["event_id"], "snapshotId": row["snapshot_id"], "action": row["action"],
            "actor": row["actor"], "approvalRef": row["approval_ref"], "proposalId": row["proposal_id"],
            "occurredAt": row["occurred_at"], "payload": json.loads(row["payload_json"]),
        } for row in reversed(rows)]
