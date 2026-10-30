# Asset catalogue (Article 17)

This directory adds a versioned catalogue model on top of the Article 16 core ontology and entity contracts.

## Files

- `schemas/asset-catalog.schema.json`: structural JSON Schema for products, components, versions, artifacts, compatibility assertions, customer configurations, and customer patches.
- `examples/demo-catalog.json`: synthetic records for a standard product plus a tenant-specific configuration and patch.
- `policies/lifecycle-and-customization.md`: lifecycle and standard-vs-customer customization rules.
- `compatibility-matrix.md`: how to record compatibility with evidence.

## Validate

```bash
python scripts/validate_asset_catalog.py
python scripts/validate_asset_catalog.py --readiness-version sf:version:event-broker-3.8.0
```

The demo catalogue should pass structural and semantic consistency checks. The readiness command intentionally returns a blocked status because the included artifact digests, SBOM and provenance are placeholders with `verificationStatus: pending`.

## Scope boundary

The validator checks catalog metadata and references. It does not fetch `artifact://` URIs, recompute file digests, parse SBOM documents, validate an SPDX identifier against the live SPDX license list, authenticate SLSA attestations, scan vulnerabilities, or deploy software. Production integrations must obtain evidence from trusted tools and bind it to actual artifact bytes, source revisions and build IDs.
