import unittest

from ontology_software_factory.source_sync import compare_asset_manifests


class SourceManifestTests(unittest.TestCase):
    def test_first_scan_is_baseline_not_deletion(self):
        result = compare_asset_manifests(
            None, [{"assetId": "a", "sha256": "abc"}],
            previous_complete=False, current_complete=True,
        )
        self.assertTrue(result["baseline"])
        self.assertEqual(result["added"], 1)
        self.assertIsNone(result["removed"])
        self.assertFalse(result["removedKnown"])

    def test_complete_manifests_report_added_changed_removed(self):
        previous = [
            {"assetId": "a", "sha256": "old"},
            {"assetId": "b", "sha256": "same"},
        ]
        current = [
            {"assetId": "a", "sha256": "new"},
            {"assetId": "c", "sha256": "added"},
        ]
        result = compare_asset_manifests(
            previous, current, previous_complete=True, current_complete=True,
        )
        self.assertEqual(result["added"], 1)
        self.assertEqual(result["changed"], 1)
        self.assertEqual(result["removed"], 1)
        self.assertTrue(result["removedKnown"])

    def test_truncated_manifest_never_claims_removed_assets(self):
        result = compare_asset_manifests(
            [{"assetId": "a", "sha256": "1"}, {"assetId": "b", "sha256": "2"}],
            [{"assetId": "a", "sha256": "1"}],
            previous_complete=True, current_complete=False,
        )
        self.assertIsNone(result["removed"])
        self.assertFalse(result["removedKnown"])

    def test_schema_fingerprint_detects_column_change(self):
        previous = [{"assetId": "table-a", "assetFingerprint": "schema-v1"}]
        current = [{"assetId": "table-a", "assetFingerprint": "schema-v2"}]
        result = compare_asset_manifests(
            previous, current, previous_complete=True, current_complete=True,
        )
        self.assertEqual(result["changed"], 1)


if __name__ == "__main__":
    unittest.main()
