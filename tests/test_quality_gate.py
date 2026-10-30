import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ontology_software_factory.production_pipeline import run_pipeline
from ontology_software_factory.quality_gate import evaluate_quality

ROOT = Path(__file__).resolve().parents[1]


class QualityGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._baseline_tmp = tempfile.TemporaryDirectory(prefix='quality-gate-baseline-')
        cls.baseline_root = Path(cls._baseline_tmp.name)
        run_pipeline(ROOT / 'examples/requests/kafka-development.json', cls.baseline_root, run_id='gate-001')
        run_pipeline(ROOT / 'examples/requests/kafka-production.json', cls.baseline_root, run_id='gate-prod')

    @classmethod
    def tearDownClass(cls):
        cls._baseline_tmp.cleanup()

    def _copy_run(self, root: Path, rid='gate-001') -> Path:
        destination = root / rid
        shutil.copytree(self.baseline_root / rid, destination)
        return destination

    def test_development_config_gate_passes_without_claiming_external_scan(self):
        with tempfile.TemporaryDirectory() as d:
            run_dir = self._copy_run(Path(d))
            report = evaluate_quality(run_dir)
            self.assertEqual(report['status'], 'passed')
            self.assertTrue(report['releaseAllowed'])
            self.assertTrue(any(x['status'] == 'not_run' for x in report['checks']))

    def test_production_gate_fails_closed_when_required_scanners_not_installed(self):
        with tempfile.TemporaryDirectory() as d:
            run_dir = self._copy_run(Path(d), 'gate-prod')
            with patch('ontology_software_factory.quality_gate.shutil.which', return_value=None):
                report = evaluate_quality(run_dir)
            self.assertEqual(report['status'], 'incomplete')
            self.assertFalse(report['releaseAllowed'])
            self.assertTrue(any(x['checkId'] == 'external-trivy' and x['status'] == 'incomplete' for x in report['checks']))

    def test_installed_scanners_execute_and_attach_report_hashes(self):
        with tempfile.TemporaryDirectory() as d:
            run_dir = self._copy_run(Path(d), 'gate-prod')
            def fake_run(argv, **kwargs):
                if argv[0].endswith('mock-trivy'):
                    report_path = Path(argv[argv.index('--output') + 1])
                    report_path.write_text(json.dumps({'Results': []}), encoding='utf-8')
                elif argv[0].endswith('mock-gitleaks'):
                    report_path = Path(argv[argv.index('--report-path') + 1])
                    report_path.write_text('[]\n', encoding='utf-8')
                return subprocess.CompletedProcess(argv, 0, stdout='mock scanner ok\n')
            def which(name):
                return f'/usr/bin/mock-{name}' if name in ('trivy', 'gitleaks') else None
            with patch('ontology_software_factory.quality_gate.shutil.which', side_effect=which), \
                 patch('ontology_software_factory.quality_gate.subprocess.run', side_effect=fake_run) as run_mock:
                report = evaluate_quality(run_dir)
            self.assertEqual(report['status'], 'passed')
            self.assertEqual(run_mock.call_count, 2)
            self.assertTrue(all(x['status'] == 'passed' and x.get('reportSha256') for x in report['externalTools']))
            self.assertTrue(all(call.kwargs.get('shell') is False for call in run_mock.call_args_list))

    def test_high_severity_scanner_finding_blocks_release(self):
        with tempfile.TemporaryDirectory() as d:
            run_dir = self._copy_run(Path(d), 'gate-prod')
            def fake_run(argv, **kwargs):
                if argv[0].endswith('mock-trivy'):
                    report_path = Path(argv[argv.index('--output') + 1])
                    report_path.write_text(json.dumps({'Results': [{'Vulnerabilities': [{'Severity': 'CRITICAL'}]}]}), encoding='utf-8')
                    return subprocess.CompletedProcess(argv, 1, stdout='high severity finding\n')
                report_path = Path(argv[argv.index('--report-path') + 1])
                report_path.write_text('[]\n', encoding='utf-8')
                return subprocess.CompletedProcess(argv, 0, stdout='mock scanner ok\n')
            def which(name):
                return f'/usr/bin/mock-{name}' if name in ('trivy', 'gitleaks') else None
            with patch('ontology_software_factory.quality_gate.shutil.which', side_effect=which), \
                 patch('ontology_software_factory.quality_gate.subprocess.run', side_effect=fake_run):
                report = evaluate_quality(run_dir)
            self.assertEqual(report['status'], 'blocked')
            self.assertFalse(report['releaseAllowed'])
            self.assertTrue(any(x['checkId'] == 'external-trivy' and x['status'] == 'failed' for x in report['checks']))

    def test_secret_like_value_blocks_gate(self):
        with tempfile.TemporaryDirectory() as d:
            run_dir = self._copy_run(Path(d))
            cfg = run_dir / 'candidate/server.properties'
            cfg.write_text(cfg.read_text() + 'password="this-is-a-fake-secret-12345"\n', encoding='utf-8')
            report = evaluate_quality(run_dir)
            self.assertEqual(report['status'], 'blocked')

    def test_corrupt_package_hash_blocks_gate(self):
        with tempfile.TemporaryDirectory() as d:
            run_dir = self._copy_run(Path(d))
            package = run_dir / 'candidate-config-bundle.tar.gz'
            package.write_bytes(b'changed')
            report = evaluate_quality(run_dir)
            self.assertEqual(report['status'], 'blocked')


if __name__ == '__main__':
    unittest.main()
