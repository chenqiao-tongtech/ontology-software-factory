"""Controlled invocation of the Factory Orchestrator Agent.

The service can propose and persist a plan. It never approves or dispatches the plan.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import uuid4

from .ontology_runtime import (
    build_agent_task_contract,
    validate_runtime_contract_lock,
    validate_ontology_binding,
)
from .workflow_engine import WorkflowError


class FactoryOrchestratorService:
    def __init__(self, runtime: Any, *, project_root: str | Path):
        self.runtime = runtime
        self.project_root = Path(project_root).resolve()

    def generate_and_submit(
        self, engine: Any, run: dict[str, Any], *, requirement: str,
    ) -> dict[str, Any]:
        run_id = str(run.get("id", ""))
        requirement = str(requirement).strip()
        if not run_id or not requirement or len(requirement) > 30_000:
            raise WorkflowError("a Workflow Run and requirement of 1..30000 characters are required", 400)
        if run.get("status") != "running":
            raise WorkflowError("Factory Orchestrator can only plan for a running Workflow Run", 409)
        binding = validate_ontology_binding(run.get("ontologyBinding") or {})
        lock = run.get("runtimeContractLock")
        if not isinstance(lock, dict):
            raise WorkflowError("Workflow Run has no immutable Role/Skill runtime lock", 409)
        try:
            locked = validate_runtime_contract_lock(
                self.project_root, lock, "factory-orchestrator", binding
            )
            role = locked["role"]
            task_contract = build_agent_task_contract(
                self.project_root, role=role, binding=binding, run_id=run_id,
                step_id="factory-orchestrator-plan", attempt=1,
                objective="Create a bounded, evidence-aware AgentPlan for the approved requirement.",
                timeout_seconds=900, max_attempts=1,
                idempotency_key=f"factory-orchestrator:{run_id}:plan:v1",
                output_entity_types=["AgentPlan", "Artifact"], max_tool_calls=20,
            )
            execution = self.runtime.run_agent(
                "factory-orchestrator",
                {
                    "run_id": run_id,
                    "source_requirement": requirement,
                    "objective": "Propose a safe and executable software-factory plan for this requirement.",
                    "acceptance_criteria": [
                        "Every phase has verifiable acceptance criteria.",
                        "Every Assignment uses a registered Role and compatible Skill.",
                        "Dependencies form a DAG and all resource limits fit the team topology.",
                        "The plan is bound to the Workflow Run ontology snapshot.",
                        "The plan requests independent human approval and does not perform execution.",
                    ],
                    "budget": {"maxAgentAssignments": 10, "maxParallelAssignments": 3,
                               "maxRevisionLoops": 2, "maxToolCalls": 100, "timeoutSeconds": 3600},
                    "run_budget": {"maxToolCalls": 20, "maxInputTokens": 100_000,
                                   "maxOutputTokens": 40_000},
                },
                ontology_binding=binding, task_contract=task_contract,
                runtime_contract_lock=lock, assigned_skill_id="factory-orchestration",
            )
        except WorkflowError:
            raise
        except Exception as exc:
            raise WorkflowError(
                f"Factory Orchestrator execution failed ({type(exc).__name__})", 502
            ) from exc

        proposed = execution.get("output")
        if not isinstance(proposed, dict):
            raise WorkflowError("Factory Orchestrator returned no structured plan", 422)
        plan = dict(proposed)
        # The control plane, not the model, owns the run ID, plan ID and ontology binding.
        plan["planId"] = f"sf:agent-plan:{run_id.lower()}-{uuid4().hex[:12]}"
        plan["workflowRunId"] = run_id
        plan["ontologyBinding"] = {
            key: binding[key] for key in
            ("snapshotId", "digest", "ontologyId", "ontologyVersion", "schemaVersion")
        }
        plan["riskAssessment"] = dict(plan.get("riskAssessment") or {})
        plan["riskAssessment"]["requiresHumanApproval"] = True
        result = engine.submit_factory_orchestrator_plan(run_id, plan, actor="factory-orchestrator")
        return {
            **result,
            "execution": {
                "roleId": "factory-orchestrator",
                "skillId": "factory-orchestration",
                "model": execution.get("model"),
                "latencyMs": execution.get("latency_ms"),
                "toolIds": execution.get("tool_ids", []),
                "usage": execution.get("usage"),
            },
            "approval": engine.store.get_factory_plan_approval(plan["planId"]),
        }
