from __future__ import annotations
import json
import unittest
from pathlib import Path

from ontology_software_factory.ontology_modules import validate_module_manifest

ROOT = Path(__file__).resolve().parents[1]


class OntologyModuleManifestTests(unittest.TestCase):
    def setUp(self):
        self.ontology = json.loads((ROOT / "ontology/software-factory-ontology.json").read_text(encoding="utf-8"))
        self.manifest = json.loads((ROOT / "ontology/module-manifest.json").read_text(encoding="utf-8"))

    def test_manifest_covers_every_canonical_class_and_relation_once(self):
        self.assertEqual(validate_module_manifest(self.ontology, self.manifest), [])

    def test_missing_class_is_rejected(self):
        self.manifest["modules"][0]["classes"].pop()
        errors = validate_module_manifest(self.ontology, self.manifest)
        self.assertTrue(any("missing from module manifest" in item for item in errors))

    def test_duplicate_class_assignment_is_rejected(self):
        self.manifest["modules"][1]["classes"].append(self.manifest["modules"][0]["classes"][0])
        errors = validate_module_manifest(self.ontology, self.manifest)
        self.assertTrue(any("multiple modules" in item for item in errors))

    def test_manifest_cannot_become_a_second_authoritative_source(self):
        self.manifest["authority"] = "module-definitions"
        errors = validate_module_manifest(self.ontology, self.manifest)
        self.assertTrue(any("cannot claim authority" in item for item in errors))


if __name__ == "__main__":
    unittest.main()
