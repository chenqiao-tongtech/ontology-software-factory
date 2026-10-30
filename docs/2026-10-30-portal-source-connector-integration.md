# Portal Source Connector Integration

Date: 2026-10-30

## Summary

This change wires the read-only connector foundation into the unified local Portal.

### Implemented

- Portal local repository and document directory scans now use `SourceConnectorRegistry` and `LocalDirectoryConnector`.
- Portal SQLite scans now use the same registry and `SQLiteSchemaConnector`.
- Directory scan results expose a SHA-256 digest for each indexed text asset, alongside the relative path, file kind, and byte size.
- SQLite scan results expose table/view columns and definitions as schema metadata. The connector uses a read-only connection and does not query business rows.
- SQLite table and column names are now eligible for deterministic ontology candidate extraction, with source evidence such as `sqlite:orders`.
- Existing remote GitHub/GitLab metadata adapters remain on their existing provider-specific path. They are not yet implemented as `SourceConnector` registry providers.
- Added portal integration tests for repository/document scans, SQLite schema scans, digest presence, and SQLite-derived ontology terms.

### Safety and behavior

- The directory connector uses an explicit allowed-root boundary, excludes hidden/secret files and common dependency/build directories, refuses symlink traversal, and caps individual file size and scan count.
- The Portal still exposes only the first 30 directory assets in the UI payload; `assetCount` reports the bounded connector scan count.
- SQLite details are schema-only. No row contents are returned to the Portal.
- This remains a local reference Portal without production authentication or multi-tenant identity enforcement.

## CI

Added `.github/workflows/ci.yml` to run:

1. `make validate`
2. `make test`

on pull requests targeting `main` and pushes to `main`.

The workflow must execute in GitHub Actions before test status can be reported. No test pass is claimed until an actual run completes successfully.

## Remaining work

1. Implement GitHub/GitLab remote adapters behind the same connector protocol while preserving host allow-lists, explicit user-triggered sync, and secret non-disclosure.
2. Add connector health, last-success, pagination/incremental cursor, and retry state.
3. Add PostgreSQL/MySQL schema-only adapters with read-only credentials and explicit database/network allow-lists.
4. Add authenticated identity, tenant-scoped source configuration, and secret-vault integration before any multi-user deployment.
5. Add evidence navigation from ontology candidates to the source asset and source revision.
