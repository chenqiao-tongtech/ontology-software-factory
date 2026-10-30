# Source Sync Delta Manifest

## What it does

The Factory Portal now compares the latest successful source asset manifest with the previous successful scan and reports:

- added assets;
- changed assets;
- unchanged assets;
- removed assets only when both manifests are complete.

A first scan is marked as a baseline. A truncated or partial manifest never claims that missing assets were deleted. This is important because remote repository file trees and database table lists may be intentionally capped for safe UI payload sizes.

## Fingerprint precedence

1. file content SHA-256 when a connector actually provides a content digest;
2. schema fingerprint for database metadata;
3. deterministic metadata fingerprint from asset identity, path, kind, size, revision, schema and columns.

A Git commit revision plus file size is only a metadata fingerprint. It is not a content hash and must not be described as proof that file contents are unchanged.

## Candidate evidence freshness

Ontology candidates keep their original source revision, locator and fingerprint. The Portal re-evaluates those references against the latest successful source scan. If evidence has changed or cannot be verified, the candidate is marked for review; it is not silently rewritten or promoted.

## Safety constraints

- Source scans remain read-only.
- The manifest stores metadata, not source document bodies.
- A failed/disabled/not-synced scan does not imply all previous assets were removed.
- Partial manifests report `removed: null` and `removedKnown: false`.
- The source registry and sync history remain local reference state; production deployments still need durable storage, tenant-scoped authorization, scheduled sync workers, webhook delivery, retries and retention controls.

## Validation

Run:

```bash
python -m unittest tests.test_source_sync
make validate
make test
```
