from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "run_factory_portal.py"
SPEC = importlib.util.spec_from_file_location("quality_portal_module", SCRIPT)
portal = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(portal)


class ScannerReportStatusTests(unittest.TestCase):
    def test_semgrep_report_distinguishes_clean_findings_and_errors(self):
        self.assertEqual(portal.scanner_report_status("semgrep", {"results": [], "errors": []}), ("clean", 0))
        self.assertEqual(portal.scanner_report_status("semgrep", {"results": [{"check_id": "x"}], "errors": []}), ("findings", 1))
        self.assertEqual(portal.scanner_report_status("semgrep", {"results": [], "errors": [{"message": "failed"}]}), ("incomplete", 0))

    def test_gitleaks_report_counts_findings(self):
        self.assertEqual(portal.scanner_report_status("gitleaks", []), ("clean", 0))
        self.assertEqual(portal.scanner_report_status("gitleaks", [{"RuleID": "generic-api-key"}]), ("findings", 1))
        self.assertEqual(portal.scanner_report_status("gitleaks", {"leaks": []}), ("incomplete", 0))

    def test_trivy_report_counts_vulnerabilities_misconfigurations_and_secrets(self):
        report = {"Results": [{
            "Vulnerabilities": [{"VulnerabilityID": "CVE-1"}],
            "Misconfigurations": [{"ID": "CFG-1"}],
            "Secrets": [{"RuleID": "secret-1"}],
        }]}
        self.assertEqual(portal.scanner_report_status("trivy", report), ("findings", 3))
        self.assertEqual(portal.scanner_report_status("trivy", {"Results": []}), ("clean", 0))
        self.assertEqual(portal.scanner_report_status("trivy", {}), ("incomplete", 0))

    def test_trivy_findings_fail_quality_run_even_when_exit_code_is_zero(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            with patch.object(portal, "STATE_DIR", base / ".state"), \
                 patch.object(portal, "STATE_PATH", base / ".state" / "state.json"), \
                 patch.object(portal, "SOURCES_PATH", base / "sources.json"), \
                 patch.object(portal.shutil, "which", return_value="/usr/bin/trivy"):
                def fake_run(command, **kwargs):
                    report_path = Path(command[command.index("--output") + 1])
                    report_path.parent.mkdir(parents=True, exist_ok=True)
                    report_path.write_text(json.dumps({"Results": [{
                        "Vulnerabilities": [{"VulnerabilityID": "CVE-TEST"}]
                    }]}), encoding="utf-8")
                    return SimpleNamespace(returncode=0, stdout="", stderr="")
                with patch.object(portal.subprocess, "run", side_effect=fake_run):
                    report = portal.run_quality(["scanner:trivy"])
        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["results"][0]["status"], "findings")
        self.assertEqual(report["results"][0]["findingCount"], 1)


if __name__ == "__main__":
    unittest.main()
