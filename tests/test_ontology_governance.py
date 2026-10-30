from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ontology_software_factory.ontology_governance import (
    analyze_consumer_impact,
    build_consumer_graph,
    compatibility_report,
)
from ontology_software_factory.ontology_versioning import create_snapshot


class OntologyGovernanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        for path in ("agents/roles", "skills/example-skill", "workflows/definitions", "contracts/schemas"):
            (self.root / path).mkdir(parents=True, exist_ok=True)
        self.ontology = {
            "ontologyId": "test",
            "ontologyVersion": "1.0.0",
            "classes": [{"name": "Requirement"}, {"name": "Artifact"}, {"name": "Build"}],
            "relations": [{"name": "produces", "source": "Build", "target": "Artifact", "field": "artifactIds", "cardinality": "0..*"}],
            "controlledVocabularies": {"status": ["draft", "active"]},
            "mvpInvariants": ["Entity IDs are unique"],
            "operationalExtensions": {"classes": [{"name": "AgentTask"}], "relations": []},
        }
        self._write("ontology/consumer-reference-map.json", {
            "schemaVersion": "1.0.0",
            "roleGlob": "agents/roles/*.json",
            "skillGlob": "skills/*/skill.json",
            "workflowGlob": "workflows/definitions/*.json",
            "toolCatalog": "agents/tool-catalog.json",
            "contractFiles": ["contracts/schemas/agent-task.schema.json"],
            "classReferenceFields": ["inputEntityTypes", "outputEntityTypes"],
        })
        self._write("agents/roles/analyst.json", {
            "roleId": "analyst", "displayName": "Analyst",
            "inputEntityTypes": ["Requirement"], "outputEntityTypes": ["Artifact"],
            "skillIds": ["example-skill"], "toolIds": ["contract.validate"],
        })
        self._write("skills/example-skill/skill.json", {
            "skillId": "example-skill", "title": "Example",
            "compatibleRoleIds": ["analyst"], "inputEntityTypes": ["Requirement"],
            "outputEntityTypes": ["Artifact"], "requiredToolIds": ["contract.validate"],
        })
        self._write("workflows/definitions/delivery.json", {
            "id": "delivery", "name": "Delivery", "steps": [
                {"id": "analysis", "roleId": "analyst", "skillId": "example-skill", "executionMode": "agent"},
                {"id": "approval", "roleId": "human-approver", "skillId": None, "executionMode": "human"},
            ],
        })
        self._write("agents/tool-catalog.json", {"tools": [{"toolId": "contract.validate"}]})
        self._write("contracts/schemas/agent-task.schema.json", {
            "title": "Agent Task", "properties": {"entityType": {"enum": ["Requirement", "Artifact"]}}
        })

    def tearDown(self):
        self.tmp.cleanup()

    def _write(self, rel, value):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding="utf-8")

    def test_graph_builds_explicit_edges_across_roles_skills_workflows_tools_and_contracts(self):
        graph = build_consumer_graph(self.root, self.ontology)
        self.assertEqual(graph["summary"]["roles"], 1)
        self.assertEqual(graph["summary"]["skills"], 1)
        self.assertEqual(graph["summary"]["workflows"], 1)
        self.assertEqual(graph["summary"]["tools"], 1)
        self.assertEqual(graph["summary"]["contracts"], 1)
        self.assertEqual(graph["issues"], [])
        relations = {(e["source"], e["target"], e["relation"]) for e in graph["edges"]}
        self.assertIn(("class:Requirement", "role:analyst", "consumes-ontology-class"), relations)
        self.assertIn(("role:analyst", "skill:example-skill", "uses-skill"), relations)
        self.assertIn(("workflow:delivery/step:analysis", "role:analyst", "dispatches-role"), relations)
        self.assertIn(("workflow:delivery/step:approval", "human-role:human-approver", "requires-human-approval-role"), relations)
        self.assertIn(("class:Artifact", "contract:agent-task.schema", "constrains-entity-type"), relations)

    def test_impact_traverses_class_to_role_to_skill_and_workflow(self):
        graph = build_consumer_graph(self.root, self.ontology)
        impact = analyze_consumer_impact(["Requirement"], graph)
        ids = {item["id"] for item in impact["affectedConsumers"]}
        self.assertIn("role:analyst", ids)
        self.assertIn("skill:example-skill", ids)
        self.assertIn("workflow:delivery", ids)
        self.assertIn("workflow:delivery/step:analysis", ids)
        self.assertIn("contract:agent-task.schema", ids)

    def test_removed_class_impact_uses_historical_class_reference(self):
        historical = self.ontology
        current = {**self.ontology, "classes": [{"name": "Artifact"}, {"name": "Build"}]}
        graph = build_consumer_graph(self.root, current, additional_ontologies=[historical])
        impact = analyze_consumer_impact(["Requirement"], graph)
        ids = {item["id"] for item in impact["affectedConsumers"]}
        self.assertIn("role:analyst", ids)
        self.assertIn("skill:example-skill", ids)
        self.assertIn("workflow:delivery/step:analysis", ids)

    def test_unknown_class_and_missing_tool_are_reported(self):
        role = json.loads((self.root / "agents/roles/analyst.json").read_text())
        role["outputEntityTypes"].append("UnknownClass")
        role["toolIds"].append("not-a-tool")
        self._write("agents/roles/analyst.json", role)
        graph = build_consumer_graph(self.root, self.ontology)
        codes = {item["code"] for item in graph["issues"]}
        self.assertIn("unknown-ontology-class", codes)
        self.assertIn("unknown-tool-reference", codes)

    def test_compatibility_detects_removed_class_and_requires_major_bump(self):
        before_ontology = self.ontology
        after_ontology = {**self.ontology, "ontologyVersion": "1.1.0",
                          "classes": [{"name": "Requirement"}, {"name": "Build"}]}
        before = create_snapshot(before_ontology, actor="owner", reason="baseline")
        after = create_snapshot(after_ontology, actor="owner", reason="change")
        report = compatibility_report(before, after)
        self.assertFalse(report["compatible"])
        self.assertTrue(any(item["kind"] == "class-removed" for item in report["breakingChanges"]))
        self.assertTrue(any(item["kind"] == "major-version-bump-required" for item in report["reviewItems"]))

    def test_major_version_bump_allows_breaking_change_but_requires_review(self):
        before = create_snapshot(self.ontology, actor="owner", reason="baseline")
        after_ontology = {**self.ontology, "ontologyVersion": "2.0.0",
                          "classes": [{"name": "Requirement"}, {"name": "Build"}]}
        after = create_snapshot(after_ontology, actor="owner", reason="major release")
        report = compatibility_report(before, after)
        self.assertTrue(report["compatible"])
        self.assertTrue(report["reviewRequired"])
        self.assertTrue(report["majorVersionBump"])

    def test_additive_class_and_vocabulary_values_are_compatible(self):
        before = create_snapshot(self.ontology, actor="owner", reason="baseline")
        after_ontology = {**self.ontology, "ontologyVersion": "1.1.0",
                          "classes": self.ontology["classes"] + [{"name": "Release"}],
                          "controlledVocabularies": {"status": ["draft", "active", "paused"]}}
        after = create_snapshot(after_ontology, actor="owner", reason="additive")
        report = compatibility_report(before, after)
        self.assertTrue(report["compatible"])
        self.assertTrue(report["reviewRequired"])
        self.assertEqual(report["summary"]["addedClasses"], 1)


if __name__ == "__main__":
    unittest.main()
