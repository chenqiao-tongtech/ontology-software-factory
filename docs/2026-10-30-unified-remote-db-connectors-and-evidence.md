# Unified Source Connectors: Remote Repositories, SQL Schemas, and Evidence

Date: 2026-10-30

## Scope

This increment brings GitHub and GitLab metadata scans behind the common source connector interface, adds optional schema-only PostgreSQL and MySQL adapters, and expands ontology candidate evidence with source provenance.

It does not turn the local Portal into a production integration service. Credentials remain environment variables; database access requires an explicit host allow-list and explicit user-triggered sync.

## Connector matrix

| Source type | Connector | Read scope | Credential / boundary |
|---|---|---|---|
| repository / documents | LocalDirectoryConnector | Bounded UTF-8 text asset inventory and SHA-256 | Explicit local allowed root; symlinks and secret-like paths excluded |
| sqlite | SQLiteSchemaConnector | Table/view/column metadata | Read-only SQLite URI; no business rows |
| github | RemoteRepositoryConnector | Repository metadata and file tree paths | github.com HTTPS only; optional token from tokenEnv |
| gitlab | RemoteRepositoryConnector | Project metadata and repository tree paths | gitlab.com HTTPS only; optional token from tokenEnv |
| postgresql | PostgreSQLSchemaConnector | information_schema tables and columns | psycopg optional extra; connectionEnv; allowedHosts; sslmode=require or verify-full |
| mysql | MySQLSchemaConnector | information_schema tables and columns | PyMySQL optional extra; connectionEnv; allowedHosts; TLS enabled |

Remote repository scans do not download file bodies. PostgreSQL/MySQL adapters do not issue SELECT statements against business tables; they query information_schema only and use read-only transaction settings.

## Configuration examples

GitHub / GitLab source:
```json
{
  "id": "source-github",
  "name": "Application repository",
  "type": "github",
  "url": "https://github.com/acme/application",
  "tokenEnv": "FACTORY_GITHUB_READ_TOKEN",
  "enabled": true
}
```

PostgreSQL source:
```json
{
  "id": "source-postgres",
  "name": "Application schema",
  "type": "postgresql",
  "connectionEnv": "FACTORY_POSTGRES_READONLY_URL",
  "allowedHosts": ["postgres.internal.example"],
  "enabled": true
}
```

The connection URL is not stored in source configuration. It is read from the named environment variable at explicit sync time. PostgreSQL URLs must include sslmode=require or sslmode=verify-full.

MySQL source:
```json
{
  "id": "source-mysql",
  "name": "Application schema",
  "type": "mysql",
  "connectionEnv": "FACTORY_MYSQL_READONLY_URL",
  "allowedHosts": ["mysql.internal.example"],
  "enabled": true
}
```

Install optional drivers only when required:
- PostgreSQL: `pip install -e ".[postgres]"`
- MySQL: `pip install -e ".[mysql]"`

Use dedicated database accounts that have metadata visibility but no business-data privileges. The adapter's read-only transaction is defense in depth, not a replacement for database-side least privilege, network policy, or TLS certificate management.

## Explicit synchronization

Background Portal refresh does not contact GitHub, GitLab, PostgreSQL, or MySQL. These source types return `not-synced` until the operator triggers an explicit Sync / discovery action. This prevents an ordinary page refresh from unexpectedly initiating network access.

## Evidence model

Each discovered term's evidence now carries the following fields where the connector can supply them:

- `sourceId`, `sourceName`, `sourceType`: configured source identity;
- `provider`: remote provider when applicable;
- `path`: repository-relative path or schema-qualified database object;
- `kind`: extraction evidence type (heading, symbol, SQL table/column, remote file path, etc.);
- `assetId`: stable connector asset identifier;
- `contentSha256`: local file content digest when available;
- `sourceRevision`: remote repository tree revision when available;
- `scannedAt`: timestamp of the source scan.

A digest is not fabricated for remote paths or database schema metadata. For database schema assets, `assetId` and the schema-qualified locator are available; database server-side schema versioning is not inferred.

## Operational and security limitations

- GitHub/GitLab support is limited to github.com and gitlab.com; self-hosted instances are not enabled.
- Remote repository trees are bounded to 600 assets and are metadata-only. Large/truncated trees are reported as partial.
- PostgreSQL/MySQL adapters are optional and require the corresponding driver extra.
- `allowedHosts` is an explicit hostname allow-list, not a full network egress firewall. Production deployments must also enforce outbound network policy and DNS controls.
- Credentials are never included in connector results. The Portal is still a local reference service without production authentication, tenant isolation, or a managed secret vault.
- No live database or remote provider was contacted by the unit tests; connector behavior is tested with mocked provider responses and boundary validation.
