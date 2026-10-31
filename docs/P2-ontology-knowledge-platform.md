# P2 Ontology and Knowledge Graph Platform — Delivery and Acceptance

## 1. Goal and boundary

P2 provides a local, runnable ontology and knowledge graph platform on top of the existing discovery, source connectors, governance, versioning and consumer-impact modules. It does not replace P1 Harness/Gateway controls and does not grant Agents write authority.

The platform separates four planes:
1. Source plane — read-only inventory and snapshots from repositories, documents, SQL schemas and API contracts.
2. Candidate plane — LLM-assisted terms, relations, constraints and competency questions with source evidence. Candidates are not executable ontology.
3. Ontology plane — reviewed, versioned canonical definitions and immutable snapshots. Runtime consumers pin a snapshot digest.
4. Knowledge plane — instance entities and relation facts, each tied to a tenant, source provenance and an ontology snapshot.

## 2. Implemented capabilities

| Capability | Implementation | Boundary |
|---|---|---|
| Ontology definition | Canonical JSON + logical module manifest | Manifest is an index, not a second source of truth |
| Discovery | Structured LLM pipeline + deterministic validation + critic; local deterministic extraction | Produces review candidates only |
| Source ingestion | Local repository/document + SQLite/PostgreSQL/MySQL schema connectors; GitHub/GitLab metadata adapters; API contract connector | Live systems require explicit credentials and network configuration |
| Incremental sync | Asset manifest diff, source revision metadata, GitHub/GitLab webhook verification and delivery dedupe | Deletion known only when both scans are complete; metadata fingerprints are not content hashes |
| Governance | Candidate digest approval, change proposal, version snapshots, promotion/rollback proposals and structural diff | Portal state is local JSON; actor strings are not enterprise IAM identities |
| Consumer impact | Explicit typed dependency graph for Roles, Skills, Workflows, Tools and schemas | Implicit prose dependencies may be missed |
| Runtime binding | Snapshot digest and role/skill contract checks | Consumers must explicitly use the binding |
| Ontology visualization | Portal SVG ontology-definition graph, focus/filter and inspector | Visualizes definitions and registered consumers |
| Knowledge graph instances | SQLite KnowledgeGraphStore, Portal API and instance explorer | Local single-node reference backend; one-hop neighborhood |
| Provenance | Source ID, locator, content SHA-256 on entity and relation records | Hash proves supplied bytes, not source authenticity or truth |

## 3. Architecture and safety contract

### Discovery and evidence
Every discovered term/relation/constraint should cite source fragments. Evidence references are checked against submitted material by the discovery pipeline. Model confidence is a triage hint, never a truth probability or publication authorization.

### Ontology lifecycle
A snapshot is immutable and carries ontology ID/version, schema version, deterministic digest, actor, reason and creation time. Promotion and rollback are explicit governance actions; a proposal requires independent approval and a distinct executor. In-flight consumers pin snapshot ID and digest.

### Knowledge graph
An entity has stable ID, tenant, class, properties, ontology snapshot binding and provenance. A relation has stable ID, type, endpoints, same tenant and snapshot binding, and provenance. Writes fail closed on unknown classes, relation types, endpoint type mismatch, missing endpoints, cross-tenant references or digest mismatch.

### Runtime integration
Agent/Skill/Workflow contracts consume approved ontology snapshots. Graph facts may enrich context but do not override policy, permissions, workflow state or human approval.

## 4. Knowledge graph Portal API

All endpoints are part of the local reference Portal. The server binds to loopback by default. Do not expose them to an untrusted network.

### Create/update an entity
```http
POST /api/knowledge-graph/entities
Content-Type: application/json

{
  "tenantId": "local-reference",
  "entityId": "product:demo",
  "entityType": "Product",
  "properties": {"name": "Demo Product"},
  "ontologySnapshotId": "ont-<snapshot-digest-prefix>",
  "source": {"sourceId": "repo:factory", "locator": "docs/domain-model.md", "content": "Product is a software product."},
  "actor": "local-operator"
}
```

If ontologySnapshotId is omitted, the active snapshot is used. The selected snapshot must exist in Portal snapshot history. Source content is hashed by the service; only digest, source ID and locator are persisted.

### Create/update a relation
```http
POST /api/knowledge-graph/relations
Content-Type: application/json

{
  "tenantId": "local-reference",
  "relationId": "product:demo/contains/component:api",
  "relationType": "containsComponent",
  "sourceEntityId": "product:demo",
  "targetEntityId": "component:api",
  "properties": {},
  "ontologySnapshotId": "ont-<snapshot-digest-prefix>",
  "source": {"sourceId": "repo:factory", "locator": "docs/domain-model.md", "content": "Product contains Component."},
  "actor": "local-operator"
}
```

Both endpoint entities must already exist in the same tenant and be bound to the same snapshot.

### Search and neighborhood
```http
GET /api/knowledge-graph/entities?tenantId=local-reference&q=demo&entityType=Product&limit=100
GET /api/knowledge-graph/entities/product%3Ademo/neighborhood?tenantId=local-reference&limit=100
```

Limits are 1–500. Search is a bounded substring search over serialized properties, not vector/semantic search. Neighborhood is one hop.

## 5. Local usage

Run python scripts/run_factory_portal.py and open http://127.0.0.1:8770. In the Ontology section, use the Knowledge Graph · Instance Explorer panel to filter entities by tenant, type and property text, then select an entity to inspect its one-hop graph and provenance.

The local graph database is stored at .local-portal/knowledge-graph.sqlite3. Do not commit real customer data or source text into this local state directory.

## 6. P2 validation in this branch

- Knowledge graph unit tests cover tenant scoping, snapshot digest checks, unknown classes, relation endpoint validation, missing/cross-tenant endpoints and provenance.
- Portal tests cover the presence of the instance explorer and its API wiring.
- First graph-store integration checkpoint: 387 tests passed, 2 skipped, 0 failures. Re-run CI after the latest Portal API/UI commits before treating the final branch state as validated.

## 7. Explicit production gap

- PostgreSQL/Neo4j/Neptune backend decision, migrations, concurrent writers, backup/restore and scale testing.
- Enterprise IAM/SSO and resource-level tenant/project authorization; current Portal is local-only and actor strings are self-reported.
- Durable release registry and transactional promotion across multiple service instances; current Portal governance history is local JSON state.
- Retained content-addressed source artifacts and independent authenticity/signature verification; current graph stores a digest and locator only.
- Full OWL/RDF reasoning, SHACL engine, SPARQL endpoint and semantic/vector retrieval.
- Multi-hop graph exploration, clustering, graph layout optimization and large-graph performance.
- Full e2e proof from live source webhook through discovery, independent approval, release, graph ingestion and Agent retrieval.

Do not interpret the local SQLite backend, local Portal approval or tenant partition key as a production security boundary.