# ADR-0005: Versioned asset catalogue and customer configuration boundary

- Status: Accepted for MVP
- Date: 2026-10-28

## Context

The core ontology and entity contracts now describe products, components, versions, artifacts, builds, tests, vulnerabilities, releases, deployments and incidents. The next step is to make approved reusable assets discoverable and to distinguish shared baseline software from tenant-specific settings and patches.

## Decision

1. Add a catalogue-level JSON Schema for products, components, nested versions, artifacts, dependencies, compatibility claims, customer configurations and custom patches.
2. Keep stable IDs for all catalogue objects and resolve every dependency to a concrete version ID while preserving the original version constraint.
3. Validate both schema shape and cross-object invariants, including version ownership, dependency satisfaction and acyclicity, compatibility evidence, product/configuration membership, tenant boundaries, and secret-like override keys.
4. Treat customer configuration as a tenant-specific overlay over an explicit product/component version baseline. Secret values are not accepted in the catalogue; only references to a dedicated secret manager are stored.
5. Keep customer-specific code patches distinct from global component versions. An approved patch requires test evidence and a security pass or an explicitly recorded waiver.
6. Use SPDX, CycloneDX and SLSA provenance as interoperable evidence formats where appropriate, but do not infer that those files exist or are valid just because metadata fields are present.
7. Define a local MVP readiness policy that checks required metadata and `verificationStatus`; cryptographic verification, package retrieval, real SBOM parsing, vulnerability scanning and deployment authorization remain external integrations.

## Consequences

- Catalogue validation can run locally and in future CI before any Agent orchestrator exists.
- A catalogue can be internally consistent while still being blocked from release because artifacts/evidence are pending.
- Dependency syntax is intentionally a SemVer subset; ecosystem-specific resolvers are required for full Maven/npm/Python/OCI behavior.
- Catalogue validation does not replace IAM, license counsel, vulnerability triage, cryptographic signature verification or production release approval.
