# Asset lifecycle and customization policy

## Standard assets

1. Store upstream/internal source URI and an immutable revision or source reference.
2. Record component owner, lifecycle status, support policy, license identifier and license review status.
3. Represent each version as a stable ID; do not use a mutable tag such as `latest` as the only version identity.
4. Resolve dependencies to concrete version IDs and preserve the declared version constraint separately.
5. Bind artifacts to content digests; a catalogue metadata record alone does not prove the referenced bytes are correct.
6. For release candidates, collect an SBOM, build provenance, test evidence and security findings where applicable.

## Customer configuration

Customer configuration is an overlay over an identified product/component baseline. It may contain non-secret settings and references to a secret manager, but must not contain secret values. The overlay must identify its tenant, product, versioned baseline, owner and status.

## Custom patch

A patch remains a distinct tenant-scoped object linked to its component and base version. Do not silently mutate the global component version or publish one customer's patch as a standard asset. Before approval, require tests, a security review or an explicitly audited waiver, and a source revision.

## Lifecycle states

- `active`: approved for the intended catalogue purpose; does not by itself mean that every deployment is safe.
- `deprecated`: still discoverable, but avoid for new adoption except with documented reason.
- `eol`: outside the declared support window; exceptions need explicit risk acceptance.
- `archived`: preserved for traceability, not offered for normal selection.

Production policy should also record who can approve lifecycle changes, how changes are audited, and how downstream products/configurations are notified.
