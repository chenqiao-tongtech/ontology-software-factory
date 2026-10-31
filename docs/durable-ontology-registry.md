# Durable Formal Ontology Registry

## Purpose

The Portal now maintains a SQLite-backed snapshot catalog in:

```
.local-portal/ontology-registry.sqlite3
```

The registry is separate from the mutable Portal `state.json` cache and stores:
- full ontology snapshot JSON;
- ontology ID/version/schema version;
- SHA-256 digest and snapshot ID;
- creation actor, reason and timestamp;
- the active snapshot pointer;
- append-only activation and legacy-migration events.

## Immutability and activation

Snapshot IDs are derived from the ontology content digest. Registration verifies both the digest and deterministic snapshot ID. Re-registering the same snapshot is idempotent. SQLite triggers reject updates and deletes to stored snapshots and registry events.

The active pointer is mutable, but activation requires:
- a registered snapshot belonging to the ontology;
- an expected previous active snapshot ID (optimistic concurrency);
- an executor identity;
- an approved governance proposal ID;
- an approval reference.

The existing Portal proposal → independent approval → independent execution sequence remains in force. Execution now updates the SQLite registry pointer and then updates the Portal state projection. If the process stops after pointer activation but before state projection update, retrying the same proposal is idempotent.

## Migration

On first registry access, existing snapshots from `.local-portal/state.json` are registered. An existing active pointer is imported with the explicit reference `legacy-state-import`; this does not fabricate a human approval. Future promotions use the governance proposal reference.

## APIs

- `GET /api/ontology/versions`: registered snapshot metadata and active pointer.
- `GET /api/ontology/governance`: active snapshot, proposals and releases.
- `GET /api/ontology/registry/events`: append-only registry event history.
- Existing compatibility and diff APIs read snapshots from the registry.

## Important boundaries

This is a durable local SQLite registry, not yet a highly available enterprise registry service. Production use still needs encrypted backups, access control, tenant isolation, replication, disaster recovery, signing/attestation, retention policy and cross-environment promotion controls. SQLite triggers protect against accidental application-level updates; they are not a defense against an administrator who can replace the database file.

Approved LLM discovery candidates remain separate artifacts. Approving a candidate does not merge it into the formal ontology; a human must update the formal ontology, create a new snapshot, pass compatibility checks, and complete the independent promotion workflow.
