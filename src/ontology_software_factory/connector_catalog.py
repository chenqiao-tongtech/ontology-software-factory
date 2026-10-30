"""Policy-aware catalog for source and agent-action connector contracts."""
from __future__ import annotations
import json
from dataclasses import dataclass
from pathlib import Path
from jsonschema import Draft202012Validator


class ConnectorPolicyError(PermissionError):
    """A connector operation is unknown, disabled, or not approved."""


@dataclass(frozen=True)
class ConnectorDescriptor:
    connector_id: str
    category: str
    direction: str
    implementation_status: str
    operations: tuple[str, ...]
    approval_required: bool
    auth_mode: str
    credential_ref: str | None
    network_egress: str
    data_classes: tuple[str, ...]
    notes: str


class ConnectorCatalog:
    """Loads reviewed descriptors; does not instantiate network clients."""

    def __init__(self, root: str | Path):
        root = Path(root).resolve()
        schema = json.loads((root / "connectors/schemas/connector-registry.schema.json").read_text(encoding="utf-8"))
        document = json.loads((root / "connectors/registry.json").read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        errors = list(Draft202012Validator(schema).iter_errors(document))
        if errors:
            raise ValueError(f"invalid connector registry: {errors[0].message}")
        self._items: dict[str, ConnectorDescriptor] = {}
        for item in document["connectors"]:
            key = item["connectorId"]
            if key in self._items:
                raise ValueError(f"duplicate connectorId: {key}")
            if item["category"] == "ontology-source" and item["direction"] != "read":
                raise ValueError(f"ontology source must be read-only: {key}")
            if item["category"] == "agent-action" and item["direction"] != "write":
                raise ValueError(f"agent action must be write-capable: {key}")
            if item["authMode"] in {"secret-reference", "oauth2"} and not item["credentialRef"]:
                raise ValueError(f"authenticated connector needs credentialRef: {key}")
            if item["networkEgress"] == "none" and item["authMode"] in {"secret-reference", "oauth2"}:
                raise ValueError(f"network-free connector cannot require remote credentials: {key}")
            self._items[key] = ConnectorDescriptor(
                connector_id=key, category=item["category"], direction=item["direction"],
                implementation_status=item["implementationStatus"], operations=tuple(item["operations"]),
                approval_required=item["approvalRequired"], auth_mode=item["authMode"],
                credential_ref=item["credentialRef"], network_egress=item["networkEgress"],
                data_classes=tuple(item["dataClasses"]), notes=item["notes"],
            )

    def list_connectors(self, *, category: str | None = None, status: str | None = None) -> list[ConnectorDescriptor]:
        values = self._items.values()
        if category is not None:
            values = (item for item in values if item.category == category)
        if status is not None:
            values = (item for item in values if item.implementation_status == status)
        return sorted(values, key=lambda item: item.connector_id)

    def authorize(self, connector_id: str, operation: str, *, approval_granted: bool = False) -> ConnectorDescriptor:
        item = self._items.get(connector_id)
        if item is None:
            raise ConnectorPolicyError(f"unknown connector: {connector_id}")
        if item.implementation_status != "implemented":
            raise ConnectorPolicyError(f"connector {connector_id!r} is {item.implementation_status}; adapter unavailable")
        if operation not in item.operations:
            raise ConnectorPolicyError(f"operation {operation!r} is not declared for {connector_id!r}")
        if item.approval_required and not approval_granted:
            raise ConnectorPolicyError(f"connector operation {connector_id!r}/{operation!r} requires approval")
        return item
