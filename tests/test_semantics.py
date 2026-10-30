from __future__ import annotations
import copy
import json
import sys
import unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from ontology_software_factory.semantics import validate_entity_graph  # noqa: E402

class EntityGraphSemanticsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.entities = json.loads((ROOT / "contracts" / "examples" / "sample-entities.json").read_text(encoding="utf-8"))

    def test_sample_graph_passes(self):
        self.assertEqual(validate_entity_graph(self.entities), [])

    def test_duplicate_id_is_rejected(self):
        graph = copy.deepcopy(self.entities)
        graph.append(copy.deepcopy(graph[0]))
        self.assertTrue(any("duplicate entity id" in e for e in validate_entity_graph(graph)))

    def test_dangling_reference_is_rejected(self):
        graph = copy.deepcopy(self.entities)
        build = next(e for e in graph if e["entityType"] == "Build")
        build["versionId"] = "sf:version:missing"
        self.assertTrue(any("does not exist" in e for e in validate_entity_graph(graph)))

    def test_wrong_reference_type_is_rejected(self):
        graph = copy.deepcopy(self.entities)
        build = next(e for e in graph if e["entityType"] == "Build")
        build["versionId"] = "sf:component:event-broker"
        self.assertTrue(any("expected Version, got Component" in e for e in validate_entity_graph(graph)))

    def test_version_must_match_build_component(self):
        graph = copy.deepcopy(self.entities)
        version = next(e for e in graph if e["entityType"] == "Version")
        version["componentId"] = "sf:component:other-component"
        errs = validate_entity_graph(graph)
        self.assertTrue(any("does not exist" in e for e in errs) or any("different component" in e for e in errs))

    def test_succeeded_build_needs_artifact(self):
        graph = copy.deepcopy(self.entities)
        build = next(e for e in graph if e["entityType"] == "Build")
        build["artifactIds"] = []
        self.assertTrue(any("succeeded Build must reference" in e for e in validate_entity_graph(graph)))

    def test_test_counts_must_balance(self):
        graph = copy.deepcopy(self.entities)
        run = next(e for e in graph if e["entityType"] == "TestRun")
        run["failed"] = 1
        self.assertTrue(any("must equal total" in e for e in validate_entity_graph(graph)))

    def test_passed_test_run_cannot_have_failures(self):
        graph = copy.deepcopy(self.entities)
        run = next(e for e in graph if e["entityType"] == "TestRun")
        run["total"] = 13
        run["failed"] = 1
        self.assertTrue(any("status passed requires failed = 0" in e for e in validate_entity_graph(graph)))

    def test_cross_tenant_reference_is_rejected(self):
        graph = copy.deepcopy(self.entities)
        component = next(e for e in graph if e["entityType"] == "Component")
        component["tenantId"] = "another-tenant"
        errors = validate_entity_graph(graph)
        self.assertTrue(any("cross-tenant reference is not allowed" in e for e in errors))

    def test_component_current_version_must_belong_to_component(self):
        graph = copy.deepcopy(self.entities)
        component = next(e for e in graph if e["entityType"] == "Component")
        version = next(e for e in graph if e["entityType"] == "Version")
        version["componentId"] = "sf:component:other-component"
        errors = validate_entity_graph(graph)
        self.assertTrue(any("currentVersionId points to a Version belonging to another component" in e for e in errors))

    def test_vulnerability_version_must_belong_to_same_component(self):
        graph = copy.deepcopy(self.entities)
        version = next(e for e in graph if e["entityType"] == "Version")
        version["componentId"] = "sf:component:other-component"
        errors = validate_entity_graph(graph)
        self.assertTrue(any("affected version" in e and "different component" in e for e in errors))

    def test_release_version_must_belong_to_product_component(self):
        graph = copy.deepcopy(self.entities)
        product = next(e for e in graph if e["entityType"] == "Product")
        product["componentIds"] = []
        errors = validate_entity_graph(graph)
        self.assertTrue(any("is not part of product" in e for e in errors))

    def test_production_success_requires_approval_ref(self):
        graph = copy.deepcopy(self.entities)
        deployment = next(e for e in graph if e["entityType"] == "Deployment")
        deployment["environment"] = "prod"
        deployment["status"] = "succeeded"
        self.assertTrue(any("requires approvalRef" in e for e in validate_entity_graph(graph)))

if __name__ == "__main__":
    unittest.main()
