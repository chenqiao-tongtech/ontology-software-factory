from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from ontology_software_factory.factory_plan_runtime import (
    FactoryAssignmentHandler, FactoryPlanDispatcher, get_factory_plan_execution,
)
from ontology_software_factory.integration import WorkflowOutboxRelay
from ontology_software_factory.ontology_runtime import build_runtime_contract_lock
from ontology_software_factory.ontology_versioning import create_snapshot
from ontology_software_factory.task_runtime import SQLiteTaskStore, TaskWorker
from ontology_software_factory.workflow_engine import WorkflowEngine
from ontology_software_factory.workflow_store import SQLiteWorkflowStore

ROOT = Path(__file__).resolve().parents[1]


class FakeAssignmentRuntime:
    project_root = ROOT

    def __init__(self):
        self.calls = []

    def run_agent(self, role_id, task_input, **kwargs):
        self.calls.append((role_id, task_input, kwargs))
        return {
            "output": {
                "summary": "Validated assignment output",
                "functional_requirements": ["FR-1"],
                "non_functional_requirements": ["No secrets"],
                "acceptance_criteria": ["AC-1"],
                "assumptions": [],
                "open_questions": [],
                "risk_level": "low",
            },
            "model": "fake",
            "latency_ms": 1,
            "tool_ids": [],
        }


class FactoryPlanRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Path(self.temp.name) / "factory.sqlite3"
        self.workflow_store = SQLiteWorkflowStore(self.db)
        self.task_store = SQLiteTaskStore(self.db)
        self.definition = json.loads((ROOT / "workflows/definitions/software-delivery-v1.json").read_text(encoding="utf-8"))
        self.engine = WorkflowEngine(self.workflow_store, self.definition)
        ontology = json.loads((ROOT / "ontology/software-factory-ontology.json").read_text(encoding="utf-8"))
        self.binding = create_snapshot(ontology, actor="test", reason="factory plan runtime test")
        plan_example = json.loads((ROOT / "contracts/examples/factory-orchestrator-plan.example.json").read_text(encoding="utf-8"))
        role_ids = sorted({assignment["roleId"] for phase in plan_example["phases"] for assignment in phase["assignments"]})
        self.lock = build_runtime_contract_lock(
            ROOT, self.definition, self.binding, additional_role_ids=role_ids
        )
        self.run = self.engine.create_run(
            "Factory assignment integration test", "test", "review",
            ontology_binding=self.binding, runtime_contract_lock=self.lock,
        )
        self.plan = plan_example
        self.plan["workflowRunId"] = self.run["id"]
        self.plan["ontologyBinding"] = {
            key: self.binding[key] for key in ("snapshotId", "digest", "ontologyId", "ontologyVersion", "schemaVersion")
        }
        self.plan["riskAssessment"]["requiresHumanApproval"] = False
        self.plan_record = self.engine.submit_factory_orchestrator_plan(self.run["id"], self.plan)["plan"]
        self.engine.decide_factory_orchestrator_plan(
            self.run["id"], self.plan["planId"], "approved",
            actor="test-reviewer", reason="Test fixture approval",
        )
        self.dispatcher = FactoryPlanDispatcher(self.task_store, project_root=ROOT, workflow_store=self.workflow_store)

    def tearDown(self):
        self.task_store.close()
        self.workflow_store.close()

    def test_dispatch_only_enqueues_dependency_ready_phase(self):
        first = self.dispatcher.dispatch_ready(self.run, self.plan_record)
        self.assertEqual([item["assignmentId"] for item in first["enqueued"]], ["analyze-requirement"])
        self.assertEqual(first["execution"]["phases"][0]["status"], "running")
        persisted = self.workflow_store.list_factory_plan_phases(self.run["id"], self.plan["planId"])
        requirements_phase = next(item for item in persisted if item["phaseId"] == "requirements-analysis")
        self.assertEqual(requirements_phase["status"], "running")
        self.assertEqual(first["execution"]["phases"][1]["status"], "pending")
        self.assertEqual(len(self.task_store.list_tasks()), 1)

        task = self.task_store.list_tasks()[0]
        self.task_store.claim("test-worker", lease_seconds=30)
        evidence = [{
            "type": "agent-result-contract", "uri": "artifact://test/result.json",
            "sha256": "a" * 64,
        }]
        self.task_store.complete(task["id"], "test-worker", output={"summary": "done"}, evidence=evidence)
        before_relay = self.dispatcher.dispatch_ready(self.run, self.plan_record)
        self.assertEqual(before_relay["enqueued"], [])
        self.assertIn("architecture-design", before_relay["blockedPhases"])
        WorkflowOutboxRelay(
            self.task_store, self.engine, relay_id="factory-phase-test-relay"
        ).drain()

        second = self.dispatcher.dispatch_ready(self.run, self.plan_record)
        self.assertEqual([item["assignmentId"] for item in second["enqueued"]], ["design-solution"])
        self.assertEqual(second["execution"]["phases"][0]["status"], "succeeded")
        self.assertEqual(second["execution"]["phases"][1]["status"], "running")

    def test_dispatch_rejects_mutated_persisted_plan_payload(self):
        tampered = copy.deepcopy(self.plan_record)
        tampered["plan"]["objective"] = "tampered after persistence"
        with self.assertRaisesRegex(ValueError, "digest mismatch"):
            self.dispatcher.dispatch_ready(self.run, tampered)
        self.assertEqual(self.task_store.list_tasks(), [])

    def test_dispatch_is_idempotent_and_parallelism_is_bounded(self):
        first = self.dispatcher.dispatch_ready(self.run, self.plan_record)
        again = self.dispatcher.dispatch_ready(self.run, self.plan_record)
        self.assertEqual(len(first["enqueued"]), 1)
        self.assertEqual(again["enqueued"], [])
        self.assertEqual(len(self.task_store.list_tasks()), 1)

    def test_high_risk_or_human_approval_plan_is_not_dispatched(self):
        self.plan["planId"] = "sf:agent-plan:approval-required-002"
        self.plan["riskAssessment"]["requiresHumanApproval"] = True
        self.plan["riskAssessment"]["level"] = "high"
        self.plan_record = self.engine.submit_factory_orchestrator_plan(self.run["id"], self.plan)["plan"]
        result = self.dispatcher.dispatch_ready(self.run, self.plan_record)
        self.assertEqual(result["status"], "approval_required")
        self.assertEqual(result["enqueued"], [])
        self.assertEqual(self.task_store.list_tasks(), [])

    def test_assignment_worker_executes_selected_role_and_skill_and_writes_evidence(self):
        self.dispatcher.dispatch_ready(self.run, self.plan_record)
        fake = FakeAssignmentRuntime()
        handler = FactoryAssignmentHandler(fake, artifact_root=Path(self.temp.name) / "artifacts")
        worker = TaskWorker(self.task_store, {"agent.factory-assignment": handler}, worker_id="factory-worker")
        result = worker.run_once()
        self.assertEqual(result["status"], "succeeded", result)
        self.assertEqual(fake.calls[0][0], "requirement-analyst")
        self.assertEqual(fake.calls[0][2]["assigned_skill_id"], "requirement-normalization")
        self.assertEqual(result["task"]["evidence"][0]["type"], "agent-result-contract")
        relay = WorkflowOutboxRelay(self.task_store, self.engine, relay_id="factory-plan-test-relay")
        relayed = relay.drain()
        self.assertEqual(relayed["delivered"], 1)
        detail = self.engine.get_run_detail(self.run["id"])
        self.assertEqual(detail["factoryAssignmentResults"][0]["assignmentId"], "analyze-requirement")
        self.assertIn("factory.assignment.succeeded", [item["action"] for item in detail["events"]])
        execution = get_factory_plan_execution(self.task_store, self.plan_record, self.workflow_store)
        self.assertEqual(execution["completedAssignments"], 1)
        self.assertEqual(execution["phases"][0]["status"], "succeeded")
        self.assertEqual(
            next(
                item["status"] for item in self.workflow_store.list_factory_plan_phases(
                    self.run["id"], self.plan["planId"]
                ) if item["phaseId"] == "requirements-analysis"
            ),
            "succeeded",
        )
        self.assertTrue(list((Path(self.temp.name) / "artifacts").rglob("agent-result.json")))


if __name__ == "__main__":
    unittest.main()
