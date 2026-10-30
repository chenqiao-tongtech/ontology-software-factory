import json
import shutil
import tempfile
import unittest
from pathlib import Path

from ontology_software_factory.production_pipeline import run_pipeline
from ontology_software_factory.quality_gate import evaluate_quality
from ontology_software_factory.release_manager import create_release, rehearse_upgrade, ReleaseError

ROOT = Path(__file__).resolve().parents[1]


class ReleaseManagerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._baseline_tmp = tempfile.TemporaryDirectory(prefix='release-baseline-')
        cls.baseline_root = Path(cls._baseline_tmp.name)
        for request, run_id in (('kafka-development.json', 'release-run'), ('kafka-production.json', 'release-prod')):
            run_pipeline(ROOT / 'examples/requests' / request, cls.baseline_root, run_id=run_id)
            evaluate_quality(cls.baseline_root / run_id)

    @classmethod
    def tearDownClass(cls):
        cls._baseline_tmp.cleanup()

    def _copy_run(self, d, source_id='release-run', dest_id='release-run'):
        runs = Path(d) / 'runs'
        runs.mkdir(parents=True, exist_ok=True)
        shutil.copytree(self.baseline_root / source_id, runs / dest_id)
        return runs / dest_id

    def _release(self, d):
        run_dir = self._copy_run(d)
        return create_release(run_dir, Path(d) / 'deliverables', release_id='release-001')

    def test_release_includes_manifest_sums_and_cyclonedx(self):
        with tempfile.TemporaryDirectory() as d:
            rec = self._release(d)
            self.assertTrue(Path(rec['bundlePath']).is_file())
            self.assertTrue(Path(rec['manifestPath']).is_file())
            sbom = json.loads((Path(d) / 'deliverables/release-001/sbom.cdx.json').read_text())
            self.assertEqual(sbom['bomFormat'], 'CycloneDX')
            self.assertEqual(sbom['metadata']['component']['name'], 'kafka-configuration-delivery-bundle')

    def test_release_fails_closed_when_quality_gate_not_passed(self):
        with tempfile.TemporaryDirectory() as d:
            run_dir = self._copy_run(d, 'release-prod', 'release-run')
            with self.assertRaises(ReleaseError):
                create_release(run_dir, Path(d) / 'deliverables')

    def test_upgrade_rehearsal_requires_approval_and_only_simulation_target(self):
        with tempfile.TemporaryDirectory() as d:
            self._release(d)
            rp = Path(d) / 'deliverables/release-001.release-record.json'
            with self.assertRaises(ReleaseError):
                rehearse_upgrade(Path(d) / 'state.json', rp, approved_by='', approval_reason='test')
            with self.assertRaises(ReleaseError):
                rehearse_upgrade(Path(d) / 'state.json', rp, approved_by='alice', approval_reason='test', target_environment='production')

    def test_failed_health_check_rolls_back_state(self):
        with tempfile.TemporaryDirectory() as d:
            self._release(d)
            rp = Path(d) / 'deliverables/release-001.release-record.json'
            state = Path(d) / 'state.json'
            state.write_text(json.dumps({'currentReleaseId': 'old', 'revision': 7, 'health': 'passed'}))
            result = rehearse_upgrade(state, rp, approved_by='reviewer', approval_reason='test rehearsal', simulate_health_failure=True)
            self.assertEqual(result['outcome'], 'rolled_back')
            self.assertEqual(json.loads(state.read_text())['currentReleaseId'], 'old')
            self.assertEqual(json.loads(state.read_text())['revision'], 7)

    def test_successful_upgrade_rehearsal_updates_simulated_state(self):
        with tempfile.TemporaryDirectory() as d:
            self._release(d)
            rp = Path(d) / 'deliverables/release-001.release-record.json'
            state = Path(d) / 'state.json'
            result = rehearse_upgrade(state, rp, approved_by='reviewer', approval_reason='staging rehearsal')
            self.assertEqual(result['outcome'], 'upgrade_rehearsal_passed')
            self.assertEqual(json.loads(state.read_text())['currentReleaseId'], 'release-001')


if __name__ == '__main__':
    unittest.main()
