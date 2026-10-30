# GitHub / GitLab Source Webhook Sync

## Overview

The local Factory Portal can accept authenticated source-change notifications and trigger a scan of only the configured source, rather than synchronizing every source.

Endpoints:

- `POST /api/webhooks/github/<source-id>`
- `POST /api/webhooks/gitlab/<source-id>`

Supported events:

- GitHub: `push`, `repository`
- GitLab: `Push Hook`, `Project Update Hook`

The handler verifies the configured provider secret, checks that the payload repository/project matches the registered source URL, and deduplicates provider delivery IDs. It then runs one explicit source scan and records a sanitized governance event. Payload bodies are not stored in Portal state.

## Configure

When adding a GitHub/GitLab source in the Portal, optionally set **Webhook Secret 环境变量名**, for example:

- GitHub: `FACTORY_GITHUB_WEBHOOK_SECRET`
- GitLab: `FACTORY_GITLAB_WEBHOOK_SECRET`

Set the actual secret in the Portal process environment. Never enter the secret value into the source form or commit it to configuration.

Configure the provider webhook URL using the source ID returned by the Portal. For GitHub, choose JSON delivery and the `push` event (optionally `repository`); configure the same secret value in GitHub. For GitLab, configure the matching secret token and Push/Project events.

## Security and deployment

The Portal defaults to loopback and has no built-in user authentication. Do not expose its port directly to the internet. To receive external webhooks, keep the Portal bound to loopback behind a reverse proxy or gateway that:
- protects interactive Portal routes with enterprise authentication;
- routes only the exact webhook path to the Portal;
- enforces request-size limits, TLS and network restrictions;
- does not log request bodies or secret headers.

Provider HMAC/token validation is additional verification, not a replacement for the gateway. GitHub uses `X-Hub-Signature-256`; GitLab uses `X-Gitlab-Token`. A configured environment variable name is stored in the source registry; its value is not.

## Delivery and failure semantics

- Repeated delivery IDs return `202 duplicate=true` and do not rescan.
- Unknown/disabled source IDs, unconfigured secrets, bad signatures/tokens, unsupported event types and repository mismatches fail closed.
- Successful verification triggers a scan for the single source ID.
- Delta summaries respect manifest completeness; partial remote scans do not claim deletions.
- Delivery deduplication is stored in local Portal JSON state, not a distributed durable inbox. Production use still requires durable idempotency storage, retries/dead-letter handling, alerting, and tenant-scoped authorization.
- This implementation has unit tests for signature, token, event, repository identity and missing-secret validation. A real provider-to-gateway end-to-end delivery test remains an operator task.
