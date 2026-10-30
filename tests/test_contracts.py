from __future__ import annotations
import copy
import json
import sys
import unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from ontology_software_factory.contracts import load_entity_schema, validate_entity  # noqa: E402

class EntityContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = load_entity_schema()
        cls.entities = json.loads((ROOT / "contracts" / "examples" / "sample-entities.json").read_text(encoding="utf-8"))

    def test_all_sample_entities_match_schema(self):
        for entity in self.entities:
            with self.subTest(entity=entity.get("id")):
                self.assertEqual(validate_entity(entity, self.schema), [])

    def test_invalid_requirement_priority_is_rejected(self):
        requirement = copy.deepcopy(next(e for e in self.entities if e["entityType"] == "Requirement"))
        requirement["priority"] = "urgent"
        self.assertTrue(validate_entity(requirement, self.schema))

    def test_missing_required_field_is_rejected(self):
        requirement = copy.deepcopy(next(e for e in self.entities if e["entityType"] == "Requirement"))
        requirement.pop("acceptanceCriteria")
        self.assertTrue(validate_entity(requirement, self.schema))

    def test_unknown_field_is_rejected(self):
        component = copy.deepcopy(next(e for e in self.entities if e["entityType"] == "Component"))
        component["freeFormAgentGuess"] = "done"
        self.assertTrue(validate_entity(component, self.schema))

    def test_bad_date_time_is_rejected(self):
        entity = copy.deepcopy(self.entities[0])
        entity["createdAt"] = "yesterday night"
        self.assertTrue(validate_entity(entity, self.schema))

if __name__ == "__main__":
    unittest.main()
