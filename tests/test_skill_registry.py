from __future__ import annotations
import tempfile
import unittest
from pathlib import Path
from ontology_software_factory.skill_registry import SkillRegistry, SkillRegistryError

ROOT = Path(__file__).resolve().parents[1]


class SkillRegistryTests(unittest.TestCase):
    def setUp(self):
        self.registry = SkillRegistry(ROOT)

    def test_loads_all_skills_and_filters_by_role(self):
        skills = self.registry.list_skills()
        self.assertGreaterEqual(len(skills), 8)
        self.assertTrue(self.registry.list_skills(role_id="solution-architect"))

    def test_role_compatibility_is_enforced(self):
        with self.assertRaises(SkillRegistryError):
            self.registry.get("architecture-plan", role_id="test-agent")

    def test_instructions_are_loaded_for_compatible_role(self):
        text = self.registry.load_instructions("architecture-plan", role_id="solution-architect")
        self.assertTrue(text.strip())

    def test_content_lock_detects_definition_or_instruction_drift(self):
        lock = self.registry.create_lock(["architecture-plan"], role_id="solution-architect")
        self.assertTrue(self.registry.verify_lock(lock))
        lock["skills"][0]["digest"] = "0" * 64
        self.assertFalse(self.registry.verify_lock(lock))

    def test_unknown_skill_fails_closed(self):
        with self.assertRaises(SkillRegistryError):
            self.registry.get("unknown-skill")


if __name__ == "__main__":
    unittest.main()
