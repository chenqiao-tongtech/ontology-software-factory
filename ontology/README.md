# Ontology

`software-factory-ontology.json` is the first machine-readable business vocabulary: classes, relationships, controlled vocabularies, ID conventions and MVP invariants. It is a lightweight catalogue, not a formal OWL ontology or a security policy. Any changes should be reviewed together with JSON Schema, semantic validators, examples and tests.


## Logical modules

`module-manifest.json` partitions all canonical ontology classes and relations into versioned logical modules. `schemas/module-manifest.schema.json` validates the manifest shape, and `make ontology-modules` verifies complete, unique class/relation coverage and relation endpoints.

The manifest is not an alternative definition store. Class and relation definitions remain authoritative in `software-factory-ontology.json`. Moving to independently versioned module files requires a future deterministic composition, dependency-lock and publication pipeline.

The current canonical ontology is version `1.1.0`; the operational extension catalogue is version `1.2.0`.
