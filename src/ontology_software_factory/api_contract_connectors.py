"""Deterministic, offline parsers for API and event contract source files.

Supported inputs: OpenAPI JSON, AsyncAPI JSON, GraphQL SDL and Protocol Buffers.
YAML and live endpoint introspection are intentionally outside this adapter.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from .source_connectors import SourceAsset, SourceConnectorError, SourceScanResult, _asset_id


class _ContractFileConnector:
    source_type = "api-contract"

    def __init__(self, allowed_roots: list[str | Path], *, max_file_bytes: int = 2_000_000):
        self.allowed_roots = tuple(Path(item).expanduser().resolve() for item in allowed_roots)
        self.max_file_bytes = max_file_bytes
        if not self.allowed_roots:
            raise ValueError("at least one allowed root is required")

    def _read(self, location: str | Path) -> tuple[Path, str, str]:
        raw = Path(location).expanduser()
        if raw.is_symlink():
            raise SourceConnectorError("contract source must not be a symbolic link")
        try:
            path = raw.resolve(strict=True)
        except OSError as exc:
            raise SourceConnectorError("contract source file is unavailable") from exc
        if not path.is_file() or not any(path == root or root in path.parents for root in self.allowed_roots):
            raise SourceConnectorError("contract source is outside allowed roots or is not a file")
        if path.stat().st_size > self.max_file_bytes:
            raise SourceConnectorError("contract source exceeds configured size limit")
        content = path.read_text(encoding="utf-8")
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        return path, content, digest

    @staticmethod
    def _asset(source_id: str, kind: str, name: str, locator: str, digest: str, metadata: dict[str, Any]) -> SourceAsset:
        return SourceAsset(
            asset_id=_asset_id(source_id, locator, kind), source_id=source_id,
            kind=kind, name=name, locator=locator, content_sha256=digest,
            metadata=metadata,
        )


class OpenAPIJsonConnector(_ContractFileConnector):
    source_type = "openapi"

    def scan(self, source_id: str, location: str | Path) -> SourceScanResult:
        path, content, digest = self._read(location)
        try:
            spec = json.loads(content)
        except json.JSONDecodeError as exc:
            raise SourceConnectorError("OpenAPI adapter accepts JSON documents only") from exc
        if not isinstance(spec, dict) or not str(spec.get("openapi", "")).startswith("3."):
            raise SourceConnectorError("document is not an OpenAPI 3.x JSON specification")
        assets = []
        info = spec.get("info") if isinstance(spec.get("info"), dict) else {}
        for route, methods in sorted((spec.get("paths") or {}).items()):
            if not isinstance(methods, dict):
                continue
            for method, operation in sorted(methods.items()):
                if method.lower() not in {"get", "post", "put", "patch", "delete", "head", "options", "trace"} or not isinstance(operation, dict):
                    continue
                name = str(operation.get("operationId") or f"{method.upper()} {route}")
                assets.append(self._asset(
                    source_id, "api-operation", name, f"openapi:{path.name}#{method.lower()}:{route}", digest,
                    {"method": method.upper(), "path": route, "operationId": operation.get("operationId"),
                     "summary": operation.get("summary"), "tags": operation.get("tags", []),
                     "parameters": [p.get("name") for p in operation.get("parameters", []) if isinstance(p, dict)],
                     "requestBody": bool(operation.get("requestBody")), "responseCodes": sorted((operation.get("responses") or {}).keys())},
                ))
        schemas = spec.get("components", {}).get("schemas", {}) if isinstance(spec.get("components"), dict) else {}
        if isinstance(schemas, dict):
            for name, schema in sorted(schemas.items()):
                if isinstance(schema, dict):
                    assets.append(self._asset(
                        source_id, "api-schema", str(name), f"openapi:{path.name}#/components/schemas/{name}", digest,
                        {"type": schema.get("type"), "properties": sorted((schema.get("properties") or {}).keys()),
                         "required": schema.get("required", []), "description": schema.get("description")},
                    ))
        assets.insert(0, self._asset(
            source_id, "api-contract", str(info.get("title") or path.stem), f"openapi:{path.name}", digest,
            {"format": "openapi", "version": spec.get("openapi"), "apiVersion": info.get("version"),
             "title": info.get("title"), "operationCount": len([x for x in assets if x.kind == "api-operation"])},
        ))
        return SourceScanResult(source_id, self.source_type, "complete", tuple(assets))


class AsyncAPIJsonConnector(_ContractFileConnector):
    source_type = "asyncapi"

    def scan(self, source_id: str, location: str | Path) -> SourceScanResult:
        path, content, digest = self._read(location)
        try:
            spec = json.loads(content)
        except json.JSONDecodeError as exc:
            raise SourceConnectorError("AsyncAPI adapter accepts JSON documents only") from exc
        if not isinstance(spec, dict) or "asyncapi" not in spec:
            raise SourceConnectorError("document is not an AsyncAPI JSON specification")
        assets = []
        for channel, definition in sorted((spec.get("channels") or {}).items()):
            if not isinstance(definition, dict):
                continue
            assets.append(self._asset(
                source_id, "event-channel", channel, f"asyncapi:{path.name}#/channels/{channel}", digest,
                {"address": definition.get("address"), "description": definition.get("description"),
                 "publish": bool(definition.get("publish")), "subscribe": bool(definition.get("subscribe"))},
            ))
        messages = spec.get("components", {}).get("messages", {}) if isinstance(spec.get("components"), dict) else {}
        if isinstance(messages, dict):
            for name, message in sorted(messages.items()):
                if isinstance(message, dict):
                    payload = message.get("payload", {})
                    assets.append(self._asset(
                        source_id, "event-message", str(name), f"asyncapi:{path.name}#/components/messages/{name}", digest,
                        {"title": message.get("title"), "summary": message.get("summary"),
                         "payloadType": payload.get("type") if isinstance(payload, dict) else None,
                         "payloadProperties": sorted((payload.get("properties") or {}).keys()) if isinstance(payload, dict) else []},
                    ))
        assets.insert(0, self._asset(
            source_id, "event-contract", str(spec.get("info", {}).get("title") or path.stem),
            f"asyncapi:{path.name}", digest,
            {"format": "asyncapi", "version": spec.get("asyncapi"), "apiVersion": spec.get("info", {}).get("version")},
        ))
        return SourceScanResult(source_id, self.source_type, "complete", tuple(assets))


class GraphQLSDLConnector(_ContractFileConnector):
    source_type = "graphql-sdl"

    def scan(self, source_id: str, location: str | Path) -> SourceScanResult:
        path, content, digest = self._read(location)
        assets = []
        block = re.compile(r"\b(type|input|interface|enum|scalar|union)\s+(\w+)[^{\n]*\{([^}]*)\}", re.MULTILINE)
        for match in block.finditer(content):
            kind, name, body = match.groups()
            fields = []
            for line in body.splitlines():
                line = line.strip()
                if not line or line.startswith("#") or line.startswith("@"):
                    continue
                field_match = re.match(r"(\w+)\s*(?:\([^)]*\))?\s*:\s*([\[\]!\w]+)", line)
                if field_match:
                    fields.append({"name": field_match.group(1), "type": field_match.group(2)})
            assets.append(self._asset(
                source_id, "graphql-type", name, f"graphql:{path.name}#{kind}:{name}", digest,
                {"definitionKind": kind, "fields": fields},
            ))
        for match in re.finditer(r"\bscalar\s+(\w+)", content):
            name = match.group(1)
            assets.append(self._asset(source_id, "graphql-scalar", name, f"graphql:{path.name}#scalar:{name}", digest, {}))
        for match in re.finditer(r"\bunion\s+(\w+)\s*=\s*([^\n]+)", content):
            name, members = match.groups()
            assets.append(self._asset(source_id, "graphql-union", name, f"graphql:{path.name}#union:{name}", digest,
                                      {"members": [item.strip() for item in members.split("|")]}))
        if not assets:
            raise SourceConnectorError("no supported GraphQL SDL definitions were found")
        assets.insert(0, self._asset(source_id, "api-contract", path.stem, f"graphql:{path.name}", digest,
                                     {"format": "graphql-sdl", "definitionCount": len(assets)}))
        return SourceScanResult(source_id, self.source_type, "complete", tuple(assets))


class ProtobufConnector(_ContractFileConnector):
    source_type = "protobuf"

    def scan(self, source_id: str, location: str | Path) -> SourceScanResult:
        path, content, digest = self._read(location)
        assets = []
        package = re.search(r"\bpackage\s+([\w.]+)\s*;", content)
        syntax = re.search(r'\bsyntax\s*=\s*["\']([^"\']+)["\']\s*;', content)
        for kind in ("message", "enum", "service"):
            for match in re.finditer(rf"\b{kind}\s+(\w+)\s*\{{", content):
                name = match.group(1)
                assets.append(self._asset(
                    source_id, f"protobuf-{kind}", name, f"protobuf:{path.name}#{kind}:{name}", digest,
                    {"package": package.group(1) if package else None,
                     "syntax": syntax.group(1) if syntax else None},
                ))
        for match in re.finditer(r"\brpc\s+(\w+)\s*\(([^)]*)\)\s*returns\s*\(([^)]*)\)", content):
            name, request, response = match.groups()
            assets.append(self._asset(
                source_id, "protobuf-rpc", name, f"protobuf:{path.name}#rpc:{name}", digest,
                {"requestType": request.strip(), "responseType": response.strip()},
            ))
        if not assets:
            raise SourceConnectorError("no supported Protocol Buffers definitions were found")
        return SourceScanResult(source_id, self.source_type, "complete", tuple(assets))
