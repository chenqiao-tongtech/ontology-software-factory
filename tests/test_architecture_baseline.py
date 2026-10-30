import copy
import json
import unittest
from pathlib import Path

from ontology_software_factory.architecture_baseline import validate_baseline, validate_from_root

ROOT = Path(__file__).resolve().parents[1]


class ArchitectureBaselineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.baseline = json.loads((ROOT / "config/architecture-baseline.json").read_text(encoding="utf-8"))

    def test_repository_baseline_passes(self):
        self.assertEqual(validate_from_root(ROOT), [])

    def test_duplicate_subsystem_id_is_rejected(self):
        data = copy.deepcopy(self.baseline)
        data["subsystems"].append(copy.deepcopy(data["subsystems"][0]))
        errors = validate_baseline(ROOT, data)
        self.assertTrue(any("duplicate id" in error for error in errors))

    def test_unknown_dependency_is_rejected(self):
        data = copy.deepcopy(self.baseline)
        data["subsystems"][0]["depends_on"].append("S99")
        errors = validate_baseline(ROOT, data)
        self.assertTrue(any("unknown dependency S99" in error for error in errors))

    def test_dependency_cycle_is_rejected(self):
        data = copy.deepcopy(self.baseline)
        data["subsystems"][0]["depends_on"] = ["S2"]
        data["subsystems"][1]["depends_on"] = ["S1"]
        errors = validate_baseline(ROOT, data)
        self.assertTrue(any("dependency cycle" in error for error in errors))

    def test_missing_architecture_principle_is_rejected(self):
        data = copy.deepcopy(self.baseline)
        data["principles"] = [item for item in data["principles"] if item["id"] != "AP-12"]
        errors = validate_baseline(ROOT, data)
        self.assertTrue(any("AP-12" in error for error in errors))

    def test_implemented_path_must_exist(self):
        data = copy.deepcopy(self.baseline)
        data["subsystems"][1]["modules"][0]["path"] = "ontology/no-such-file.json"
        errors = validate_baseline(ROOT, data)
        self.assertTrue(any("implemented path does not exist" in error for error in errors))

    def test_roadmap_requires_exit_criteria(self):
        data = copy.deepcopy(self.baseline)
        data["roadmap"][0]["exit_criteria"] = []
        errors = validate_baseline(ROOT, data)
        self.assertTrue(any("exit_criteria must not be empty" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
