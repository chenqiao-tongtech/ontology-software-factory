"""Authenticated, idempotency-aware webhook verification for source synchronization."""
from __future__ import annotations

import hashlib
import hmac
import os
import re
from typing import Any
from urllib.parse import urlparse


class SourceWebhookError(ValueError):
    pass


def _repo_identity(value: str, provider: str) -> tuple[str, str] | None:
    parsed = urlparse(str(value or ""))
    expected = "github.com" if provider == "github" else "gitlab.com"
    if parsed.scheme != "https" or parsed.hostname != expected or parsed.username or parsed.password:
        return None
    path = parsed.path.strip("/").removesuffix(".git").rstrip("/")
    if not path:
        return None
    return expected, path.casefold()


def verify_source_webhook(
    provider: str,
    source: dict[str, Any],
    headers: Any,
    raw_body: bytes,
    payload: dict[str, Any],
    *,
    environ: dict[str, str] | None = None,
) -> dict[str, str]:
    """Verify provider secret, event type, delivery ID and repository identity."""
    if provider not in {"github", "gitlab"} or source.get("type") != provider:
        raise SourceWebhookError("provider/source mismatch")
    env = os.environ if environ is None else environ
    secret_env = str(source.get("webhookSecretEnv", ""))
    if not re.fullmatch(r"[A-Z_][A-Z0-9_]{0,127}", secret_env):
        raise SourceWebhookError("webhook secret environment variable is not configured")
    secret = env.get(secret_env, "")
    if not secret:
        raise SourceWebhookError("webhook secret is not configured on this server")

    if provider == "github":
        signature = str(headers.get("X-Hub-Signature-256", ""))
        if not re.fullmatch(r"sha256=[0-9a-f]{64}", signature):
            raise SourceWebhookError("missing or malformed GitHub signature")
        expected = "sha256=" + hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise SourceWebhookError("GitHub signature verification failed")
        event = str(headers.get("X-GitHub-Event", ""))
        delivery = str(headers.get("X-GitHub-Delivery", ""))
        repo = payload.get("repository", {}) if isinstance(payload.get("repository"), dict) else {}
        delivered_url = str(repo.get("html_url") or repo.get("clone_url") or "")
    else:
        supplied = str(headers.get("X-Gitlab-Token", ""))
        if not supplied or not hmac.compare_digest(supplied, secret):
            raise SourceWebhookError("GitLab token verification failed")
        event = str(headers.get("X-Gitlab-Event", ""))
        delivery = str(headers.get("X-Gitlab-Event-UUID", "") or payload.get("event_uuid", ""))
        project = payload.get("project", {}) if isinstance(payload.get("project"), dict) else {}
        delivered_url = str(project.get("web_url") or project.get("git_http_url") or "")

    allowed_events = {"push", "repository"} if provider == "github" else {"Push Hook", "Project Update Hook"}
    if event not in allowed_events:
        raise SourceWebhookError("unsupported webhook event")
    if not delivery or len(delivery) > 200:
        raise SourceWebhookError("delivery identifier is required")
    expected_identity = _repo_identity(str(source.get("url", "")), provider)
    delivered_identity = _repo_identity(delivered_url, provider)
    if not expected_identity or expected_identity != delivered_identity:
        raise SourceWebhookError("webhook repository does not match configured source")
    return {"deliveryId": delivery, "eventType": event}
