# Ontology Evidence Lifecycle and Live Database Checks

## What changed

This iteration adds a read-only evidence lifecycle assessment to the local Factory Portal and an opt-in live database integration test harness.

### Evidence validity states

When the Portal serves `GET /api/ontology`, it compares each saved candidate evidence item against the latest cached/source inventory without initiating remote network calls:

| State | Meaning |
|---|---|
| `current` | A comparable local content hash or SQL schema fingerprint matches; or a remote repository tree revision matches |
| `content-changed` | A local file still exists but its SHA-256 differs |
| `schema-changed` | A table/column metadata fingerprint differs |
| `revision-changed-review` | The repository tree revision changed; file-level content was not fetched, so review is required rather than claiming the specific file changed |
| `asset-missing` | A complete scan did not find the evidence locator |
| `inconclusive-partial-scan` | The scan was truncated; absence cannot be interpreted as deletion |
| `source-unavailable` | The latest scan failed or the source is disabled |
| `source-removed` | The source no longer exists in source configuration |
| `not-yet-checked` | No scan result is available |
| `unverifiable` / `present-unverified` | The locator exists but no comparable fingerprint/revision is available |

The candidate API response includes per-evidence `validity`, a status-count summary, a check timestamp, and an affected-term count. The UI shows the result on candidate cards and evidence details.

These states are an assessment against the latest available inventory, not a guarantee of live freshness. The existing 90-second local cache may be used, and the assessment does not trigger remote refresh. Operators should explicitly synchronize sources before reviewing a candidate.

### Fingerprints and conservative semantics

- Local repository/document evidence uses the existing file SHA-256.
- SQLite/PostgreSQL/MySQL table and column evidence uses a deterministic fingerprint over the schema locator, kind, table name, schema, and column metadata.
- GitHub/GitLab evidence uses the provider tree revision. A tree revision change flags the evidence for review, not as a proven file-content change.
- If a source scan is partial, a missing asset is inconclusive rather than deleted.
- SQL schema discovery includes PostgreSQL and MySQL as well as SQLite; no business table rows are queried.

## Live database integration test harness

The regular CI suite includes opt-in tests in `tests/test_database_connector_integration.py`. They are skipped unless explicit test DSNs are supplied. This avoids connecting CI to unconfigured or production databases.

Install optional drivers:
```bash
pip install -e ".[postgres]"
pip install -e ".[mysql]"
```

Run against dedicated, non-production databases:

```bash
export FACTORY_TEST_POSTGRES_DSN='postgresql://factory_reader:...@db.example.internal:5432/factory_test?sslmode=verify-full'
export FACTORY_TEST_POSTGRES_EXPECT_TABLE='public.integration_probe'
export FACTORY_TEST_MYSQL_DSN='mysql://factory_reader:...@db.example.internal:3306/factory_test'
export FACTORY_TEST_MYSQL_EXPECT_TABLE='factory_test.integration_probe'
python -m unittest discover -s tests -p 'test_database_connector_integration.py' -v
```

The MySQL test requires a server and client environment compatible with the connector's TLS hostname verification. Configure trusted CA material according to the deployment's PyMySQL/OpenSSL environment; do not disable certificate checks to make a test pass.

The tests:
- derive the host allow-list from the explicitly supplied test DSN;
- run only the schema connector;
- assert that the connector returns schema metadata and read-only markers;
- optionally assert that a known pre-created fixture table is visible.

They do not create or mutate test tables, query business rows, or prove production privilege configuration. Use dedicated disposable test databases and a least-privilege account. For meaningful permission validation, provision an account with only the metadata privileges needed by the connector and separately verify that application tables cannot be modified.

## Security and operational limitations

- DSNs are provided through environment variables and must not be committed to source control or printed in logs.
- The connector's hostname allow-list is an application-level guard, not a network egress firewall.
- PostgreSQL `sslmode=require` encrypts the connection but does not provide the same server identity verification as `verify-full`; prefer `verify-full` with trusted CA configuration.
- MySQL TLS behavior depends on server certificate and client trust configuration; this harness does not install or distribute CA certificates.
- Evidence validity is not yet persisted as an immutable audit trail. It is recomputed from the latest source scan when the API is read.
- No automated ontology rollback, automatic candidate rejection, or formal ontology mutation is performed.
