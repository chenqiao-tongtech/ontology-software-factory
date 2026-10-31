# P2 Ontology and Knowledge Graph Platform — Delivery and Acceptance

## 1. Goal and boundary

P2 turns the existing ontology discovery, governance, versioning, source inventory and Portal graph projection into a coherent ontology/knowledge platform. It does not replace P1 Harness/Gateway controls and does not grant Agents write authority.

The platform distinguishes four data planes:

1. **Source plane** — read-only inventory and snapshots from repositories, documents, SQL schemas and API contracts.
2. **Candidate plane** — LLM-assisted terms, relations, constraints and competency questions with verifiable source evidence. Candidates are not executable ontology.
3. **Ontology plane** — reviewed, versioned canonical definitions and immutable snapshots. Runtime consumers pin a snapshot digest.
4. **Knowledge plane** — instance entities and relation facts, each tied to a tenant, source provenance and an ontology snapshot.

## 2. Existing repository capabilities retained

| Capability | Current implementation | Boundary |
|---|---|---|
| Ontology definition | Canonical JSON + logical module manifest | Manifest is an index, not a second source of truth |
| Discovery | Structured LLM pipeline + deterministic validation + critic | Produces review candidates only |
| Source ingestion | Local repository/document + SQLite/PostgreSQL/MySQL schema connectors and optional adapters | Read-only metadata; live external systems require explicit credentials and network configuration |
| Governance | Candidate digest approval, change proposal, version snapshots and structural diff | CLI/local Portal approval is not enterprise IAM |
| Consumer impact | Explicit typed dependency graph for Roles, Skills, Workflows, Tools and schemas | Unregistered or implicit natural-language dependencies may be missed |
| Runtime binding | Snapshot digest and role/skill contract checks | Consumers must explicitly use the binding |
| Ontology visualization | Portal SVG graph projection and inspector | Read-only ontology view; not a general graph explorer |
| Knowledge graph instances | SQLite reference store added in P2 | Local single-node reference backend only |

## 3. P2 architecture contract

### Ontology metadata
Every published ontology snapshot must carry ontology ID, semantic version, schema version, deterministic digest, actor, reason and creation time. A consumer must pin the snapshot ID and digest; silently switching an in-flight run to a newer version is forbidden.

### Discovery and evidence
Every discovered term/relation/constraint must cite one or more source fragments. Evidence references must be checked against submitted source material. Model confidence is a triage hint, never a truth probability or publication authorization.

### Knowledge graph
An entity must have a stable ID, tenant, class, property object, ontology snapshot binding and provenance. A relation must have a stable ID, relation type, source and target entity, the same tenant and snapshot binding, and provenance. Writes fail closed on unknown classes, unknown relation types, endpoint type mismatch, missing endpoints, cross-tenant references or digest mismatch.

### Integration
Agent/Skill/Workflow contracts consume approved ontology snapshots. Knowledge graph queries may provide context, but retrieved facts remain evidence-bearing data and do not override policy, permissions, workflow state or human approval.

## 4. Implemented P2 increment in this branch

- Added KnowledgeGraphStore backed by SQLite.
- Added tenant-scoped entity and relation persistence.
- Added pinned ontology snapshot digest checks.
- Added class and relation endpoint type validation.
- Added provenance source ID, locator and content SHA-256.
- Added entity search and bounded one-hop neighborhood query.
- Added unit tests for tenant isolation, relation validation, tampered snapshots and provenance.
- Added usage and limitation documentation; linked it from README.

## 5. Acceptance checklist

### Automated checks in this branch
- [ ] All repository CI tests pass.
- [x] Reject unknown entity classes.
- [x] Reject unknown/tampered ontology snapshot bindings.
- [x] Reject relation endpoint class mismatch.
- [x] Reject missing/cross-tenant relation endpoints.
- [x] Persist source locator and source content digest.
- [x] Bound graph search and neighborhood result sizes.
- [x] Parameterize SQL values and tenant-scope graph queries.

### Remaining P2 exit criteria (not claimed complete)
- [ ] Run the new tests and full suite in GitHub Actions on this branch.
- [ ] Integrate graph query APIs into the Portal service and UI.
- [ ] Add visual graph interactions for instance graph: zoom/pan, neighborhood expansion, filters, clustering and large-graph handling.
- [ ] Add a durable ontology release registry and promotion transaction rather than relying on local Portal state/CLI artifacts.
- [ ] Add source revision/webhook sync, incremental scan and deletion/tombstone reconciliation.
- [ ] Add API contract, event-schema and additional enterprise source adapters with security review.
- [ ] Add PostgreSQL/Neo4j/Neptune production backend decision, migrations, backup/restore and concurrency tests.
- [ ] Add SHACL validation and optional RDF/OWL export/import round-trip tests.
- [ ] Add resource-level authorization and audit integration before exposing graph data to multiple users/tenants.
- [ ] Add graph retention, source content retention and provenance re-verification policy.
- [ ] Add end-to-end tests from source scan → candidate → human approval → ontology snapshot → graph ingest → Agent context retrieval.

## 6. Operational notes

The SQLite store is suitable for local development, demos and deterministic tests. It is not a horizontally scalable graph database, a multi-writer service or a security boundary. Do not expose it directly to untrusted clients. The tenant key is a data partition key; caller identity and tenant authorization must be enforced by the surrounding authenticated service.

The current graph search is a bounded substring search over serialized properties, not semantic vector search. Neighborhood queries are one-hop only. No inference, transitive closure or ontology reasoning is performed.
