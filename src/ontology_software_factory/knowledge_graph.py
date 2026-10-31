"""Version-pinned, provenance-aware SQLite knowledge graph reference store."""
from __future__ import annotations
import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

class KnowledgeGraphError(ValueError):
    """A graph write or query violates the graph contract."""

def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()

def _classes(ontology: dict[str, Any]) -> set[str]:
    result = {str(x["name"]) for x in ontology.get("classes", []) if isinstance(x, dict) and x.get("name")}
    ext = ontology.get("operationalExtensions", {})
    if isinstance(ext, dict):
        result.update(str(x["name"]) for x in ext.get("classes", []) if isinstance(x, dict) and x.get("name"))
    return result

def _relations(ontology: dict[str, Any]) -> dict[str, set[tuple[str, str]]]:
    result: dict[str, set[tuple[str, str]]] = {}
    groups = [ontology.get("relations", [])]
    ext = ontology.get("operationalExtensions", {})
    if isinstance(ext, dict):
        groups.append(ext.get("relations", []))
    for group in groups:
        for item in group:
            if not isinstance(item, dict) or not item.get("name"):
                continue
            targets = item.get("target", [])
            if not isinstance(targets, list):
                targets = [targets]
            result.setdefault(str(item["name"]), set()).update(
                (str(item.get("source", "")), str(target)) for target in targets)
    return result

class KnowledgeGraphStore:
    """SQLite graph store with tenant partitioning and immutable ontology binding."""
    def __init__(self, database: str | Path):
        self.database = str(database)
        Path(self.database).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS graph_entities (
              tenant_id TEXT NOT NULL, entity_id TEXT NOT NULL, entity_type TEXT NOT NULL,
              snapshot_id TEXT NOT NULL, ontology_digest TEXT NOT NULL, properties_json TEXT NOT NULL,
              source_id TEXT NOT NULL, source_locator TEXT NOT NULL, source_digest TEXT NOT NULL,
              PRIMARY KEY (tenant_id, entity_id));
            CREATE TABLE IF NOT EXISTS graph_relations (
              tenant_id TEXT NOT NULL, relation_id TEXT NOT NULL, relation_type TEXT NOT NULL,
              source_entity_id TEXT NOT NULL, target_entity_id TEXT NOT NULL,
              snapshot_id TEXT NOT NULL, ontology_digest TEXT NOT NULL, properties_json TEXT NOT NULL,
              source_id TEXT NOT NULL, source_locator TEXT NOT NULL, source_digest TEXT NOT NULL,
              PRIMARY KEY (tenant_id, relation_id),
              FOREIGN KEY (tenant_id, source_entity_id) REFERENCES graph_entities(tenant_id, entity_id),
              FOREIGN KEY (tenant_id, target_entity_id) REFERENCES graph_entities(tenant_id, entity_id));
            CREATE INDEX IF NOT EXISTS idx_kg_entity_type ON graph_entities(tenant_id, entity_type);
            CREATE INDEX IF NOT EXISTS idx_kg_relation_source ON graph_relations(tenant_id, source_entity_id);
            CREATE INDEX IF NOT EXISTS idx_kg_relation_target ON graph_relations(tenant_id, target_entity_id);
            """)
    def _connect(self):
        db = sqlite3.connect(self.database, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        return db
    @staticmethod
    def _binding(binding: dict[str, Any]):
        ontology = binding.get("ontology")
        if not isinstance(ontology, dict):
            raise KnowledgeGraphError("complete pinned ontology snapshot is required")
        digest = _digest(ontology)
        if binding.get("digest") != digest or binding.get("snapshotId") != "ont-" + digest[:16]:
            raise KnowledgeGraphError("ontology snapshot digest or ID mismatch")
        return ontology, binding["snapshotId"], digest
    @staticmethod
    def _provenance(source: dict[str, Any]):
        source_id, locator, content = (str(source.get("sourceId", "")).strip(),
            str(source.get("locator", "")).strip(), source.get("content"))
        if not source_id or not locator or not isinstance(content, str) or not content:
            raise KnowledgeGraphError("sourceId, locator and non-empty source content are required")
        return source_id, locator, hashlib.sha256(content.encode("utf-8")).hexdigest()
    def put_entity(self, *, tenant_id: str, entity_id: str, entity_type: str,
                   properties: dict[str, Any], binding: dict[str, Any], source: dict[str, Any]):
        tenant_id, entity_id = str(tenant_id).strip(), str(entity_id).strip()
        if not tenant_id or not entity_id or not isinstance(properties, dict):
            raise KnowledgeGraphError("tenant_id, entity_id and object properties are required")
        ontology, snapshot_id, digest = self._binding(binding)
        if entity_type not in _classes(ontology):
            raise KnowledgeGraphError("unknown ontology class: " + str(entity_type))
        source_id, locator, source_digest = self._provenance(source)
        with self._connect() as db:
            db.execute("""INSERT INTO graph_entities VALUES (?,?,?,?,?,?,?,?,?)
              ON CONFLICT(tenant_id,entity_id) DO UPDATE SET entity_type=excluded.entity_type,
              snapshot_id=excluded.snapshot_id, ontology_digest=excluded.ontology_digest,
              properties_json=excluded.properties_json, source_id=excluded.source_id,
              source_locator=excluded.source_locator, source_digest=excluded.source_digest""",
              (tenant_id, entity_id, entity_type, snapshot_id, digest, _canonical(properties),
               source_id, locator, source_digest))
        return {"tenantId": tenant_id, "entityId": entity_id, "entityType": entity_type,
                "ontologySnapshotId": snapshot_id, "ontologyDigest": digest,
                "sourceId": source_id, "sourceLocator": locator, "sourceDigest": source_digest}
    def put_relation(self, *, tenant_id: str, relation_id: str, relation_type: str,
                     source_entity_id: str, target_entity_id: str, properties: dict[str, Any],
                     binding: dict[str, Any], source: dict[str, Any]):
        ontology, snapshot_id, digest = self._binding(binding)
        if (not relation_id or not isinstance(properties, dict) or
                (not str(tenant_id).strip())):
            raise KnowledgeGraphError("tenant, relation ID and object properties are required")
        if relation_type not in _relations(ontology):
            raise KnowledgeGraphError("unknown ontology relation: " + str(relation_type))
        source_id, locator, source_digest = self._provenance(source)
        with self._connect() as db:
            rows = db.execute("""SELECT entity_id,entity_type,snapshot_id,ontology_digest
                FROM graph_entities WHERE tenant_id=? AND entity_id IN (?,?)""",
                (tenant_id, source_entity_id, target_entity_id)).fetchall()
            entities = {r["entity_id"]: r for r in rows}
            if source_entity_id not in entities or target_entity_id not in entities:
                raise KnowledgeGraphError("both relation endpoints must exist in the same tenant")
            left, right = entities[source_entity_id], entities[target_entity_id]
            if (left["entity_type"], right["entity_type"]) not in _relations(ontology)[relation_type]:
                raise KnowledgeGraphError("relation endpoint types do not match ontology definition")
            for row in (left, right):
                if row["snapshot_id"] != snapshot_id or row["ontology_digest"] != digest:
                    raise KnowledgeGraphError("relation endpoints must use the same ontology snapshot")
            db.execute("""INSERT INTO graph_relations VALUES (?,?,?,?,?,?,?,?,?,?,?)
              ON CONFLICT(tenant_id,relation_id) DO UPDATE SET relation_type=excluded.relation_type,
              source_entity_id=excluded.source_entity_id,target_entity_id=excluded.target_entity_id,
              snapshot_id=excluded.snapshot_id,ontology_digest=excluded.ontology_digest,
              properties_json=excluded.properties_json,source_id=excluded.source_id,
              source_locator=excluded.source_locator,source_digest=excluded.source_digest""",
              (tenant_id, relation_id, relation_type, source_entity_id, target_entity_id,
               snapshot_id, digest, _canonical(properties), source_id, locator, source_digest))
        return {"tenantId": tenant_id, "relationId": relation_id, "relationType": relation_type,
                "sourceEntityId": source_entity_id, "targetEntityId": target_entity_id,
                "ontologySnapshotId": snapshot_id, "ontologyDigest": digest}
    def search_entities(self, *, tenant_id: str, entity_type: str | None = None,
                        text: str | None = None, limit: int = 100):
        if not 1 <= int(limit) <= 500:
            raise KnowledgeGraphError("limit must be between 1 and 500")
        clauses, params = ["tenant_id=?"], [tenant_id]
        if entity_type:
            clauses.append("entity_type=?"); params.append(entity_type)
        if text:
            clauses.append("lower(properties_json) LIKE ?"); params.append("%" + text.casefold() + "%")
        params.append(int(limit))
        with self._connect() as db:
            rows = db.execute("SELECT * FROM graph_entities WHERE " + " AND ".join(clauses) +
                              " ORDER BY entity_id LIMIT ?", params).fetchall()
        return [{"entityId": r["entity_id"], "entityType": r["entity_type"],
                 "properties": json.loads(r["properties_json"]), "ontologySnapshotId": r["snapshot_id"],
                 "provenance": {"sourceId": r["source_id"], "locator": r["source_locator"],
                                "sha256": r["source_digest"]}} for r in rows]
    def neighborhood(self, *, tenant_id: str, entity_id: str, limit: int = 100):
        if not 1 <= int(limit) <= 500:
            raise KnowledgeGraphError("limit must be between 1 and 500")
        with self._connect() as db:
            center = db.execute("SELECT * FROM graph_entities WHERE tenant_id=? AND entity_id=?",
                                (tenant_id, entity_id)).fetchone()
            if center is None:
                raise KnowledgeGraphError("entity not found in tenant")
            edges = db.execute("""SELECT * FROM graph_relations WHERE tenant_id=?
                AND (source_entity_id=? OR target_entity_id=?) ORDER BY relation_id LIMIT ?""",
                (tenant_id, entity_id, entity_id, int(limit))).fetchall()
            ids = {entity_id}
            for edge in edges:
                ids.update((edge["source_entity_id"], edge["target_entity_id"]))
            marks = ",".join("?" for _ in ids)
            nodes = db.execute("SELECT * FROM graph_entities WHERE tenant_id=? AND entity_id IN (" + marks + ")",
                               (tenant_id, *sorted(ids))).fetchall()
        return {"center": entity_id,
          "nodes": [{"entityId": r["entity_id"], "entityType": r["entity_type"],
                     "properties": json.loads(r["properties_json"]), "ontologySnapshotId": r["snapshot_id"],
                     "provenance": {"sourceId": r["source_id"], "locator": r["source_locator"],
                                    "sha256": r["source_digest"]}} for r in nodes],
          "edges": [{"relationId": r["relation_id"], "relationType": r["relation_type"],
                     "source": r["source_entity_id"], "target": r["target_entity_id"],
                     "properties": json.loads(r["properties_json"]),
                     "provenance": {"sourceId": r["source_id"], "locator": r["source_locator"],
                                    "sha256": r["source_digest"]}} for r in edges]}
