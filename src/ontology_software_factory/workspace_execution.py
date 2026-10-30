"""Run-scoped candidate workspaces and evidence-producing local tool adapters.

This module deliberately does not claim to provide an OS/container sandbox. Executing
candidate code on the host is disabled unless the operator explicitly opts in.
"""
from __future__ import annotations

import difflib
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any


class WorkspacePolicyError(PermissionError):
    pass


class WorkspaceExecutionError(RuntimeError):
    pass


RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,100}$")
READ_ROOTS = {"src", "tests", "docs", "agents", "skills", "workflows", "contracts",
              "ontology", "catalog", "config", "examples", "scripts", "tools", "policies"}
WRITE_ROOTS = {"src", "tests", "docs", "examples"}
PROTECTED_PREFIXES = (".git", ".github", "policies", "agents/roles", "agents/teams",
                       "skills", "workflows", "contracts", "ontology", "tools")
IGNORE_NAMES = {".git", ".venv", "venv", "__pycache__", ".pytest_cache", ".ruff_cache",
                "node_modules", "data", "deliverables", ".local-runs", ".local-portal",
                ".local-environments", ".idea", ".vscode"}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


class WorkspaceManager:
    """Create one persistent copy of the repository per workflow run, outside its checkout."""

    def __init__(self, project_root: str | Path, *, workspace_root: str | Path | None = None):
        self.project_root = Path(project_root).resolve()
        default_root = Path(tempfile.gettempdir()) / "ontology-software-factory-workspaces"
        self.workspace_root = Path(workspace_root or default_root).resolve()
        if self.workspace_root == self.project_root or self.project_root in self.workspace_root.parents:
            raise WorkspacePolicyError("workspace root must be outside the source checkout")
        self.workspace_root.mkdir(parents=True, exist_ok=True)

    def open(self, run_id: str) -> Path:
        if not RUN_ID_RE.fullmatch(run_id):
            raise WorkspacePolicyError("invalid workflow run ID")
        raw_target = self.workspace_root / run_id
        if raw_target.is_symlink():
            raise WorkspacePolicyError("workspace root cannot be a symlink")
        target = raw_target.resolve()
        if self.workspace_root not in target.parents:
            raise WorkspacePolicyError("workspace path escaped workspace root")
        backend = os.getenv("FACTORY_WORKSPACE_BACKEND", "copy").strip().lower()
        if backend not in {"copy", "git-worktree"}:
            raise WorkspacePolicyError("workspace backend must be copy or git-worktree")
        if backend == "git-worktree":
            git = shutil.which("git")
            if not git:
                raise WorkspacePolicyError("git-worktree backend requires the Git CLI")
            root_result = subprocess.run(
                [git, "-C", str(self.project_root), "rev-parse", "--show-toplevel"],
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, timeout=15, shell=False, check=False,
            )
            if root_result.returncode != 0 or Path(root_result.stdout.strip()).resolve() != self.project_root:
                raise WorkspacePolicyError("git-worktree backend requires project_root to be the Git repository root")
            branch_name = f"agent/run-{run_id.lower()}"
            if not target.exists():
                proc = subprocess.run(
                    [git, "-C", str(self.project_root), "worktree", "add", "-b", branch_name, str(target), "HEAD"],
                    stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, timeout=60, shell=False, check=False,
                )
                if proc.returncode != 0:
                    raise WorkspacePolicyError("cannot create isolated Git worktree: " + proc.stdout[-2000:])
            current = subprocess.run(
                [git, "-C", str(target), "branch", "--show-current"],
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, timeout=15, shell=False, check=False,
            )
            if current.returncode != 0 or current.stdout.strip() != branch_name:
                raise WorkspacePolicyError("existing run workspace does not match its expected local branch")
        elif not target.exists():
            shutil.copytree(
                self.project_root, target,
                ignore=shutil.ignore_patterns(*IGNORE_NAMES, "*.pyc", "*.sqlite3", "*.log"),
                symlinks=True,
            )
        if target.is_symlink() or not target.is_dir():
            raise WorkspacePolicyError("workspace root is not a regular directory")
        return target

    def describe(self, run_id: str) -> dict[str, Any]:
        backend = os.getenv("FACTORY_WORKSPACE_BACKEND", "copy").strip().lower()
        if backend == "git-worktree":
            return {"backend": "git-worktree", "branch": f"agent/run-{run_id.lower()}",
                    "pushEnabled": False, "mergeEnabled": False}
        return {"backend": "repository-copy", "branch": None,
                "pushEnabled": False, "mergeEnabled": False}


class WorkspaceExecution:
    """Bounded file tools and fixed test/security commands for one isolated workspace."""

    def __init__(self, project_root: str | Path, workspace_path: str | Path, *,
                 run_id: str, max_file_bytes: int = 128_000,
                 max_write_bytes: int = 1_000_000, max_output_chars: int = 100_000):
        self.project_root = Path(project_root).resolve()
        raw_workspace = Path(workspace_path)
        if raw_workspace.is_symlink():
            raise WorkspacePolicyError("workspace root cannot be a symlink")
        self.root = raw_workspace.resolve()
        self.run_id = run_id
        if not RUN_ID_RE.fullmatch(run_id):
            raise WorkspacePolicyError("invalid workflow run ID")
        if self.root == self.project_root or self.project_root in self.root.parents:
            raise WorkspacePolicyError("workspace must be outside the source checkout")
        if not self.root.is_dir() or self.root.is_symlink():
            raise WorkspacePolicyError("workspace must be an existing regular directory")
        self.max_file_bytes = max_file_bytes
        self.max_write_bytes = max_write_bytes
        self.max_output_chars = max_output_chars
        self.operations: list[dict[str, Any]] = []
        self.tool_evidence: list[dict[str, Any]] = []
        self.evidence_root = self.root / ".agent-evidence"
        self.evidence_root.mkdir(exist_ok=True)

    def _relative(self, value: str) -> tuple[PurePosixPath, Path]:
        if not isinstance(value, str) or not value or len(value) > 500 or "\\" in value:
            raise WorkspacePolicyError("path must be a non-empty safe relative path")
        relative = PurePosixPath(value)
        if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
            raise WorkspacePolicyError("absolute paths and traversal segments are forbidden")
        if any(part.startswith(".") for part in relative.parts):
            raise WorkspacePolicyError("hidden paths are not accessible")
        target = self.root.joinpath(*relative.parts)
        current = self.root
        for part in relative.parts:
            current = current / part
            if current.is_symlink():
                raise WorkspacePolicyError("symlink paths are not accessible")
        resolved = target.resolve()
        if resolved != self.root and self.root not in resolved.parents:
            raise WorkspacePolicyError("path escaped workspace root")
        return relative, resolved

    def read(self, relative_path: str) -> dict[str, Any]:
        relative, target = self._relative(relative_path)
        if relative.parts[0] not in READ_ROOTS:
            raise WorkspacePolicyError("path is outside the workspace read allowlist")
        if not target.is_file():
            raise WorkspacePolicyError("workspace file does not exist")
        if target.stat().st_size > self.max_file_bytes:
            raise WorkspacePolicyError("workspace file exceeds the read size limit")
        content = target.read_text(encoding="utf-8", errors="replace")
        operation = {"operation": "workspace_read", "relativePath": relative.as_posix(),
                     "sha256": sha256_file(target), "bytes": target.stat().st_size}
        self.operations.append(operation)
        return {"relativePath": relative.as_posix(), "content": content,
                "sha256": sha256_file(target), "bytes": target.stat().st_size}

    def write_candidate(self, relative_path: str, content: str, *, purpose: str = "candidate change") -> dict[str, Any]:
        relative, target = self._relative(relative_path)
        rel = relative.as_posix()
        if relative.parts[0] not in WRITE_ROOTS:
            raise WorkspacePolicyError("candidate writes are limited to src/, tests/, docs/ and examples/")
        if any(rel == prefix or rel.startswith(prefix + "/") for prefix in PROTECTED_PREFIXES):
            raise WorkspacePolicyError("protected policy, role, Skill, workflow and ontology files cannot be changed by an Agent")
        if len(content.encode("utf-8")) > self.max_write_bytes:
            raise WorkspacePolicyError("candidate content exceeds the write size limit")
        if target.exists() and not target.is_file():
            raise WorkspacePolicyError("candidate target must be a regular file")
        target.parent.mkdir(parents=True, exist_ok=True)
        # Re-check parents after mkdir to reject symlink substitution.
        _, target = self._relative(rel)
        temp = target.with_name(target.name + ".agent-tmp")
        temp.write_text(content, encoding="utf-8")
        temp.replace(target)
        operation = {"operation": "candidate_write", "relativePath": rel,
                     "sha256": sha256_file(target), "bytes": target.stat().st_size,
                     "purpose": purpose, "at": datetime.now(timezone.utc).isoformat()}
        self.operations.append(operation)
        return {**operation, "workspaceOnly": True, "appliedToSourceRepository": False}

    def diff_patch(self) -> dict[str, Any]:
        """Build a bounded unified diff against the source checkout for review/export."""
        files: list[dict[str, Any]] = []
        patches: list[str] = []
        total = 0
        for root_name in sorted(WRITE_ROOTS):
            root = self.root / root_name
            if not root.is_dir():
                continue
            for folder, dirnames, filenames in os.walk(root, followlinks=False):
                dirnames[:] = [name for name in dirnames if not name.startswith(".")]
                for filename in sorted(filenames):
                    candidate = Path(folder) / filename
                    if candidate.is_symlink() or filename.startswith("."):
                        continue
                    relative = candidate.relative_to(self.root).as_posix()
                    original = self.project_root / relative
                    try:
                        new_text = candidate.read_text(encoding="utf-8")
                        old_text = original.read_text(encoding="utf-8") if original.is_file() else ""
                    except (OSError, UnicodeDecodeError):
                        continue
                    if new_text == old_text:
                        continue
                    action = "modified" if original.is_file() else "added"
                    digest = sha256_file(candidate)
                    files.append({"relativePath": relative, "action": action,
                                  "sha256": digest, "bytes": candidate.stat().st_size})
                    patch = "".join(difflib.unified_diff(
                        old_text.splitlines(keepends=True), new_text.splitlines(keepends=True),
                        fromfile=f"a/{relative}" if action == "modified" else "/dev/null",
                        tofile=f"b/{relative}", lineterm="\n",
                    ))
                    patches.append(patch)
                    total += len(patch.encode("utf-8"))
                    if total > 1_000_000:
                        return {"status": "incomplete", "reason": "patch exceeds 1 MB review limit",
                                "files": files[:200], "fileCount": len(files), "patch": None}
        patch_text = "".join(patches)
        digest = hashlib.sha256(patch_text.encode("utf-8")).hexdigest()
        return {"status": "ready", "files": files[:200], "fileCount": len(files),
                "patch": patch_text, "patchSha256": digest, "patchBytes": len(patch_text.encode("utf-8"))}

    def architecture_plan_write(self, relative_path: str, content: str) -> dict[str, Any]:
        relative = PurePosixPath(relative_path)
        if not (relative.as_posix().startswith("docs/agent-proposals/") or
                relative.as_posix().startswith("docs/adr-drafts/")):
            raise WorkspacePolicyError("architecture plans must be written under docs/agent-proposals/ or docs/adr-drafts/")
        return self.write_candidate(relative_path, content, purpose="architecture proposal; not an approved ADR")

    def _write_evidence(self, category: str, name: str, value: dict[str, Any], log: str = "") -> dict[str, Any]:
        if not re.fullmatch(r"[a-z0-9-]{1,50}", category) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", name):
            raise WorkspacePolicyError("invalid evidence identifier")
        folder = self.evidence_root / category
        folder.mkdir(parents=True, exist_ok=True)
        report_path = folder / f"{name}.json"
        report_path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        result = {"reportPath": report_path.relative_to(self.root).as_posix(),
                  "reportSha256": sha256_file(report_path)}
        if log:
            log_path = folder / f"{name}.log"
            log_path.write_text(log[:self.max_output_chars], encoding="utf-8")
            result.update({"logPath": log_path.relative_to(self.root).as_posix(),
                           "logSha256": sha256_file(log_path)})
        return result

    def _run_container_command(
        self, argv: list[str], *, timeout_seconds: int, image: str = "ontology-software-factory-test-runner:py311-v1"
    ) -> tuple[int, str, bool, str]:
        docker = shutil.which("docker")
        if not docker:
            return 127, "Docker CLI is not installed", False, "unavailable"
        inspect = subprocess.run(
            [docker, "image", "inspect", image], stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            timeout=15, shell=False, check=False,
        )
        if inspect.returncode != 0:
            return 127, "Required container image is not present locally; image pulls are disabled", False, "image_missing"
        uid = str(os.getuid()) if hasattr(os, "getuid") else "10001"
        gid = str(os.getgid()) if hasattr(os, "getgid") else "10001"
        command = [
            docker, "run", "--rm", "--pull=never", "--network=none", "--read-only",
            "--cap-drop=ALL", "--security-opt=no-new-privileges", "--pids-limit=128",
            "--memory=1g", "--cpus=1", "--user", f"{uid}:{gid}",
            "--tmpfs", "/tmp:rw,noexec,nosuid,size=256m",
            "--env", "PYTHONPATH=/workspace/src", "--env", "PYTHONIOENCODING=utf-8",
            "--env", "PYTHONUTF8=1", "--env", "HOME=/tmp",
            "--volume", f"{self.root}:/workspace:rw", "--workdir", "/workspace",
            image, *argv,
        ]
        try:
            proc = subprocess.run(
                command, cwd=self.root, env={"PATH": os.environ.get("PATH", ""), "LANG": "C.UTF-8"},
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace",
                timeout=timeout_seconds, shell=False, check=False,
            )
            return proc.returncode, proc.stdout, False, "docker"
        except subprocess.TimeoutExpired as exc:
            output = exc.stdout.decode("utf-8", "replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
            return 124, output + "\\nRUNNER_TIMEOUT: container suite exceeded the configured timeout", True, "docker"

    def run_tests(self, suite_id: str, *, timeout_seconds: int = 120) -> dict[str, Any]:
        suites = {
            "kafka-profile-regression": [sys.executable, "-m", "unittest", "tests.test_kafka_profile", "-v"],
            "python-unit-tests": [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
        }
        if suite_id not in suites:
            raise WorkspacePolicyError("test suite is not in the fixed command allowlist")
        if not 1 <= timeout_seconds <= 120:
            raise WorkspacePolicyError("test timeout must be between 1 and 120 seconds")
        container_enabled = os.getenv("FACTORY_ENABLE_CONTAINER_EXECUTION", "").lower() in {"1", "true", "yes"}
        host_enabled = os.getenv("FACTORY_ENABLE_UNSANDBOXED_TEST_EXECUTION", "").lower() in {"1", "true", "yes"}
        if not container_enabled and not host_enabled:
            return {"status": "blocked", "suiteId": suite_id, "executed": False,
                    "reason": "execution disabled; enable Docker execution with FACTORY_ENABLE_CONTAINER_EXECUTION=1",
                    "evidence": None}
        argv = suites[suite_id]
        started = time.monotonic()
        if container_enabled:
            container_argv = ["python", *argv[1:]]
            exit_code, output, timed_out, sandbox = self._run_container_command(
                container_argv, timeout_seconds=timeout_seconds
            )
        else:
            env = {"PATH": os.environ.get("PATH", ""), "PYTHONPATH": str(self.root / "src"),
                   "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1",
                   "HOME": str(self.root / ".agent-home"), "LANG": "C.UTF-8"}
            Path(env["HOME"]).mkdir(exist_ok=True)
            try:
                proc = subprocess.run(argv, cwd=self.root, env=env, stdin=subprocess.DEVNULL,
                                      stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                      text=True, encoding="utf-8", errors="replace",
                                      timeout=timeout_seconds, shell=False, check=False)
                exit_code, output, timed_out, sandbox = proc.returncode, proc.stdout, False, "host-unsafe-demo"
            except subprocess.TimeoutExpired as exc:
                timed_out, exit_code, sandbox = True, 124, "host-unsafe-demo"
                output = exc.stdout.decode("utf-8", "replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
                output += "\\nRUNNER_TIMEOUT: test suite exceeded the configured timeout"
        duration = round((time.monotonic() - started) * 1000)
        output = output[:self.max_output_chars]
        status = "timed_out" if timed_out else ("passed" if exit_code == 0 else "failed")
        report = {"schemaVersion": "1.0.0", "runId": self.run_id, "suiteId": suite_id,
                  "status": status, "exitCode": exit_code, "durationMs": duration,
                  "commandId": suite_id, "argv": argv, "executedAt": datetime.now(timezone.utc).isoformat(),
                  "workspaceOnly": True, "sandbox": sandbox}
        evidence = self._write_evidence("tests", suite_id, report, output)
        result = {**report, "evidence": evidence}
        self.tool_evidence.append(result)
        self.operations.append({"operation": "tests.run", "suiteId": suite_id,
                                "status": status, "reportSha256": evidence["reportSha256"]})
        return result

    def run_security_scan(self, scanner_id: str, *, timeout_seconds: int = 90) -> dict[str, Any]:
        if scanner_id not in {"semgrep", "gitleaks", "trivy"}:
            raise WorkspacePolicyError("scanner is not in the fixed scanner allowlist")
        if os.getenv("FACTORY_ENABLE_LOCAL_SECURITY_SCANS", "").lower() not in {"1", "true", "yes"}:
            return {"status": "blocked", "scannerId": scanner_id, "executed": False,
                    "reason": "local scanner execution is disabled; set FACTORY_ENABLE_LOCAL_SECURITY_SCANS=1 after reviewing scanner and workspace trust boundaries",
                    "evidence": None}
        executable = shutil.which(scanner_id)
        if not executable:
            return {"status": "incomplete", "scannerId": scanner_id, "executed": False,
                    "reason": f"{scanner_id} executable is not installed", "evidence": None}
        report_dir = self.evidence_root / "security"
        report_dir.mkdir(parents=True, exist_ok=True)
        report_path = report_dir / f"{scanner_id}-report.json"
        if scanner_id == "semgrep":
            argv = [executable, "scan", "--json", "--output", str(report_path), "--config", "auto", str(self.root)]
        elif scanner_id == "gitleaks":
            argv = [executable, "dir", "--report-format", "json", "--report-path", str(report_path),
                    "--redact", "100", "--no-banner", str(self.root)]
        else:
            argv = [executable, "fs", "--format", "json", "--output", str(report_path),
                    "--scanners", "vuln,misconfig,secret", "--severity", "HIGH,CRITICAL",
                    "--skip-db-update", "--skip-java-db-update", str(self.root)]
        env = {"PATH": os.environ.get("PATH", ""), "HOME": str(self.root / ".scanner-home"),
               "TMPDIR": str(self.root / ".scanner-tmp"), "LANG": "C.UTF-8"}
        Path(env["HOME"]).mkdir(exist_ok=True)
        Path(env["TMPDIR"]).mkdir(exist_ok=True)
        started = time.monotonic()
        timed_out = False
        try:
            proc = subprocess.run(argv, cwd=self.root, env=env, stdin=subprocess.DEVNULL,
                                  stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                  text=True, encoding="utf-8", errors="replace",
                                  timeout=timeout_seconds, shell=False, check=False)
            exit_code, output = proc.returncode, proc.stdout
        except subprocess.TimeoutExpired as exc:
            timed_out, exit_code = True, 124
            output = exc.stdout.decode("utf-8", "replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
            output += "\nSCANNER_TIMEOUT"
        output = output[:self.max_output_chars]
        parsed = None
        if report_path.is_file():
            try:
                parsed = json.loads(report_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                parsed = None
        if timed_out or parsed is None:
            status = "incomplete"
        elif exit_code == 0:
            status = "passed"
        elif exit_code == 1:
            status = "findings"
        else:
            status = "incomplete"
        report = {"schemaVersion": "1.0.0", "runId": self.run_id, "scannerId": scanner_id,
                  "status": status, "exitCode": exit_code, "durationMs": round((time.monotonic()-started)*1000),
                  "executedAt": datetime.now(timezone.utc).isoformat(), "workspaceOnly": True,
                  "reportSha256": sha256_file(report_path) if report_path.is_file() else None,
                  "reportPath": report_path.relative_to(self.root).as_posix() if report_path.is_file() else None,
                  "sandbox": "host-process; not an OS/container sandbox"}
        evidence = self._write_evidence("security", scanner_id, report, output)
        return {**report, "evidence": evidence, "findings": parsed if status == "findings" else None}
