from __future__ import annotations
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from ontology_software_factory.agent_contracts import validate_agent_catalog, read_json  # noqa: E402


class AgentContractTests(unittest.TestCase):
    def _mutated_fixture(self, mutate):
        temporary = tempfile.TemporaryDirectory()
        target = Path(temporary.name)
        for name in ["agents", "skills", "policies", "contracts", "examples"]:
            shutil.copytree(ROOT / name, target / name)
        shutil.copytree(ROOT / "src", target / "src", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        mutate(target)
        return temporary, validate_agent_catalog(target)

    def test_repository_agent_contracts_pass(self):
        self.assertEqual(validate_agent_catalog(ROOT), [])

    def test_no_role_can_grant_production_deploy(self):
        def mutate(root):
            path = root / "agents" / "roles" / "ops-support.json"
            role = read_json(path)
            role["toolIds"].append("production.deploy")
            path.write_text(json.dumps(role, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary, errors = self._mutated_fixture(mutate)
        try:
            self.assertTrue(any("globally denied tool production.deploy" in e for e in errors))
            self.assertTrue(any("is not enabled in MVP" in e for e in errors))
        finally:
            temporary.cleanup()

    def test_skill_tool_requirements_are_a_subset_of_role_tools(self):
        def mutate(root):
            path = root / "agents" / "roles" / "test-agent.json"
            role = read_json(path)
            role["toolIds"].remove("tests.run")
            path.write_text(json.dumps(role, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary, errors = self._mutated_fixture(mutate)
        try:
            self.assertTrue(any("Skill test-evidence-collection requires tools not granted" in e for e in errors))
        finally:
            temporary.cleanup()

    def test_role_cannot_allow_and_forbid_same_action(self):
        def mutate(root):
            path = root / "agents" / "roles" / "implementation-agent.json"
            role = read_json(path)
            role["allowedActions"].append("production.deploy")
            path.write_text(json.dumps(role, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary, errors = self._mutated_fixture(mutate)
        try:
            self.assertTrue(any("actions both allowed and forbidden" in e for e in errors))
            self.assertTrue(any("globally denied actions must not be allowed" in e for e in errors))
        finally:
            temporary.cleanup()

    def test_context_fields_cannot_overlap_restricted_and_shared(self):
        def mutate(root):
            path = root / "agents" / "roles" / "security-reviewer.json"
            role = read_json(path)
            role["contextPolicy"]["sharedContextFields"].append("raw_passwords")
            path.write_text(json.dumps(role, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary, errors = self._mutated_fixture(mutate)
        try:
            self.assertTrue(any("context fields both shared and restricted" in e for e in errors))
        finally:
            temporary.cleanup()

    def test_sample_handoff_requires_human_review_for_ambiguous_requirement(self):
        result = read_json(ROOT / "examples" / "agent-handoff" / "requirement-result.json")
        self.assertEqual(result["status"], "needs_human_review")
        self.assertTrue(result["humanReviewRequired"])
        self.assertTrue(result["blockedReasons"])

    def test_task_and_result_must_match(self):
        def mutate(root):
            path = root / "examples" / "agent-handoff" / "requirement-result.json"
            result = read_json(path)
            result["taskId"] = "sf:task:some-other-task"
            path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary, errors = self._mutated_fixture(mutate)
        try:
            self.assertTrue(any("example result taskId does not match task" in e for e in errors))
        finally:
            temporary.cleanup()

    def test_unknown_tool_is_detected_by_validator(self):
        def mutate(root):
            role_file = root / "agents" / "roles" / "implementation-agent.json"
            role = read_json(role_file)
            role["toolIds"].append("tools.not.real")
            role_file.write_text(json.dumps(role, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary, errors = self._mutated_fixture(mutate)
        try:
            self.assertTrue(any("unknown toolId tools.not.real" in error for error in errors))
        finally:
            temporary.cleanup()


if __name__ == "__main__":
    unittest.main()
