from __future__ import annotations
import json
import tempfile
import unittest
from pathlib import Path
from ontology_software_factory.knowledge_graph import KnowledgeGraphError, KnowledgeGraphStore
from ontology_software_factory.ontology_versioning import create_snapshot

ROOT = Path(__file__).resolve().parents[1]

class KnowledgeGraphStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = KnowledgeGraphStore(Path(self.tmp.name) / "graph.sqlite")
        ontology = json.loads((ROOT / "ontology/software-factory-ontology.json").read_text(encoding="utf-8"))
        self.binding = create_snapshot(ontology, actor="test", reason="graph test")
        self.source = {"sourceId": "repo:demo", "locator": "docs/domain.md", "content": "Product contains Component"}
        self.store.put_entity(tenant_id="t1", entity_id="p1", entity_type="Product",
            properties={"name": "Demo Product"}, binding=self.binding, source=self.source)
        self.store.put_entity(tenant_id="t1", entity_id="c1", entity_type="Component",
            properties={"name": "API"}, binding=self.binding, source=self.source)
    def tearDown(self):
        self.tmp.cleanup()
    def test_tenant_scoped_search(self):
        self.assertEqual(len(self.store.search_entities(tenant_id="t1")), 2)
        self.assertEqual(self.store.search_entities(tenant_id="t2"), [])
    def test_relation_endpoint_validation_and_neighborhood(self):
        self.store.put_relation(tenant_id="t1", relation_id="e1", relation_type="containsComponent",
            source_entity_id="p1", target_entity_id="c1", properties={}, binding=self.binding, source=self.source)
        graph = self.store.neighborhood(tenant_id="t1", entity_id="p1")
        self.assertEqual(len(graph["nodes"]), 2)
        self.assertEqual(len(graph["edges"]), 1)
        self.assertEqual(graph["edges"][0]["provenance"]["sourceId"], "repo:demo")
    def test_invalid_endpoint_order_is_rejected(self):
        with self.assertRaises(KnowledgeGraphError):
            self.store.put_relation(tenant_id="t1", relation_id="bad", relation_type="containsComponent",
                source_entity_id="c1", target_entity_id="p1", properties={}, binding=self.binding, source=self.source)
    def test_unknown_class_and_tampered_snapshot_are_rejected(self):
        with self.assertRaises(KnowledgeGraphError):
            self.store.put_entity(tenant_id="t1", entity_id="x", entity_type="Unknown",
                properties={}, binding=self.binding, source=self.source)
        tampered = dict(self.binding); tampered["digest"] = "0" * 64
        with self.assertRaises(KnowledgeGraphError):
            self.store.put_entity(tenant_id="t1", entity_id="y", entity_type="Product",
                properties={}, binding=tampered, source=self.source)
    def test_cross_tenant_relation_is_rejected(self):
        with self.assertRaises(KnowledgeGraphError):
            self.store.put_relation(tenant_id="t2", relation_id="e2", relation_type="containsComponent",
                source_entity_id="p1", target_entity_id="c1", properties={}, binding=self.binding, source=self.source)

if __name__ == "__main__":
    unittest.main()
