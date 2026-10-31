"""Default-deny registry for explicitly reviewed outbound action connectors."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


class ActionConnectorPolicyError(PermissionError):
    pass


@dataclass(frozen=True)
class ActionConnector:
    connector_id: str
    adapter_type: str
    tool_ids: frozenset[str]
    methods: frozenset[str]
    approval_required: bool
    idempotency_required: bool


class ActionConnectorRegistry:
    """Loads reviewed connector-to-tool bindings; never discovers or enables tools implicitly."""

    def __init__(self, project_root: str | Path):
        self.root = Path(project_root).resolve()
        raw = json.loads((self.root / "policies/action-connectors.json").read_text(encoding="utf-8"))
        if raw.get("schemaVersion") != "1.0.0" or raw.get("defaultDecision") != "deny":
            raise ValueError("unsupported action connector policy or non-default-deny configuration")
        tool_defs = json.loads((self.root / "tools/registry.json").read_text(encoding="utf-8"))["tools"]
        self.tools = {item["toolId"]: item for item in tool_defs}
        self.connectors: dict[str, ActionConnector] = {}
        for item in raw.get("connectors", []):
            connector_id = str(item.get("connectorId", "")).strip()
            adapter_type = item.get("adapterType")
            tool_ids = frozenset(item.get("toolIds", []))
            methods = frozenset(str(x).upper() for x in item.get("methods", []))
            if not connector_id or connector_id in self.connectors:
                raise ValueError("connectorId must be non-empty and unique")
            if adapter_type not in {"http-json", "mcp-stdio"} or not tool_ids:
                raise ValueError(f"connector {connector_id} requires a supported adapterType and explicit toolIds")
            if not tool_ids.issubset(self.tools):
                raise ValueError(f"connector {connector_id} references an unknown tool")
            if not methods or not methods.issubset({"GET", "POST", "PUT", "PATCH", "DELETE", "MCP_TOOLS_CALL"}):
                raise ValueError(f"connector {connector_id} contains unsupported methods")
            approval_required = bool(item.get("approvalRequired", True))
            idempotency_required = bool(item.get("idempotencyRequired", True))
            if any(self.tools[tool_id].get("approvalRequired") for tool_id in tool_ids) and not approval_required:
                raise ValueError(f"connector {connector_id} cannot weaken a tool's approval requirement")
            if not idempotency_required and any(method != "GET" for method in methods):
                raise ValueError(f"connector {connector_id} cannot disable idempotency for mutating methods")
            self.connectors[connector_id] = ActionConnector(
                connector_id, adapter_type, tool_ids, methods, approval_required, idempotency_required
            )

    def authorize(self, connector_id: str, *, tool_id: str, method: str) -> ActionConnector:
        connector = self.connectors.get(connector_id)
        normalized_method = method.upper()
        if connector is None or tool_id not in connector.tool_ids or normalized_method not in connector.methods:
            raise ActionConnectorPolicyError("action connector, tool, or method is not explicitly allow-listed")
        return connector
