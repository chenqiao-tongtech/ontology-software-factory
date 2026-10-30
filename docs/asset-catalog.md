# Article 17 — Asset catalogue design

## Responsibilities

The catalogue is the factory's reusable asset index. It links products, components, component versions, artifacts, dependencies, compatibility claims, tenant-specific configuration overlays, and customer patches.

It is not a package registry, source control system, SBOM generator, vulnerability scanner, artifact-signature verifier, or authorization service. It records references to those systems and uses trusted external evidence when deciding readiness.

## Key invariants implemented in this MVP

- IDs are unique across catalogue object types and versions.
- Product component references must resolve to component records.
- A component default version must be one of its own versions.
- A resolved dependency version must belong to the declared dependency component and satisfy the supported SemVer constraint subset.
- The resolved version graph must not contain dependency cycles.
- Active components must have an approved license-review record.
- `compatible` or `incompatible` claims require referenced verified evidence; `untested` makes no claim.
- Customer baseline versions must belong to components included by the selected product.
- Secret-like config keys are rejected from ordinary overrides; use secret-manager references.
- Customer patches are tenant-scoped and must be anchored to a version of the declared component.
- An approved patch requires test evidence and a security pass or explicit waiver.

## Readiness policy

`check_version_readiness` is a local MVP policy, not a release authorization engine. It checks the presence and catalogue verification status of required artifacts, SBOM, provenance, license-review status, source revision and stable/active lifecycle status. It does not verify the actual bytes, cryptographic signatures, SBOM content, vulnerability disposition or production environment.

## Version constraints

The MVP supports exact SemVer, caret (`^`), tilde (`~`), and comma-separated comparison operators (`>=`, `>`, `<=`, `<`, `==`). This is an intentionally small subset, not a full implementation of every ecosystem's dependency syntax. Maven ranges, npm aliases, Python environment markers, OS package constraints and container multi-architecture manifests need ecosystem-specific resolvers/adapters in later work.
