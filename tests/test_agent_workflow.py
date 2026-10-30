import json
import tempfile
import unittest
from pathlib import Path

from ontology_software_factory.agent_workflow import AgentWorkflowStepHandler
from ontology_software_factory.integration import WorkflowOutboxRelay, enqueue_workflow_step
from ontology_software_factory.task_runtime import SQLiteTaskStore, TaskWorker
from ontology_software_factory.workflow_engine import WorkflowEngine
from ontology_software_factory.workflow_store import SQLiteWorkflowStore
from ontology_software_factory.ontology_versioning import create_snapshot

ROOT = Path(__file__).resolve().parents[1]


class FakeAgentRuntime:
    def __init__(self):
        self.calls = []

    def run_agent(self, role_id, task_input, *, ontology_binding, task_contract):
        self.calls.append((role_id, task_input, ontology_binding, task_contract))
        outputs = {
            "requirement-analyst": {
                "summary": "A small HTTP service", "functional_requirements": ["FR-1 /health", "FR-2 /hello"],
                "non_functional_requirements": ["no secrets"], "acceptance_criteria": ["AC-1: health returns ok"],
                "assumptions": [], "open_questions": [], "risk_level": "low",
            },
            "solution-architect": {
                "summary": "Single service", "components": ["HTTP handler"], "data_flows": ["request -> handler -> response"],
                "security_controls": ["validate route"], "tradeoffs": [], "open_questions": [],
            },
            "implementation-agent": {
                "work_items": [{"title": "API skeleton", "description": "Add routes", "depends_on": [], "verification": "Review"}],
                "proposed_changes": [{"relative_path": "src/generated_demo.py", "purpose": "safe sample",
                                      "content": "def health():\n    return {'status': 'ok'}\n"}],
                "out_of_scope": ["deploy"], "requires_human_review": True,
            },
            "test-agent": {
                "test_cases": [{"name": "health returns status", "test_type": "unit", "setup": "load app",
                                "assertion": "response status field is ok", "automation_candidate": True}],
                "required_gates": ["real test execution required before release"], "residual_risks": [],
            },
            "security-reviewer": {
                "findings": [], "release_recommendation": "ready_with_conditions",
                "rationale": "reviewable prototype only", "evidence_gaps": ["generated code not executed"],
            },
        }
        return {"role_id": role_id, "model": "fake", "latency_ms": 1, "tool_ids": [], "output": outputs[role_id]}


def load_definition():
    return json.loads((ROOT / "workflows/definitions/agent-proposal-v1.json").read_text(encoding="utf-8"))


class AgentWorkflowTests(unittest.TestCase):
    def test_real_agent_worker_outbox_inbox_workflow_with_fake_runtime(self):
        # This runs the real Workflow/SQLite Worker/Outbox/Inbox stack with an injected
        # deterministic agent runtime; it does not call external LLM APIs.
        with tempfile.TemporaryDirectory() as temp:
            db = Path(temp) / "integration.sqlite3"
            wf_store = SQLiteWorkflowStore(db)
            task_store = SQLiteTaskStore(db)
            engine = WorkflowEngine(wf_store, load_definition())
            ontology = json.loads((ROOT / "ontology/software-factory-ontology.json").read_text(encoding="utf-8"))
            binding = create_snapshot(ontology, actor="test", reason="workflow integration fixture")
            run = engine.create_run("agent pipeline test", requested_by="test", environment="review", ontology_binding=binding)
            runtime = FakeAgentRuntime()
            artifacts = Path(temp) / "artifacts"
            handler = AgentWorkflowStepHandler(runtime, artifact_root=artifacts)
            worker = TaskWorker(task_store, {
                f"agent.workflow-step.{step_id}": handler
                for step_id in AgentWorkflowStepHandler.STAGE_TO_ROLE
            }, worker_id="unit-test-worker", lease_seconds=5)
            relay = WorkflowOutboxRelay(task_store, engine, relay_id="unit-test-relay")

            for _ in range(5):
                current = engine.get_run(run["id"])
                step = next(x for x in current["steps"] if x["id"] == current["currentStepId"])
                self.assertFalse(step["requiresApproval"])
                task, duplicate = enqueue_workflow_step(
                    task_store, current, step, {"requirement": "Build a small HTTP service"},
                    task_type=f"agent.workflow-step.{step['id']}", worker_max_attempts=step["maxAttempts"],
                )
                self.assertFalse(duplicate)
                result = worker.run_once()
                self.assertEqual(result["status"], "succeeded", result)
                relay_result = relay.drain()
                self.assertGreaterEqual(relay_result.get("delivered", 0), 1, relay_result)

            current = engine.get_run(run["id"])
            self.assertEqual(current["status"], "waiting_approval")
            self.assertEqual(current["currentStepId"], "human-review")
            self.assertEqual([x[0] for x in runtime.calls], [
                "requirement-analyst", "solution-architect", "implementation-agent", "test-agent", "security-reviewer"
            ])
            self.assertTrue(all(call[2]["snapshotId"] == binding["snapshotId"] for call in runtime.calls))
            self.assertTrue(all(call[3]["ontologyDigest"] == binding["digest"] for call in runtime.calls))
            self.assertTrue(all(call[3]["skillRefs"] and all(len(ref["digest"]) == 64 for ref in call[3]["skillRefs"]) for call in runtime.calls))
            self.assertTrue(list(artifacts.rglob("evidence/*.json")))
            self.assertEqual(len(list(artifacts.rglob("agent-result.json"))), 5)
            first_result = json.loads(next(artifacts.rglob("agent-result.json")).read_text(encoding="utf-8"))
            self.assertEqual(first_result["ontologySnapshotId"], binding["snapshotId"])
            self.assertEqual(first_result["skillRefs"], runtime.calls[0][3]["skillRefs"])
            self.assertTrue(list(artifacts.rglob("proposed_changes/src/generated_demo.py")))
            final = engine.apply_action(run["id"], "approve", note="Reviewed candidate artifacts; no code executed", actor="reviewer")
            self.assertEqual(final["status"], "succeeded")
            task_store.close()
            wf_store.close()

    def test_agent_worker_rejects_missing_ontology_binding(self):
        from ontology_software_factory.task_runtime import TaskContext, PermanentTaskError
        with tempfile.TemporaryDirectory() as temp:
            handler = AgentWorkflowStepHandler(FakeAgentRuntime(), artifact_root=Path(temp) / "artifacts")
            payload = {"workflowRunId": "run-test", "workflowStepId": "requirement-analysis",
                       "workflowAttempt": 1, "input": {"requirement": "Build a tiny app"}}
            with self.assertRaises(PermanentTaskError):
                handler(payload, TaskContext("t1", "idempotency-key-1", "w", 1, 9999999999,
                                             ("normalized-requirement",)))

    def test_workflow_role_mismatch_is_rejected(self):
        from ontology_software_factory.task_runtime import TaskContext, PermanentTaskError
        ontology = json.loads((ROOT / "ontology/software-factory-ontology.json").read_text(encoding="utf-8"))
        binding = create_snapshot(ontology, actor="test", reason="role mismatch fixture")
        with tempfile.TemporaryDirectory() as temp:
            handler = AgentWorkflowStepHandler(FakeAgentRuntime(), artifact_root=Path(temp) / "artifacts")
            payload = {"workflowRunId": "run-test", "workflowStepId": "requirement-analysis",
                       "roleId": "security-reviewer", "ontologyBinding": binding,
                       "input": {"requirement": "Build a tiny app"}}
            with self.assertRaises(PermanentTaskError):
                handler(payload, TaskContext("t1", "idempotency-key-1", "w", 1, 9999999999,
                                             ("normalized-requirement",)))

    def test_security_block_stops_before_human_approval(self):
        class BlockingRuntime(FakeAgentRuntime):
            def run_agent(self, role_id, task_input, *, ontology_binding, task_contract):
                result = super().run_agent(role_id, task_input, ontology_binding=ontology_binding, task_contract=task_contract)
                if role_id == "security-reviewer":
                    result["output"]["release_recommendation"] = "blocked"
                return result
        with tempfile.TemporaryDirectory() as temp:
            handler = AgentWorkflowStepHandler(BlockingRuntime(), artifact_root=Path(temp) / "artifacts")
            # Create upstream result files by calling the first four steps in sequence in a
            # miniature handler context, then assert the security stage fails closed.
            from ontology_software_factory.task_runtime import TaskContext, PermanentTaskError
            ontology = json.loads((ROOT / "ontology/software-factory-ontology.json").read_text(encoding="utf-8"))
            binding = create_snapshot(ontology, actor="test", reason="security block fixture")
            requirement = {"workflowRunId": "run-test", "workflowStepId": "requirement-analysis", "workflowAttempt": 1,
                           "ontologyBinding": binding, "input": {"requirement": "Build a tiny app"}}
            handler(requirement, TaskContext("t1", "k1", "w", 1, 9999999999, ("normalized-requirement",)))
            architecture = {"workflowRunId": "run-test", "workflowStepId": "architecture-design", "workflowAttempt": 1,
                            "ontologyBinding": binding, "input": {"requirement": "Build a tiny app"}}
            handler(architecture, TaskContext("t2", "k2", "w", 1, 9999999999, ("architecture-decision-record", "interface-contract")))
            implementation = {"workflowRunId": "run-test", "workflowStepId": "implementation-proposal", "workflowAttempt": 1,
                              "ontologyBinding": binding, "input": {"requirement": "Build a tiny app"}}
            handler(implementation, TaskContext("t3", "k3", "w", 1, 9999999999, ("candidate-change-set", "change-summary")))
            test = {"workflowRunId": "run-test", "workflowStepId": "test-strategy", "workflowAttempt": 1,
                    "ontologyBinding": binding, "input": {"requirement": "Build a tiny app"}}
            handler(test, TaskContext("t4", "k4", "w", 1, 9999999999, ("test-strategy",)))
            security = {"workflowRunId": "run-test", "workflowStepId": "security-review", "workflowAttempt": 1,
                        "ontologyBinding": binding, "input": {"requirement": "Build a tiny app"}}
            with self.assertRaises(PermanentTaskError):
                handler(security, TaskContext("t5", "k5", "w", 1, 9999999999, ("security-review-summary", "evidence-gaps")))


if __name__ == "__main__":
    unittest.main()
