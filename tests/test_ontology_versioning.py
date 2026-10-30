from __future__ import annotations

import unittest

from ontology_software_factory.ontology_versioning import (
    create_snapshot,
    diff_snapshots,
    ontology_digest,
)


def sample():
    return {
        "ontologyId": "software-factory-core",
        "ontologyVersion": "1.0.0",
        "schemaVersion": "1.0.0",
        "classes": [{"name": "Product", "description": "A product"}, {"name": "Component"}],
        "relations": [{"name": "contains", "source": "Product", "target": ["Component"], "field": "componentIds"}],
        "controlledVocabularies": {"status": ["draft", "active"]},
        "mvpInvariants": ["IDs must be unique"],
        "operationalExtensions": {
            "classes": [{"name": "AgentRole"}],
            "relations": [{"name": "usesSkill", "source": "AgentRole", "target": "Skill"}],
        },
    }


class OntologyVersioningTests(unittest.TestCase):
    def test_digest_is_stable_across_mapping_key_order(self):
        first = {"ontologyId": "x", "classes": [{"name": "A", "description": "a"}]}
        second = {"classes": [{"description": "a", "name": "A"}], "ontologyId": "x"}
        self.assertEqual(ontology_digest(first), ontology_digest(second))

    def test_snapshot_requires_actor_and_reason_and_is_self_contained(self):
        ontology = sample()
        with self.assertRaises(ValueError):
            create_snapshot(ontology, actor="", reason="approved")
        with self.assertRaises(ValueError):
            create_snapshot(ontology, actor="reviewer", reason="")
        snap = create_snapshot(ontology, actor="reviewer", reason="baseline", created_at="2026-10-30T00:00:00+00:00")
        self.assertEqual(snap["ontology"], ontology)
        self.assertEqual(snap["ontologyVersion"], "1.0.0")
        self.assertEqual(snap["createdAt"], "2026-10-30T00:00:00+00:00")
        ontology["classes"].clear()
        self.assertEqual(len(snap["ontology"]["classes"]), 2)

    def test_diff_reports_class_relation_vocabulary_and_invariant_changes(self):
        before = create_snapshot(sample(), actor="reviewer", reason="baseline")
        changed = sample()
        changed["ontologyVersion"] = "1.1.0"
        changed["classes"] = [{"name": "Product", "description": "Updated product"}, {"name": "Release"}]
        changed["relations"][0]["field"] = "products"
        changed["controlledVocabularies"]["status"].append("retired")
        changed["mvpInvariants"].append("Evidence must be traceable")
        after = create_snapshot(changed, actor="reviewer", reason="change")
        result = diff_snapshots(before, after)
        self.assertTrue(result["changed"])
        self.assertEqual(len(result["sections"]["coreClasses"]["added"]), 1)
        self.assertEqual(len(result["sections"]["coreClasses"]["removed"]), 1)
        self.assertEqual(len(result["sections"]["coreClasses"]["changed"]), 1)
        self.assertEqual(len(result["sections"]["coreRelations"]["changed"]), 1)
        self.assertEqual(len(result["sections"]["controlledVocabularies"]["changed"]), 1)
        self.assertEqual(len(result["sections"]["mvpInvariants"]["added"]), 1)
        self.assertIn("Product", result["impact"]["affectedClasses"])
        self.assertIn("Component", result["impact"]["affectedClasses"])
        self.assertTrue(result["impact"]["reviewRequired"])
        self.assertEqual(result["impact"]["potentialConsumers"], [])

    def test_identical_snapshots_have_no_structural_change(self):
        ontology = sample()
        before = create_snapshot(ontology, actor="reviewer", reason="one")
        after = create_snapshot(ontology, actor="reviewer", reason="two")
        result = diff_snapshots(before, after)
        self.assertFalse(result["changed"])
        self.assertFalse(result["impact"]["reviewRequired"])
        self.assertEqual(result["summary"]["coreClasses"]["added"], 0)


if __name__ == "__main__":
    unittest.main()
