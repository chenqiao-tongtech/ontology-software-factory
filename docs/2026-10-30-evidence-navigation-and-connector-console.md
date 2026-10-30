# Evidence Navigation and Connector Operations Console

## Scope

This iteration builds on the unified source connector registry and ontology provenance fields added in the previous change. It adds three practical capabilities to the local Factory Portal:

1. Provider-host-allowlisted file navigation for GitHub.com and GitLab.com repository evidence.
2. Per-source synchronization history with duration, status, asset count, and a coarse error classification.
3. Portal registration for PostgreSQL and MySQL schema-only sources using a DSN environment-variable name and explicit hostname allow-list.

The implementation remains a local reference feature. It does not add enterprise IAM, a durable telemetry backend, or production network policy.

## Evidence navigation

Remote repository assets now carry a `browseUrl` derived from:
- a validated HTTPS GitHub.com or GitLab.com source URL;
- the provider-reported default branch;
- the asset's repository-relative path.

The link opens the source file in the provider UI. It does not download file contents into the Portal. Candidate evidence details show the source ID/name/type, path, asset ID, revision when available, content hash when available, and scan time.

For local directory sources, the Portal displays the local path and available SHA-256 evidence but deliberately does not create browser links to local files. For database sources, evidence remains a schema/table/column locator; there is no business-row link or business-row query.

GitHub's current revision value is the tree SHA exposed by the metadata connector, not a guaranteed commit SHA. It is shown as source revision metadata and is not treated as a file-content hash. GitLab revision may be absent when the provider response does not supply one.

## Connector operations view

Each explicit scan records up to 20 recent entries per source in local Portal state:
- sync ID and timestamp;
- duration in milliseconds;
- resulting status;
- asset count;
- coarse error class.

The UI shows the latest scan and recent entries. Error classes are intended for triage, not root-cause diagnosis. They include configuration, provider-unavailable, timeout, TLS/certificate, host-policy, connector-error, disabled, and not-synced categories where identifiable.

The history is stored in the local `.local-portal/state.json` file. It is not an immutable audit log, distributed trace, or production metrics store. A background refresh does not make remote provider or database network calls; remote repository and SQL scans remain explicit user-triggered actions.

## PostgreSQL and MySQL registration

The source form now supports PostgreSQL and MySQL:
- DSN environment-variable name, e.g. `FACTORY_POSTGRES_DSN` or `FACTORY_MYSQL_DSN`;
- one or more DNS hostnames in `allowedHosts`.

The Portal stores the environment-variable name and host allow-list, not the DSN value. At scan time the connector reads the DSN from the named environment variable. The database connector queries schema metadata only and does not query business table rows.

Optional drivers remain required:
```bash
pip install -e ".[postgres]"
pip install -e ".[mysql]"
```

PostgreSQL requires a TLS mode accepted by the connector. MySQL uses TLS hostname verification. Database credentials should be supplied through a secret manager or protected process environment. Use a database principal with least-privilege metadata access.

The hostname allow-list is an application-level connection check. It is not an egress firewall, DNS rebinding defense, or network segmentation control. Production deployment still needs outbound network policy, DNS controls, trusted CA configuration, secret rotation, connection timeouts, and monitoring.

## Verification

The automated tests cover:
- deterministic construction of GitHub/GitLab file browser URLs;
- provider host allow-listing and path encoding;
- synchronization history persistence and error classification;
- existing mocked remote repository and database connector boundaries.

These tests do not prove live GitHub/GitLab API availability, PostgreSQL/MySQL driver compatibility against a production server, TLS certificate deployment, or database privilege correctness. Those require a controlled integration environment.

## Known limitations

- GitHub/GitLab links point to the provider's browser view on the reported default branch; a concurrent branch update can make the linked file differ from the earlier scan. The revision remains visible alongside the link for comparison.
- No source-side incremental cursor or webhook delivery is implemented in this iteration.
- No provider-native deep link is available for local files or SQL tables.
- No automatic evidence invalidation or ontology impact analysis is implemented yet.
- Synchronization history is local, bounded, and mutable.
- The Portal remains unauthenticated and should only bind to loopback for trusted local development.
