from __future__ import annotations
import json
import tempfile
import unittest
from pathlib import Path
from ontology_software_factory.api_contract_connectors import (
    AsyncAPIJsonConnector, GraphQLSDLConnector, OpenAPIJsonConnector, ProtobufConnector
)
from ontology_software_factory.source_connectors import SourceConnectorError


class ApiContractConnectorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def write(self, name, content):
        path = self.root / name
        path.write_text(content, encoding="utf-8")
        return str(path)

    def test_openapi_json_extracts_operations_and_schemas(self):
        spec = {"openapi": "3.0.3", "info": {"title": "Orders", "version": "1"},
                "paths": {"/orders": {"get": {"operationId": "listOrders", "responses": {"200": {}}}}},
                "components": {"schemas": {"Order": {"type": "object", "properties": {"id": {"type": "string"}}}}}}
        connector = OpenAPIJsonConnector([self.root])
        result = connector.scan("src-1", self.write("openapi.json", json.dumps(spec)))
        self.assertEqual(result.status, "complete")
        self.assertTrue(any(item.kind == "api-operation" and item.name == "listOrders" for item in result.assets))
        self.assertTrue(any(item.kind == "api-schema" and item.name == "Order" for item in result.assets))

    def test_asyncapi_json_extracts_event_channels(self):
        spec = {"asyncapi": "2.6.0", "info": {"title": "Events", "version": "1"},
                "channels": {"orders.created": {"publish": {"message": {"$ref": "#/components/messages/OrderCreated"}}}},
                "components": {"messages": {"OrderCreated": {"payload": {"type": "object", "properties": {"id": {"type": "string"}}}}}}}
        result = AsyncAPIJsonConnector([self.root]).scan("src-2", self.write("asyncapi.json", json.dumps(spec)))
        self.assertTrue(any(item.kind == "event-channel" for item in result.assets))
        self.assertTrue(any(item.kind == "event-message" for item in result.assets))

    def test_graphql_sdl_extracts_types_and_fields(self):
        sdl = "type Query { orders: [Order!]! }\ntype Order { id: ID! status: String }\nenum Status { OPEN CLOSED }"
        result = GraphQLSDLConnector([self.root]).scan("src-3", self.write("schema.graphql", sdl))
        order = next(item for item in result.assets if item.name == "Order")
        self.assertEqual(order.metadata["definitionKind"], "type")
        self.assertTrue(order.metadata["fields"])

    def test_protobuf_extracts_messages_services_and_rpcs(self):
        proto = 'syntax = "proto3"; package orders.v1; message Order { string id = 1; } service Orders { rpc GetOrder (GetOrderRequest) returns (Order); }'
        result = ProtobufConnector([self.root]).scan("src-4", self.write("orders.proto", proto))
        self.assertTrue(any(item.kind == "protobuf-message" for item in result.assets))
        self.assertTrue(any(item.kind == "protobuf-rpc" for item in result.assets))

    def test_path_outside_allowed_roots_is_rejected(self):
        with tempfile.TemporaryDirectory() as other:
            outside = Path(other) / "schema.graphql"
            outside.write_text("type Query { ok: Boolean }")
            with self.assertRaises(SourceConnectorError):
                GraphQLSDLConnector([self.root]).scan("src-5", outside)


if __name__ == "__main__":
    unittest.main()
