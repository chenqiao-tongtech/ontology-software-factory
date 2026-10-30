# Connector Platform and Ontology Ingestion

## Two connector planes, one governance model

**Ontology source connectors** are read-oriented. They discover concepts from repositories, documents, database schemas, API contracts, event schemas, data catalogs, work items and operational metadata. Their output is source evidence and candidate ontology content; it never directly edits the canonical ontology.

**Agent action connectors** expose bounded side effects such as creating a pull request, updating a work item or triggering CI. They require independent authorization, idempotency, approval where impactful, and evidence tied to the candidate digest.

The two planes share connector identity, versioning, policy, secret references, audit and observability. They must not share credentials or assume the same trust level.

## Capability architecture

1. Protocol adapter: filesystem, SQL metadata, Git provider API, SaaS API, OpenAPI/GraphQL, MCP, HTTP or message broker.
2. Descriptor: stable ID, category, direction, operations, rollout status, data classes, auth mode, credential reference and egress class.
3. Policy: principal, tenant, workflow, task, target resource, environment, data classification, risk and approval.
4. Normalization: immutable locator, provider revision, content/schema digest, observation time and provenance.
5. Semantic extraction: terms, entities, relations, events, actions, state transitions, constraints and competency questions.
6. Validation: citations, schema checks, duplicate/contradiction detection, benchmark and human review.
7. Lifecycle: candidate, approved, versioned, deprecated, with consumer impact and migration plan.

The ConnectorCatalog implemented here validates metadata and applies a default-deny operation check. It does not instantiate OAuth clients, MCP servers or provider network sessions.

## Ontology source connector roadmap

| Source family | Examples | Ontology value | Registry status |
|---|---|---|---|
| Code and engineering | GitHub, GitLab, Bitbucket, Azure DevOps, local repositories | classes, APIs, dependencies, ownership, build/test/release lifecycle | local directory and GitHub/GitLab metadata implemented; others future |
| Enterprise documents | Confluence, SharePoint/OneDrive, Google Drive, Notion, OpenText | glossary, policies, SOPs, process descriptions and exceptions | planned |
| Database and warehouse | SQLite, PostgreSQL, MySQL, SQL Server, Oracle, Snowflake, Databricks, BigQuery | tables, columns, keys, constraints, lineage and ownership | SQLite/PostgreSQL/MySQL implemented; others future |
| API contracts | OpenAPI, AsyncAPI, GraphQL SDL, Protobuf/gRPC, JSON Schema | service boundaries, operations, payload semantics and events | OpenAPI/GraphQL adapter-required; others future |
| Event platforms | Kafka Schema Registry, Kafka Connect, Pulsar, RabbitMQ, cloud event buses | event types, producers/consumers, lifecycle and compatibility | planned |
| Data governance | DataHub, OpenMetadata, Collibra, Apache Atlas, dbt artifacts | glossary, lineage, ownership and classification | dbt planned; others future |
| Work management | Jira, Linear, Azure Boards, GitHub Issues | work item types, states, ownership and change history | future |
| Runtime and observability | Kubernetes, service catalog, OpenTelemetry, Prometheus, Grafana, Datadog, PagerDuty | service, metric, alert, incident, SLO and dependency concepts | future |
| Identity and policy | Entra ID, Okta, Keycloak, OPA | principal, group, entitlement and policy relationships | future; ontology never grants permissions |

Additional action connector candidates include GitHub/GitLab PRs, Jira, CI systems, artifact registries, Kubernetes and cloud deployment APIs. They must remain separate from read-only discovery connectors.

## Harness, Skills, Tools and Connectors

- **Harness** is the control plane around Agents: identity, policy, context assembly, tool mediation, budget, retries, timeouts, isolation, approval, tracing, evidence and kill-switch.
- **Skill** is a versioned task procedure with input/output schemas, preconditions, steps, allowed tools, verification and failure taxonomy.
- **Tool** is one narrow typed operation with side-effect classification, permission scope, idempotency and evidence contract.
- **Connector** is authenticated transport and provider-specific translation. It may expose read-only source operations or bounded action operations.
- **Agent** reasons and owns a task but requests capabilities through the Harness; it must not hold provider credentials or bypass Workflow authority.

Recommended Harness modules: policy decision point, context broker, tool gateway, secret broker, sandbox manager, model gateway, budget manager, approval service, evidence collector, trace exporter, retention policy and emergency stop.

## Ingestion and security rules

- Keep source credentials read-only and action credentials separate.
- Preserve source ACLs and tenant boundaries through retrieval and candidate review.
- Never put secrets in prompts, logs, evidence payloads or ontology artifacts.
- Enforce network egress outside the connector process; host allow-lists in config are not a firewall.
- Treat documents and tool output as untrusted data; prompt-injection text must never become executable instructions.
- Record provider, adapter version, scope, revision, pagination completeness and errors on each sync.
- Do not infer deletions from partial scans or claim completeness beyond the caller's visible ACL scope.
- Bind every write action and evidence record to candidate digest and approval record.
- Provide revoke, rotate, pause and kill-switch operations.

## Current implementation boundary

This increment adds a JSON Schema, connector registry, Python catalog loader, default-deny operation authorization, validation CLI and unit tests. Registry entries marked planned or adapter-required are inventory only. No new live Confluence, SharePoint, Google Drive, Bitbucket, Azure DevOps, Kafka Schema Registry, AsyncAPI or GraphQL network adapter is delivered here. OAuth exchange, production secret broker, connector UI, event-driven sync and enterprise ACL propagation remain future work.
