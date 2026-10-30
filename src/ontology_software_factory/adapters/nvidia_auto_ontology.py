"""Read-only adapter for NVIDIA Auto Ontology's semantic catalogue API.

This adapter imports catalogue terms/acronyms as evidence sources for our own discovery
pipeline. It deliberately does not assume NVIDIA Auto Ontology has an endpoint that
creates this project's domain ontology or directly publish our candidate ontology.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any, Callable
from urllib.parse import urlparse

from ..ontology_discovery import SourceMaterial, OntologyDiscoveryError


class NvidiaAutoOntologyError(RuntimeError):
    pass


def _default_get(url: str, headers: dict[str, str], timeout: float) -> bytes:
    request = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            if response.status != 200:
                raise NvidiaAutoOntologyError(f"Auto Ontology API returned HTTP {response.status}")
            payload = response.read(2_000_001)
            if len(payload) > 2_000_000:
                raise NvidiaAutoOntologyError("Auto Ontology API response exceeds 2 MB limit")
            return payload
    except urllib.error.HTTPError as exc:
        raise NvidiaAutoOntologyError(f"Auto Ontology API returned HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise NvidiaAutoOntologyError(f"Auto Ontology API request failed ({type(exc).__name__})") from exc


class NvidiaAutoOntologyAdapter:
    """Import read-only terms and acronyms from a deployed NVIDIA Auto Ontology service."""

    def __init__(self, *, base_url: str | None = None, api_key: str | None = None,
                 timeout_seconds: float = 10.0,
                 get_bytes: Callable[[str, dict[str, str], float], bytes] = _default_get) -> None:
        self.base_url = (base_url or os.getenv("NVIDIA_AUTO_ONTOLOGY_URL", "")).rstrip("/")
        self.api_key = api_key or os.getenv("NVIDIA_AUTO_ONTOLOGY_API_TOKEN")
        self.timeout_seconds = max(1.0, min(timeout_seconds, 30.0))
        self._get_bytes = get_bytes
        parsed = urlparse(self.base_url)
        is_loopback = parsed.hostname in {"localhost", "127.0.0.1", "::1"}
        if parsed.scheme != "https" and not (parsed.scheme == "http" and is_loopback):
            raise NvidiaAutoOntologyError("base_url must use HTTPS (HTTP is allowed only for loopback testing)")
        if not parsed.netloc:
            raise NvidiaAutoOntologyError("NVIDIA_AUTO_ONTOLOGY_URL must be configured")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise NvidiaAutoOntologyError("base_url must not contain credentials, query, or fragment")

    def fetch_catalog_sources(self) -> list[SourceMaterial]:
        """Read the documented terms and acronyms routes and normalize each item as source evidence."""
        headers = {"Accept": "application/json"}
        if self.api_key:
            headers["x-api-key"] = self.api_key
        sources: list[SourceMaterial] = []
        for route, source_kind in (("/api/terms", "semantic-term"), ("/api/acronyms", "acronym")):
            url = self.base_url + route
            raw = self._get_bytes(url, headers, self.timeout_seconds)
            try:
                data = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise NvidiaAutoOntologyError(f"invalid JSON returned by {route}") from exc
            records = _unwrap_records(data)
            for index, record in enumerate(records):
                if not isinstance(record, dict):
                    continue
                label = str(record.get("name") or record.get("term") or record.get("acronym") or "").strip()
                if not label:
                    # Do not fabricate an entity identity. Preserve this record as review evidence only.
                    label = f"unlabeled-record-{index + 1}"
                record_id = str(record.get("id") or record.get("termId") or label)
                source_id = f"nvidia-auto-ontology:{source_kind}:{record_id}"
                content = json.dumps(record, ensure_ascii=False, sort_keys=True)
                sources.append(SourceMaterial(
                    source_id=source_id,
                    source_type=f"external-catalog:{source_kind}",
                    locator=f"{route}/{record_id}",
                    content=content,
                ))
        return sources


def _unwrap_records(payload: Any) -> list[Any]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("items", "terms", "acronyms", "data", "results"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
        # Some list endpoints wrap the array one layer deeper.
        for value in payload.values():
            if isinstance(value, dict):
                for key in ("items", "terms", "acronyms", "data", "results"):
                    if isinstance(value.get(key), list):
                        return value[key]
    raise NvidiaAutoOntologyError("expected a list or a documented list response object")
