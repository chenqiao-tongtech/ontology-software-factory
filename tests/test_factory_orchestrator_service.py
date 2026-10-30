from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ontology_software_factory.factory_orchestrator_service import FactoryOrchestratorService
from ontology_software_factory.ontology_runtime import build_runtime_contract_lock
from ontology_software_factory.ontology_versioning import create_snapshot
from ontology_software_factory.workflow_engine import WorkflowEngine, WorkflowError
from ontology_software_factory.workflow_store import SQLiteWorkflowStore

ROOT = Path(__file__).resolve().parents[1]


class FakeOrchestratorRuntime:
    project_root = ROOT

    def __init__(self, output):
        self.output = output
        self.calls = []

    def run_agent(self, role_id, task_input, **kwargs):
        self.calls.append((role_id, task_input, kwargs))
        return {
            "output": self.output,
            "model": "fake-orchestrator",
            "latency_ms": 2,
            "tool_ids": ["ontology.definition.read", "catalog.read"],
            "usage": {"inputTokens": 10, "outputTokens": 5},
        }


class FactoryOrchestratorServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = SQLiteWorkflowStore(Path(self.temp.name) / "workflow.sqlite3")
        definition = json.loads((ROOT / "workflows/definitions/software-delivery-v1.json").read_text(encoding="utf-8"))
        self.engine = WorkflowEngine(self.store, definition)
        ontology = json.loads((ROOT / "ontology/software-factory-ontology.json").read_text(encoding="utf-8"))
        binding = create_snapshot(ontology, actor="test", reason="orchestrator generation test")
        lock = build_runtime_contract_lock(
            ROOT, definition, binding, additional_role_ids=["factory-orchestrator"]
        )
        self.run = self.engine.create_run(
            "Autonomous plan test", "tester", "review",
            ontology_binding=binding, runtime_contract_lock=lock,
        )
        self.plan = json.loads((ROOT / "contracts/examples/factory-orchestrator-plan.example.json").read_text(encoding="utf-8"))
        self.runtime = FakeOrchestratorRuntime(self.plan)
        self.service = FactoryOrchestratorService(self.runtime, project_root=ROOT)

    def tearDown(self):
        self.store.close()

    def test_generates_and_submits_server_pinned_plan_pending_independent_approval(self):
        result = self.service.generate_and_submit(
            self.engine, self.run, requirement="Build a governed service configuration delivery workflow."
        )
        plan = result["plan"]["plan"]
        self.assertEqual(self.runtime.calls[0][0], "factory-orchestrator")
        self.assertEqual(self.runtime.calls[0][2]["assigned_skill_id"], "factory-orchestration")
        self.assertEqual(plan["workflowRunId"], self.run["id"])
        self.assertEqual(plan["ontologyBinding"]["digest"], self.run["ontologyBinding"]["digest"])
        self.assertTrue(plan["riskAssessment"]["requiresHumanApproval"])
        self.assertEqual(result["approval"]["status"], "pending")
        self.assertEqual(result["execution"]["roleId"], "factory-orchestrator")

    def test_rejects_missing_runtime_lock_before_model_call(self):
        run = dict(self.run)
        run["runtimeContractLock"] = None
        with self.assertRaises(WorkflowError):
            self.service.generate_and_submit(self.engine, run, requirement="Build a service.")
        self.assertEqual(self.runtime.calls, [])

    def test_rejects_empty_requirement(self):
        with self.assertRaises(WorkflowError):
            self.service.generate_and_submit(self.engine, self.run, requirement=" ")
        self.assertEqual(self.runtime.calls, [])


if __name__ == "__main__":
    unittest.main()
