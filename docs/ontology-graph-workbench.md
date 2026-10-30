# Ontology Graph Workbench

## Interaction model

The Factory Portal ontology graph supports:

- text search over class names, descriptions and relation names/endpoints;
- selecting a class node to inspect its definition and incoming/outgoing relations;
- selecting a directed relation to inspect its source/target, field, cardinality and validation;
- **聚焦邻域** to show the selected class and its directly connected classes;
- **仅核心类** to hide operational extension classes;
- **重置视图** to clear selection and filters.

The graph remains a read-only projection of the formal ontology JSON. It does not edit the formal ontology.

## Provenance and impact context

When a selected class has a same-name term in a locally stored ontology candidate, the inspector shows the candidate's source evidence, including source name, locator, revision and a safe browser link when available.

The inspector also shows registered consumers from the repository consumer-reference graph, including Agent Roles, Skills, Workflows and other indexed consumers. This is a reference index: an unregistered consumer will not appear, and absence from the graph is not proof that no downstream dependency exists.

## Validation

Start the local Portal:

```bash
python scripts/run_factory_portal.py
```

Open the ontology view and verify:
1. Search filters the graph.
2. Select a class and activate **聚焦邻域**; only the selected class and direct neighbors remain.
3. Activate **仅核心类**; operational extension nodes are hidden.
4. Select a relation edge; the inspector shows relation metadata.
5. Select a class with candidate evidence; source provenance appears.
6. Select a class with registered consumers; downstream consumer references appear.
7. Reset restores the full graph.

## Current limits

The current layout is a deterministic radial layout in an SVG viewport. This increment adds useful focus and inspection interactions, not a general-purpose graph database UI. Large-scale force-directed layout, zoom/pan, clustering, graph virtualization, collaborative annotation, access-controlled editing and live change streaming remain future work.
