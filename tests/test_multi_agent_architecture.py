import copy
import json
import unittest
from pathlib import Path
from ontology_software_factory.multi_agent_architecture import validate_team, validate_handoff_example, validate_handoff_instance
ROOT = Path(__file__).resolve().parents[1]

class MultiAgentArchitectureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.team = json.loads((ROOT / "agents/teams/software-factory-mvp.json").read_text(encoding="utf-8"))

    def test_repository_topology_passes(self):
        self.assertEqual(validate_team(ROOT), [])
        self.assertEqual(validate_handoff_example(ROOT), [])

    def test_unknown_role_is_rejected(self):
        team = copy.deepcopy(self.team)
        team["registeredRoles"][0]["roleId"] = "not-registered"
        self.assertTrue(any("unknown role" in e for e in validate_team(ROOT, team)))

    def test_team_schema_rejects_llm_controller(self):
        from jsonschema import Draft202012Validator
        schema = json.loads((ROOT / "contracts/schemas/agent-team.schema.json").read_text(encoding="utf-8"))
        team = copy.deepcopy(self.team)
        team["controller"]["llmPowered"] = True
        self.assertTrue(any("False" in e.message or "const" in e.message for e in Draft202012Validator(schema).iter_errors(team)))

    def test_llm_cannot_be_deterministic_controller(self):
        team = copy.deepcopy(self.team)
        team["controller"]["llmPowered"] = True
        self.assertTrue(any("not LLM-powered" in e for e in validate_team(ROOT, team)))

    def test_agents_cannot_grant_permissions(self):
        team = copy.deepcopy(self.team)
        team["handoffRules"]["toolsGrantedBy"] = "agent"
        self.assertTrue(any("policy runtime only" in e for e in validate_team(ROOT, team)))

    def test_agent_cannot_approve_own_high_risk_result(self):
        team = copy.deepcopy(self.team)
        team["registeredRoles"][2]["mayApproveHighRisk"] = True
        self.assertTrue(any("cannot approve" in e for e in validate_team(ROOT, team)))

    def test_verification_requires_test_and_security_parallel(self):
        team = copy.deepcopy(self.team)
        next(s for s in team["stages"] if s["stageId"] == "candidate-verification")["roleIds"] = ["test-agent"]
        self.assertTrue(any("independent parallel branches" in e for e in validate_team(ROOT, team)))

    def test_revision_loop_is_bounded(self):
        team = copy.deepcopy(self.team)
        next(f for f in team["failurePaths"] if f["action"] == "bounded_revision_loop")["maxIterations"] = 99
        self.assertTrue(any("explicitly bounded" in e for e in validate_team(ROOT, team)))

    def test_agent_cannot_mutate_workflow(self):
        team = copy.deepcopy(self.team)
        team["handoffRules"]["agentsMayMutateWorkflowState"] = True
        self.assertTrue(any("directly mutate workflow" in e for e in validate_team(ROOT, team)))

    def test_handoff_contract_schema_rejects_missing_budget(self):
        from jsonschema import Draft202012Validator
        schema = json.loads((ROOT / "contracts/schemas/agent-handoff.schema.json").read_text(encoding="utf-8"))
        instance = json.loads((ROOT / "examples/multi-agent-handoffs/requirement-to-architecture.json").read_text(encoding="utf-8"))
        del instance["budget"]
        self.assertTrue(any("budget" in e.message for e in Draft202012Validator(schema).iter_errors(instance)))

    def test_handoff_sender_and_recipient_must_differ_by_policy(self):
        instance = json.loads((ROOT / "examples/multi-agent-handoffs/requirement-to-architecture.json").read_text(encoding="utf-8"))
        instance["toRoleId"] = instance["fromRoleId"]
        self.assertTrue(any("sender and recipient must differ" in e for e in validate_handoff_instance(ROOT, instance)))

    def test_handoff_tools_must_be_within_recipient_role(self):
        instance = json.loads((ROOT / "examples/multi-agent-handoffs/requirement-to-architecture.json").read_text(encoding="utf-8"))
        instance["allowedToolIds"].append("production.deploy")
        self.assertTrue(any("exceed recipient role declaration" in e for e in validate_handoff_instance(ROOT, instance)))

if __name__ == "__main__":
    unittest.main()
