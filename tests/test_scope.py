from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ontology_software_factory.scope import load_manifest, validate_manifest  # noqa: E402


class ScopeManifestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.valid_manifest = load_manifest(ROOT / "config" / "mvp-scope.json")

    def test_repository_manifest_passes(self) -> None:
        self.assertEqual(validate_manifest(self.valid_manifest, ROOT), [])

    def test_included_and_excluded_capabilities_must_not_overlap(self) -> None:
        data = copy.deepcopy(self.valid_manifest)
        data["mvp"]["excluded_capabilities"].append(
            data["mvp"]["included_capabilities"][0]
        )
        self.assertTrue(any("both included and excluded" in e for e in validate_manifest(data, ROOT)))

    def test_acceptance_ids_must_be_unique(self) -> None:
        data = copy.deepcopy(self.valid_manifest)
        data["acceptance_criteria"][1]["id"] = data["acceptance_criteria"][0]["id"]
        self.assertTrue(any("duplicate acceptance criterion id" in e for e in validate_manifest(data, ROOT)))

    def test_required_module_must_exist(self) -> None:
        data = copy.deepcopy(self.valid_manifest)
        data["required_modules"].append("directory_that_does_not_exist")
        self.assertTrue(any("does not exist" in e for e in validate_manifest(data, ROOT)))

    def test_evidence_id_must_be_traceable(self) -> None:
        data = copy.deepcopy(self.valid_manifest)
        data["acceptance_criteria"][0]["id"] = "MVP-99"
        self.assertTrue(any("not traceable" in e for e in validate_manifest(data, ROOT)))


if __name__ == "__main__":
    unittest.main()
