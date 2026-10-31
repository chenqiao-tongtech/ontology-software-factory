# P2 Knowledge Graph Store

## Purpose
This increment adds a local SQLite reference store for graph facts. It complements the canonical ontology JSON and immutable snapshots, the discovery candidate/review pipeline, source connector inventory, consumer dependency graph, and the Portal ontology-definition graph.

The graph store holds instance data (entities and relation instances), not ontology definitions.

## Data model
Each entity is keyed by tenant ID and entity ID. Each relation records its type, endpoints, ontology snapshot ID/digest, properties and source provenance. Provenance contains source ID, locator and SHA-256 of the supplied source content. The digest identifies the bytes supplied at ingestion; it does not prove source authenticity, truth or future availability.

## Safety and consistency
- Writes require a complete snapshot with a matching canonical digest and snapshot ID.
- Entity classes and relation endpoint types must exist in the pinned ontology.
- Both relation endpoints must exist in the same tenant and use the same ontology snapshot.
- SQL is parameterized and tenant ID is included in primary keys and lookups.
- No arbitrary query language or SPARQL endpoint is exposed.
- This is a local SQLite reference implementation, not a distributed graph database or enterprise authorization boundary.

## Python usage
\`\`\`python
from ontology_software_factory.knowledge_graph import KnowledgeGraphStore
store = KnowledgeGraphStore(".local-portal/knowledge-graph.sqlite")
store.put_entity(tenant_id="tenant-a", entity_id="product:demo", entity_type="Product",
    properties={"name": "Demo"}, binding=approved_snapshot,
    source={"sourceId": "repo:factory", "locator": "docs/domain-model.md", "content": "Product"})
\`\`\`

## Deferred production work
PostgreSQL/Neo4j/Neptune adapters, graph migrations, full-text indexes, SHACL/OWL reasoning, SPARQL, distributed transactions, role/resource authorization, retained content-addressed source artifacts, graph streaming, collaborative editing and large-graph visualization remain future work.
