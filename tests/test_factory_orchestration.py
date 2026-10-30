from __future__ import annotations
import copy
import json
import unittest
from pathlib import Path

from ontology_software_factory.factory_orchestration import FactoryPlanError, validate_factory_plan

ROOT = Path(__file__).resolve().parents[1]


def sample_plan():
    return json.loads((ROOT / "contracts/examples/factory-orchestrator-plan.example.json").read_text(encoding="utf-8"))


class FactoryOrchestrationTests(unittest.TestCase):
    def test_example_plan_passes_registered_role_skill_and_topology_checks(self):
        result = validate_factory_plan(ROOT, sample_plan())
        self.assertTrue(result["valid"])
        self.assertEqual(result["phaseCount"], 2)
        self.assertEqual(result["assignmentCount"], 2)
        self.assertFalse(result["workflowStateMutationAllowed"])
        self.assertFalse(result["permissionGrantAllowed"])

    def test_plan_cannot_grant_permissions_or_change_workflow_state(self):
        plan = sample_plan()
        plan["controlAssertions"]["mayGrantPermissions"] = True
        with self.assertRaises(FactoryPlanError):
            validate_factory_plan(ROOT, plan)

    def test_unknown_role_is_rejected(self):
        plan = sample_plan()
        plan["phases"][0]["assignments"][0]["roleId"] = "super-admin"
        with self.assertRaisesRegex(FactoryPlanError, "unregistered role"):
            validate_factory_plan(ROOT, plan)

    def test_skill_not_declared_by_role_is_rejected(self):
        plan = sample_plan()
        plan["phases"][0]["assignments"][0]["skillId"] = "architecture-plan"
        with self.assertRaisesRegex(FactoryPlanError, "not declared by Role"):
            validate_factory_plan(ROOT, plan)

    def test_dependency_cycle_is_rejected(self):
        plan = sample_plan()
        plan["phases"][0]["dependsOn"] = ["architecture-design"]
        plan["phases"][1]["dependsOn"] = ["requirements-analysis"]
        with self.assertRaisesRegex(FactoryPlanError, "cycle"):
            validate_factory_plan(ROOT, plan)

    def test_assignment_output_cannot_exceed_role_contract(self):
        plan = sample_plan()
        plan["phases"][0]["assignments"][0]["outputEntityTypes"] = ["Release"]
        with self.assertRaisesRegex(FactoryPlanError, "exceed Role"):
            validate_factory_plan(ROOT, plan)

    def test_plan_must_match_run_pinned_ontology_binding(self):
        plan = sample_plan()
        binding = copy.deepcopy(plan["ontologyBinding"])
        binding["ontologyVersion"] = "9.9.9"
        with self.assertRaisesRegex(FactoryPlanError, "active ontology binding"):
            validate_factory_plan(ROOT, plan, ontology_binding=binding)

    def test_plan_tool_budget_must_cover_at_least_one_call_per_assignment(self):
        plan = sample_plan()
        plan["limits"]["maxToolCalls"] = 1
        with self.assertRaisesRegex(FactoryPlanError, "one call budget unit per assignment"):
            validate_factory_plan(ROOT, plan)

    def test_plan_limits_cannot_exceed_team_topology(self):
        plan = sample_plan()
        plan["limits"]["maxParallelAssignments"] = 4
        with self.assertRaisesRegex(FactoryPlanError, "maxParallelAgents"):
            validate_factory_plan(ROOT, plan)


if __name__ == "__main__":
    unittest.main()
