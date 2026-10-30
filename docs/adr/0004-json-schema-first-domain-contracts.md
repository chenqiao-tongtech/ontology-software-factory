# ADR-0004: Start with machine-readable vocabulary + JSON Schema + graph checks

- Status: Accepted for MVP
- Date: 2026-10-27

## Context

The factory needs a shared meaning for requirements, products, components, versions, builds, tests, vulnerabilities, releases, deployments and incidents. The first goal is low-friction validation in CI, not ontology reasoning infrastructure.

## Decision

Use a versioned JSON vocabulary file for classes, relationships and controlled terms; use JSON Schema Draft 2020-12 for individual entity shape; use Python validation for typed references and selected cross-object invariants. Consider RDF/OWL/SHACL as optional later additions when formal reasoning, graph exchange, or RDF graph constraints are justified by concrete requirements.

## Consequences

- Developers can validate examples and APIs before a graph database is introduced.
- Graph/reference rules require explicit tests in Python and may need expansion as the model grows.
- The vocabulary, schemas, examples, validators and tests must evolve together.
- This decision does not provide authorization or evidence provenance guarantees by itself.
