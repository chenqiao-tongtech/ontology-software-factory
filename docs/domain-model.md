# Software Factory Domain Model — v1.0.0

> Status: MVP vocabulary and contract baseline. The sample entities are synthetic fixtures used for automated validation, not evidence of a real Kafka build or production deployment.

## Design intent

The ontology defines business meaning and typed relations. The JSON Schema validates one entity's structure. Python graph checks validate cross-entity references and selected MVP invariants. None of these layers grants permissions or authenticates evidence.

## Core classes

| Class | Meaning | Important relationships |
|---|---|---|
| Requirement | Requested behavior and acceptance criteria | optional `targetProductId` → Product |
| Product | A deliverable product family | `componentIds` → Component |
| Component | Reusable middleware, library, service, template or tool | `currentVersionId` → Version |
| Version | A version belonging to one component | `componentId` → Component |
| Artifact | Package, image, configuration, report, SBOM or document | optional `createdByBuildId` → Build |
| Build | An actual build run for a source revision | component + version; `artifactIds` → Artifact |
| TestRun | An actual test execution | `buildId` → Build; `reportArtifactId` → Artifact |
| Vulnerability | A security finding | component + `affectedVersionIds` → Version |
| Release | A product delivery candidate/published release | product, versions, builds, tests and evidence |
| Deployment | A deployment attempt/result | `releaseId` → Release |
| Incident | A runtime issue | optional deployment, affected components, evidence |

## Shared metadata

- `id`: stable identifier following `sf:<entity-kebab-case>:<stable-key>`.
- `entityType`: type discriminator.
- `schemaVersion`: JSON contract shape version.
- `ontologyVersion`: business vocabulary/meaning version.
- `tenantId`: tenant boundary label; authorization still belongs to a policy/IAM layer.
- `createdAt`: timestamp with time zone.
- `source`: origin metadata; provenance alone is not truth verification.

## Validation layers

1. `contracts/schemas/entities.schema.json`: JSON Schema Draft 2020-12 validation using `jsonschema` + `FormatChecker`.
2. `src/ontology_software_factory/semantics.py`: duplicate IDs, typed references, component/version matching and selected status/count invariants.
3. `tests/`: positive and negative tests proving that important invalid states are rejected.

## Current MVP invariants

- Entity IDs are unique within the submitted graph.
- Every relation target must exist, have the target entity type, and remain within the same tenant boundary.
- A Build's Version must belong to its Component.
- A Component's current Version must belong to that Component.
- Vulnerability affected versions must belong to the finding's Component.
- Release versions must be provided by Components included in its Product.
- A `succeeded` Build must reference an Artifact in this MVP.
- For TestRun, `passed + failed + skipped = total`.
- A `passed` TestRun has zero failed cases; a `failed` TestRun has at least one failed case.
- A published Release must have vulnerability review `pass` or `waived`, plus approver identity and timestamp.
- A successful production Deployment must include `approvalRef`.

These are deliberately small starter rules. Amend them through reviewed ontology/schema changes when a real workflow requires a different invariant. Avoid special-casing valid workloads just to satisfy the example.

## Extend safely

1. Add or change a class/relation in the machine-readable ontology and review its meaning with the owner.
2. Update the JSON Schema, example dataset, graph validators and both positive/negative tests in one change.
3. Decide whether `schemaVersion`, `ontologyVersion`, or both must change.
4. Add migration/compatibility notes for consumers and record the choice in an ADR.
5. Run `python scripts/validate_domain_model.py` and `python -m unittest discover -s tests -v` before merge.

## Why no OWL/SHACL yet?

The first milestone is to make operational objects and references testable with low setup cost. RDF/OWL can be added when formal ontology exchange/reasoning or graph semantics are required; SHACL can validate RDF graphs. Neither automatically replaces API contract validation, workflow state transitions or access control.
