import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, Mock

from ontology_software_factory.workspace_execution import (
    WorkspaceExecution, WorkspaceManager, WorkspacePolicyError,
)


class WorkspaceExecutionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.project = self.base / "checkout"
        self.project.mkdir()
        (self.project / "src").mkdir()
        (self.project / "src" / "module.py").write_text("value = 1\n", encoding="utf-8")
        (self.project / "docs").mkdir()
        (self.project / "docs" / "architecture.md").write_text("design\n", encoding="utf-8")
        self.manager = WorkspaceManager(self.project, workspace_root=self.base / "external-workspaces")
        self.workspace = self.manager.open("run-001")
        self.service = WorkspaceExecution(self.project, self.workspace, run_id="run-001")

    def test_manager_copies_repository_outside_checkout(self):
        self.assertTrue((self.workspace / "src" / "module.py").is_file())
        self.assertNotEqual(self.workspace, self.project)
        self.assertNotIn(self.project, self.workspace.parents)

    def test_workspace_read_and_candidate_write(self):
        self.assertEqual(self.service.read("src/module.py")["content"], "value = 1\n")
        result = self.service.write_candidate("src/new_module.py", "value = 2\n")
        self.assertTrue(result["workspaceOnly"])
        self.assertFalse(result["appliedToSourceRepository"])
        self.assertFalse((self.project / "src" / "new_module.py").exists())

    def test_traversal_hidden_and_protected_paths_rejected(self):
        for path in ("../secret", ".env", "policies/tool-permissions.json", "agents/roles/a.json"):
            with self.subTest(path=path), self.assertRaises(WorkspacePolicyError):
                self.service.read(path) if path == ".env" else self.service.write_candidate(path, "x")

    def test_symlink_read_rejected(self):
        outside = self.base / "outside.txt"
        outside.write_text("secret", encoding="utf-8")
        (self.workspace / "src" / "link.txt").symlink_to(outside)
        with self.assertRaises(WorkspacePolicyError):
            self.service.read("src/link.txt")

    def test_test_execution_blocked_without_explicit_opt_in(self):
        with patch.dict(os.environ, {}, clear=True):
            result = self.service.run_tests("python-unit-tests")
        self.assertEqual(result["status"], "blocked")
        self.assertFalse(result["executed"])

    def test_fixed_test_command_runs_and_records_hash_when_opted_in(self):
        fake = Mock(returncode=0, stdout="Ran 1 test\nOK\n")
        with patch.dict(os.environ, {"FACTORY_ENABLE_UNSANDBOXED_TEST_EXECUTION": "1"}):
            with patch("ontology_software_factory.workspace_execution.subprocess.run", return_value=fake) as run:
                result = self.service.run_tests("python-unit-tests")
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["exitCode"], 0)
        self.assertTrue(result["evidence"]["reportSha256"])
        self.assertEqual(run.call_args.kwargs["shell"], False)
        self.assertNotIn("OPENAI_API_KEY", run.call_args.kwargs["env"])

    def test_container_runner_uses_networkless_readonly_privilege_dropped_docker(self):
        inspect = Mock(returncode=0, stdout="[]")
        run_result = Mock(returncode=0, stdout="Ran 1 test\\nOK\\n")
        with patch.dict(os.environ, {"FACTORY_ENABLE_CONTAINER_EXECUTION": "1"}, clear=True):
            with patch("ontology_software_factory.workspace_execution.shutil.which", return_value="/usr/bin/docker"):
                with patch("ontology_software_factory.workspace_execution.subprocess.run", side_effect=[inspect, run_result]) as run:
                    result = self.service.run_tests("python-unit-tests")
        self.assertEqual(result["status"], "passed")
        command = run.call_args_list[1].args[0]
        self.assertIn("--network=none", command)
        self.assertIn("--read-only", command)
        self.assertIn("--cap-drop=ALL", command)
        self.assertIn("--security-opt=no-new-privileges", command)
        self.assertIn("--pull=never", command)

    def test_missing_container_image_is_incomplete_and_never_falls_back_to_host(self):
        inspect = Mock(returncode=1, stdout="image missing")
        with patch.dict(os.environ, {"FACTORY_ENABLE_CONTAINER_EXECUTION": "1",
                                     "FACTORY_ENABLE_UNSANDBOXED_TEST_EXECUTION": "1"}):
            with patch("ontology_software_factory.workspace_execution.shutil.which", return_value="/usr/bin/docker"):
                with patch("ontology_software_factory.workspace_execution.subprocess.run", return_value=inspect) as run:
                    result = self.service.run_tests("python-unit-tests")
        self.assertEqual(result["status"], "incomplete")
        self.assertEqual(run.call_count, 1)
        self.assertEqual(result["sandbox"], "image_missing")

    def test_git_worktree_backend_creates_a_local_run_branch(self):
        import shutil
        import subprocess
        git = shutil.which("git")
        if not git:
            self.skipTest("Git CLI is unavailable")
        subprocess.run([git, "-C", str(self.project), "init"], check=True, stdout=subprocess.DEVNULL)
        subprocess.run([git, "-C", str(self.project), "config", "user.email", "test@example.invalid"], check=True)
        subprocess.run([git, "-C", str(self.project), "config", "user.name", "Test"], check=True)
        subprocess.run([git, "-C", str(self.project), "add", "."], check=True)
        subprocess.run([git, "-C", str(self.project), "commit", "-m", "baseline"], check=True, stdout=subprocess.DEVNULL)
        manager = WorkspaceManager(self.project, workspace_root=self.base / "git-worktrees")
        with patch.dict(os.environ, {"FACTORY_WORKSPACE_BACKEND": "git-worktree"}):
            worktree = manager.open("run-git-001")
            current = subprocess.run([git, "-C", str(worktree), "branch", "--show-current"],
                                      check=True, capture_output=True, text=True).stdout.strip()
            self.assertEqual(current, "agent/run-run-git-001")
            metadata = manager.describe("run-git-001")
            self.assertEqual(metadata["backend"], "git-worktree")
            self.assertFalse(metadata["pushEnabled"])
            self.assertFalse(metadata["mergeEnabled"])
        subprocess.run([git, "-C", str(self.project), "worktree", "remove", "--force", str(worktree)], check=True)
        subprocess.run([git, "-C", str(self.project), "branch", "-D", "agent/run-run-git-001"], check=True, stdout=subprocess.DEVNULL)

    def test_workspace_diff_is_reviewable_and_source_checkout_stays_unchanged(self):
        self.service.write_candidate("src/module.py", "value = 2\n")
        result = self.service.diff_patch()
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["fileCount"], 1)
        self.assertIn("-value = 1", result["patch"])
        self.assertIn("+value = 2", result["patch"])
        self.assertEqual((self.project / "src" / "module.py").read_text(encoding="utf-8"), "value = 1\n")

    def test_unknown_test_suite_rejected(self):
        with self.assertRaises(WorkspacePolicyError):
            self.service.run_tests("arbitrary-shell-command")


if __name__ == "__main__":
    unittest.main()
