"""Governed connector execution boundary for ontology-source scans.

Provider clients are injected by trusted application code. The runtime does not
construct network clients, resolve secrets, or execute arbitrary connector commands.
"""
from __future__ import annotations

import hashlib
import json
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Protocol

from .connector_catalog import ConnectorCatalog, ConnectorPolicyError


class ConnectorRuntimeDenied(PermissionError):
    """A connector invocation failed an identity, tenant, or policy check."""


class ConnectorRuntimeUnavailable(RuntimeError):
    """A declared connector has no runtime adapter registered."""


class SourceAdapter(Protocol):
    def scan(self, source_id: str, location: str) -> Any: ...


@dataclass(frozen=True)
class ConnectorPrincipal:
    principal_id: str
    tenant_id: str


@dataclass(frozen=True)
class SourceBinding:
    source_id: str
    connector_id: str
    tenant_id: str
    location: str
    enabled: bool = True
    approved: bool = True
    operation: str = "scan.assets"


class ConnectorRuntime:
    """Read-only source scan runtime with tenant binding and metadata-only audit."""

    def __init__(
        self,
        *,
        catalog: ConnectorCatalog,
        source_adapters: dict[str, SourceAdapter],
        audit_path: str | Path,
        max_assets_per_scan: int = 20_000,
    ):
        self.catalog = catalog
        self.source_adapters = dict(source_adapters)
        self.audit_path = Path(audit_path).resolve()
        self.max_assets_per_scan = max(1, int(max_assets_per_scan))
        self._lock = threading.RLock()

    @staticmethod
    def _normalize_result(result: Any, *, source_id: str, max_assets: int) -> dict[str, Any]:
        if hasattr(result, "as_dict"):
            value = result.as_dict()
        elif isinstance(result, dict):
            value = dict(result)
        else:
            raise ValueError("source adapter must return a mapping or as_dict result")
        assets = value.get("assets")
        if not isinstance(assets, list):
            raise ValueError("source adapter result must contain an assets array")
        if len(assets) > max_assets:
            raise ValueError("source adapter exceeded configured asset limit")
        normalized = []
        for asset in assets:
            if not isinstance(asset, dict):
                raise ValueError("source asset must be an object")
            if not asset.get("asset_id") and not asset.get("assetId"):
                raise ValueError("source asset requires a stable asset ID")
            # Only metadata is projected. Raw source text and credential-like fields are excluded.
            safe = {}
            aliases = {
                "assetId": ("asset_id", "assetId"),
                "sourceId": ("source_id", "sourceId"),
                "kind": ("kind",),
                "name": ("name",),
                "locator": ("locator",),
                "contentSha256": ("content_sha256", "contentSha256", "sha256"),
                "sizeBytes": ("size_bytes", "sizeBytes", "bytes"),
                "metadata": ("metadata",),
            }
            for output_key, candidates in aliases.items():
                for candidate in candidates:
                    if candidate in asset:
                        safe[output_key] = asset[candidate]
                        break
            if safe.get("sourceId") not in (None, source_id):
                raise ValueError("source asset belongs to a different source")
            safe["sourceId"] = source_id
            normalized.append(safe)
        status = str(value.get("status", "unknown"))
        if status not in {"complete", "partial", "failed", "unknown", "success"}:
            status = "unknown"
        return {
            "sourceId": source_id,
            "sourceType": value.get("sourceType") or value.get("source_type") or "unknown",
            "status": status,
            "assetCount": len(normalized),
            "assets": normalized,
            "warnings": [str(item)[:500] for item in value.get("warnings", [])[:50]]
            if isinstance(value.get("warnings", []), list) else [],
        }

    def scan_source(self, principal: ConnectorPrincipal, binding: SourceBinding) -> dict[str, Any]:
        started = time.monotonic()
        status = "failed"
        result: dict[str, Any] | None = None
        try:
            if not principal.principal_id or not principal.tenant_id:
                raise ConnectorRuntimeDenied("authenticated principal and tenant are required")
            if binding.tenant_id != principal.tenant_id:
                raise ConnectorRuntimeDenied("source binding tenant does not match principal tenant")
            if not binding.enabled or not binding.approved:
                raise ConnectorRuntimeDenied("source binding is disabled or not approved")
            descriptor = self.catalog.authorize(binding.connector_id, binding.operation)
            if descriptor.category != "ontology-source" or descriptor.direction != "read":
                raise ConnectorRuntimeDenied("connector is not an ontology source")
            adapter = self.source_adapters.get(binding.connector_id)
            if adapter is None:
                raise ConnectorRuntimeUnavailable(f"no runtime adapter registered for {binding.connector_id}")
            raw = adapter.scan(binding.source_id, binding.location)
            result = self._normalize_result(
                raw, source_id=binding.source_id, max_assets=self.max_assets_per_scan
            )
            status = result["status"]
            return result
        finally:
            elapsed_ms = int((time.monotonic() - started) * 1000)
            event = {
                "occurredAt": datetime.now(timezone.utc).isoformat(),
                "principalId": principal.principal_id,
                "tenantId": principal.tenant_id,
                "sourceId": binding.source_id,
                "connectorId": binding.connector_id,
                "status": status,
                "assetCount": result.get("assetCount") if result else None,
                "durationMs": elapsed_ms,
            }
            self.audit_path.parent.mkdir(parents=True, exist_ok=True)
            with self._lock:
                with self.audit_path.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
                    handle.flush()
