from __future__ import annotations

import copy
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ontology_software_factory.catalog import (  # noqa: E402
    check_version_readiness,
    load_json,
    validate_catalog,
    version_satisfies,
)


class AssetCatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sample = load_json(ROOT / "catalog" / "examples" / "demo-catalog.json")

    def test_demo_catalog_is_structurally_and_semantically_valid(self):
        self.assertEqual(validate_catalog(self.sample), [])

    def test_duplicate_entity_id_is_rejected(self):
        catalog = copy.deepcopy(self.sample)
        catalog["artifacts"].append(copy.deepcopy(catalog["artifacts"][0]))
        self.assertTrue(any("duplicate catalogue ID" in error for error in validate_catalog(catalog)))

    def test_product_cannot_reference_missing_component(self):
        catalog = copy.deepcopy(self.sample)
        catalog["products"][0]["componentIds"].append("sf:component:missing")
        self.assertTrue(any("referenced ID does not exist" in error for error in validate_catalog(catalog)))

    def test_default_version_must_belong_to_its_component(self):
        catalog = copy.deepcopy(self.sample)
        catalog["components"][0]["defaultVersionId"] = "sf:version:metrics-exporter-0.4.0"
        self.assertTrue(any("defaultVersionId must point" in error for error in validate_catalog(catalog)))

    def test_dependency_resolved_version_must_belong_to_declared_component(self):
        catalog = copy.deepcopy(self.sample)
        dependency = catalog["components"][1]["versions"][0]["dependencies"][0]
        dependency["resolvedVersionId"] = "sf:version:runtime-image-1.27.0"
        self.assertTrue(any("does not belong to componentId" in error for error in validate_catalog(catalog)))

    def test_resolved_version_must_satisfy_constraint(self):
        catalog = copy.deepcopy(self.sample)
        dependency = catalog["components"][1]["versions"][0]["dependencies"][0]
        dependency["versionConstraint"] = ">=4.0.0,<5.0.0"
        self.assertTrue(any("does not satisfy" in error for error in validate_catalog(catalog)))

    def test_dependency_cycle_is_rejected(self):
        catalog = copy.deepcopy(self.sample)
        broker_version = catalog["components"][0]["versions"][0]
        broker_version["dependencies"].append({
            "componentId": "sf:component:metrics-exporter",
            "versionConstraint": "==0.4.0",
            "resolvedVersionId": "sf:version:metrics-exporter-0.4.0",
            "scope": "runtime",
            "optional": False,
            "declaredBy": "manifest",
            "evidenceArtifactIds": []
        })
        self.assertTrue(any("dependency cycle detected" in error for error in validate_catalog(catalog)))

    def test_active_component_requires_license_review(self):
        catalog = copy.deepcopy(self.sample)
        catalog["components"][0]["license"]["reviewStatus"] = "pending"
        self.assertTrue(any("requires approved license review" in error for error in validate_catalog(catalog)))

    def test_compatibility_assertion_requires_verified_evidence(self):
        catalog = copy.deepcopy(self.sample)
        rule = catalog["compatibilityRules"][0]
        rule["status"] = "compatible"
        rule["evidenceArtifactIds"] = ["sf:artifact:compatibility-report"]
        errors = validate_catalog(catalog)
        self.assertTrue(any("compatibility evidence must be verified" in error for error in errors))

    def test_customer_config_cannot_reference_component_outside_product(self):
        catalog = copy.deepcopy(self.sample)
        catalog["customerConfigurations"][0]["baseVersionIds"].append("sf:version:event-broker-3.8.0")
        catalog["products"][0]["componentIds"].remove("sf:component:event-broker")
        self.assertTrue(any("belongs to a component outside the selected product" in error for error in validate_catalog(catalog)))

    def test_secret_like_override_must_use_secret_ref(self):
        catalog = copy.deepcopy(self.sample)
        catalog["customerConfigurations"][0]["overrides"].append({"key": "apiToken", "value": "do-not-store-this"})
        self.assertTrue(any("must not be stored in overrides" in error for error in validate_catalog(catalog)))

    def test_custom_patch_must_belong_to_same_tenant_as_config(self):
        catalog = copy.deepcopy(self.sample)
        catalog["customPatches"][0]["tenantId"] = "another-customer"
        self.assertTrue(any("belongs to a different tenant" in error for error in validate_catalog(catalog)))

    def test_approved_customer_config_requires_approver(self):
        catalog = copy.deepcopy(self.sample)
        catalog["customerConfigurations"][0]["status"] = "approved"
        self.assertTrue(any("requires approvedBy and approvedAt" in error for error in validate_catalog(catalog)))

    def test_approved_custom_patch_requires_tests_and_security_review(self):
        catalog = copy.deepcopy(self.sample)
        patch = catalog["customPatches"][0]
        patch["status"] = "approved"
        patch["testEvidenceArtifactIds"] = []
        patch["securityReviewStatus"] = "pending"
        errors = validate_catalog(catalog)
        self.assertTrue(any("approved patch requires security review" in error for error in errors))
        self.assertTrue(any("approved patch requires test evidence" in error for error in errors))

    def test_readiness_is_blocked_for_unverified_demo_artifacts(self):
        blockers = check_version_readiness(self.sample, "sf:version:event-broker-3.8.0")
        self.assertTrue(any("not verified" in blocker for blocker in blockers))
        self.assertTrue(any("sbomArtifactId is not verified" in blocker for blocker in blockers))

    def test_readiness_policy_can_pass_when_required_metadata_is_marked_verified(self):
        catalog = copy.deepcopy(self.sample)
        artifacts = {item["id"]: item for item in catalog["artifacts"]}
        version = catalog["components"][0]["versions"][0]
        for artifact_id in version["artifactIds"] + [version["sbomArtifactId"], version["provenanceArtifactId"]]:
            artifacts[artifact_id]["verificationStatus"] = "verified"
        self.assertEqual(check_version_readiness(catalog, version["id"]), [])

    def test_exact_semver_constraint(self):
        self.assertTrue(version_satisfies("1.2.3", "1.2.3"))
        self.assertFalse(version_satisfies("1.2.4", "1.2.3"))

    def test_caret_constraint(self):
        self.assertTrue(version_satisfies("1.9.0", "^1.2.0"))
        self.assertFalse(version_satisfies("2.0.0", "^1.2.0"))
        self.assertTrue(version_satisfies("0.2.4", "^0.2.3"))
        self.assertFalse(version_satisfies("0.3.0", "^0.2.3"))

    def test_tilde_constraint(self):
        self.assertTrue(version_satisfies("1.2.9", "~1.2.3"))
        self.assertFalse(version_satisfies("1.3.0", "~1.2.3"))

    def test_comparison_range(self):
        self.assertTrue(version_satisfies("3.8.5", ">=3.8.0,<4.0.0"))
        self.assertFalse(version_satisfies("4.0.0", ">=3.8.0,<4.0.0"))


if __name__ == "__main__":
    unittest.main()
