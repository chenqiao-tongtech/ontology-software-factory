# Contracts

- `schemas/entities.schema.json` is the JSON Schema Draft 2020-12 contract for one core software-factory entity.
- `examples/sample-entities.json` is a synthetic linked example graph for tests. It is not a real build or deployment record.
- `src/ontology_software_factory/contracts.py` validates object structure; `semantics.py` validates cross-object references and selected business invariants.

Run `python scripts/validate_domain_model.py` from the repository root.
