"""Deterministic workflow state machine for the Article 19 reference project.

The engine records commands and transitions; it does not invoke LLMs, run CI,
or deploy software. Those responsibilities belong in separately authorized workers.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from .workflow_store import ConcurrentWorkflowUpdate, SQLiteWorkflowStore

RUN_TERMINAL = {"succeeded", "failed", "cancelled"}
RUN_STATUSES = {"queued", "running", "waiting_approval", "paused", "failed", "succeeded", "cancelled"}
STEP_TERMINAL = {"succeeded", "failed", "cancelled"}


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class WorkflowError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


class WorkflowEngine:
    def __init__(self, store: SQLiteWorkflowStore, definition: dict[str, Any]):
        self.store = store
        self.definition = deepcopy(definition)
        self._steps_by_id = {step["id"]: step for step in self.definition["steps"]}
        self._validate_definition()

    def _validate_definition(self) -> None:
        ids = list(self._steps_by_id)
        if len(ids) != len(set(ids)):
            raise ValueError("Workflow step IDs must be unique")
        if self.definition.get("startStepId") not in self._steps_by_id:
            raise ValueError("startStepId must reference a declared step")
        known = set(ids)
        for step in self.definition["steps"]:
            missing = set(step.get("dependsOn", [])) - known
            if missing:
                raise ValueError(f"Step {step['id']} references unknown dependencies: {sorted(missing)}")
            if step["id"] in step.get("dependsOn", []):
                raise ValueError(f"Step {step['id']} cannot depend on itself")
        # Kahn topological check: reject cycles before any run is accepted.
        indegree = {sid: 0 for sid in ids}
        children = {sid: [] for sid in ids}
        for step in self.definition["steps"]:
            for parent in step.get("dependsOn", []):
                indegree[step["id"]] += 1
                children[parent].append(step["id"])
        ready = [sid for sid, degree in indegree.items() if degree == 0]
        visited = 0
        while ready:
            node = ready.pop()
            visited += 1
            for child in children[node]:
                indegree[child] -= 1
                if indegree[child] == 0:
                    ready.append(child)
        if visited != len(ids):
            raise ValueError("Workflow dependencies must form a DAG; cycle detected")

    def list_runs(self) -> list[dict[str, Any]]:
        return self.store.list_runs()

    def get_run(self, run_id: str) -> dict[str, Any]:
        run = self.store.get_run(run_id)
        if run is None:
            raise WorkflowError(f"Workflow run not found: {run_id}", 404)
        return run

    def get_run_detail(self, run_id: str) -> dict[str, Any]:
        run = self.get_run(run_id)
        plans = self.store.list_factory_orchestrator_plans(run_id)
        return {"run": run, "events": self.store.get_events(run_id), "orchestratorPlans": plans}

    def submit_factory_orchestrator_plan(self, run_id: str, plan: dict[str, Any],
                                         actor: str = "factory-orchestrator") -> dict[str, Any]:
        """Validate and durably attach an immutable Orchestrator plan to its Workflow Run."""
        run = self.get_run(run_id)
        if run.get("status") not in {"running", "queued", "waiting_approval"}:
            raise WorkflowError("cannot submit an Orchestrator plan to a terminal or paused run", 409)
        if not isinstance(plan, dict) or plan.get("workflowRunId") != run_id:
            raise WorkflowError("plan workflowRunId must match the target Workflow Run", 422)
        binding = run.get("ontologyBinding")
        if not isinstance(binding, dict):
            raise WorkflowError("Workflow Run has no pinned ontology binding", 409)
        try:
            from .factory_orchestration import validate_factory_plan
            validation = validate_factory_plan(
                Path(__file__).resolve().parents[2], plan, ontology_binding=binding
            )
        except Exception as exc:
            raise WorkflowError(f"Orchestrator plan validation failed: {type(exc).__name__}: {exc}", 422) from exc
        timestamp = now_iso()
        event = self._event(
            "factory.plan.submitted",
            f"主控计划已通过校验并持久化：{plan['planId']}",
            actor=actor,
            payload={
                "planId": plan["planId"], "planDigest": None,
                "phaseCount": validation["phaseCount"],
                "assignmentCount": validation["assignmentCount"],
                "ontologySnapshotId": validation["ontologySnapshotId"],
            },
        )
        event["at"] = timestamp
        try:
            record, created = self.store.insert_factory_orchestrator_plan(run_id, plan, event)
        except ValueError as exc:
            raise WorkflowError(str(exc), 409) from exc
        return {"plan": record, "validation": validation, "created": created}

    def create_run(self, title: str, requested_by: str = "local-operator", environment: str = "staging",
                   ontology_binding: dict[str, Any] | None = None,
                   runtime_contract_lock: dict[str, Any] | None = None) -> dict[str, Any]:
        if ontology_binding is not None:
            from .ontology_runtime import validate_ontology_binding
            ontology_binding = validate_ontology_binding(ontology_binding)
        timestamp = now_iso()
        run_id = f"RUN-{uuid4().hex[:6].upper()}"
        steps = []
        for spec in self.definition["steps"]:
            steps.append({
                "id": spec["id"], "name": spec["name"], "roleId": spec["roleId"],
                "skillId": spec.get("skillId"), "executionMode": spec["executionMode"],
                "status": "pending", "attempt": 0, "maxAttempts": spec["maxAttempts"],
                "dependsOn": list(spec.get("dependsOn", [])), "requiresApproval": bool(spec.get("requiresApproval")),
                "retryableErrorClasses": list(spec.get("retryableErrorClasses", [])),
                "requiredEvidence": list(spec.get("requiresEvidence", [])),
                "requiresIdempotencyKey": bool(spec.get("requiresIdempotencyKey", False)),
                "sideEffect": spec.get("sideEffect", "none"), "compensation": spec.get("compensation"),
                "retryable": False, "startedAt": None, "finishedAt": None, "evidence": [], "error": None,
            })
        run = {
            "id": run_id, "workflowId": self.definition["id"], "workflowVersion": self.definition["version"],
            "title": title.strip() or "新建软件交付运行", "status": "running",
            "currentStepId": self.definition["startStepId"], "createdAt": timestamp, "updatedAt": timestamp,
            "requestedBy": requested_by, "environment": environment, "revision": 1,
            "ontologyBinding": ontology_binding,
            "runtimeContractLock": runtime_contract_lock,
            "steps": steps,
        }
        first = self._step(run, run["currentStepId"])
        first["status"] = "running"
        first["attempt"] = 1
        first["startedAt"] = timestamp
        event = self._event("run.created", f"创建工作流运行：{run['title']}", actor=requested_by, payload={"workflowVersion": run["workflowVersion"], "ontologySnapshotId": (ontology_binding or {}).get("snapshotId"), "ontologyDigest": (ontology_binding or {}).get("digest"), "ontologyVersion": (ontology_binding or {}).get("ontologyVersion"), "ontologySchemaVersion": (ontology_binding or {}).get("schemaVersion"), "runtimeContractLockDigest": (runtime_contract_lock or {}).get("digest")})
        self.store.insert_new_run(run, event)
        return self.get_run(run_id)

    def apply_worker_event(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Project an outbox event onto the workflow, atomically deduplicating via the inbox."""
        from .integration import IntegrationEventDeferred

        event_id = str(payload.get("eventId", ""))
        run_id = str(payload.get("workflowRunId", ""))
        step_id = str(payload.get("workflowStepId", ""))
        if not event_id or not run_id or not step_id:
            raise WorkflowError("Worker event missing eventId/workflowRunId/workflowStepId", 400)
        if self.store.has_processed_integration_event(event_id):
            return {"run": self.get_run(run_id), "deduplicated": True, "ignored": False}
        run = self.get_run(run_id)
        if run["status"] == "paused":
            raise IntegrationEventDeferred("workflow is paused; keep result event pending until resume")
        step = self._step(run, step_id)
        if run["status"] != "running":
            reason = f"workflow status is {run['status']}"
            event = self._event("worker.result_ignored", "", actor="workflow-projector",
                                payload={"taskId": payload.get("taskId"), "stepId": step_id})
            self.store.record_ignored_integration_event(run_id, event, event_id, reason)
            return {"run": self.get_run(run_id), "deduplicated": False, "ignored": True, "reason": reason}
        expected_attempt = payload.get("workflowAttempt")
        if (run.get("currentStepId") != step_id or step.get("status") != "running"
                or (expected_attempt is not None and int(expected_attempt) != int(step.get("attempt", 0)))):
            reason = (f"stale step result: currentStepId={run.get('currentStepId')}, "
                      f"stepStatus={step.get('status')}, expectedAttempt={expected_attempt}, "
                      f"currentAttempt={step.get('attempt')}")
            event = self._event("worker.result_ignored", "", actor="workflow-projector",
                                payload={"taskId": payload.get("taskId"), "stepId": step_id})
            self.store.record_ignored_integration_event(run_id, event, event_id, reason)
            return {"run": self.get_run(run_id), "deduplicated": False, "ignored": True, "reason": reason}

        expected_revision = int(run["revision"])
        run = deepcopy(run)
        target = self._step(run, step_id)
        task_id = str(payload.get("taskId", ""))
        task_status = payload.get("taskStatus")
        target["executionTaskId"] = task_id
        if task_status == "succeeded":
            evidence = payload.get("evidence", [])
            if not isinstance(evidence, list):
                raise WorkflowError("worker result evidence must be a list", 400)
            actual_types = {str(item.get("type")) for item in evidence if isinstance(item, dict)}
            missing = sorted(set(target.get("requiredEvidence", [])) - actual_types)
            if missing:
                raise WorkflowError(f"worker result violates evidence contract: missing {missing}", 422)
            target["status"] = "succeeded"
            target["finishedAt"] = now_iso()
            target["retryable"] = False
            target["error"] = None
            target["executionResult"] = {
                "taskId": task_id, "eventId": event_id, "workerAttempt": payload.get("attempt"),
                "output": payload.get("output", {}), "evidence": evidence,
            }
            for item in evidence:
                target.setdefault("evidence", []).append(
                    f"执行证据：{item.get('type')} → {item.get('uri')} (sha256={item.get('sha256')})")
            run["currentStepId"] = step_id
            self._advance(run)
            action = "step.succeeded"
            summary = f"Worker 结果已回写：{target['name']} 成功，taskId={task_id}"
        elif task_status in {"failed", "dead_letter"}:
            error_class = str(payload.get("errorClass", "unknown"))
            error_message = str(payload.get("errorMessage", "Worker task failed"))[:4000]
            target["status"] = "failed"
            target["finishedAt"] = now_iso()
            target["error"] = f"{error_class}: {error_message}"
            aliases = {
                "timeout": "transient_timeout", "transient": "transient_timeout",
                "transient_network_error": "transient_network_error", "worker_lost": "worker_lost",
                "rate_limited": "rate_limited",
            }
            retryable_classes = set(target.get("retryableErrorClasses", []))
            retryable = (error_class in retryable_classes or aliases.get(error_class) in retryable_classes)
            target["retryable"] = bool(retryable and target["attempt"] < target["maxAttempts"])
            target["executionResult"] = {
                "taskId": task_id, "eventId": event_id, "workerAttempt": payload.get("attempt"),
                "errorClass": error_class, "errorMessage": error_message,
                "taskStatus": task_status,
            }
            run["status"] = "failed"
            run["currentStepId"] = step_id
            action = "step.failed"
            summary = f"Worker 结果已回写：{target['name']} 失败；可重试={str(target['retryable']).lower()}"
        else:
            raise WorkflowError(f"unsupported worker taskStatus: {task_status}", 400)

        run["updatedAt"] = now_iso()
        run["revision"] = expected_revision + 1
        event = self._event(action, summary, actor="workflow-projector", payload={
            "integrationEventId": event_id, "taskId": task_id, "stepId": step_id,
            "workflowAttempt": expected_attempt, "workerAttempt": payload.get("attempt"),
            "taskStatus": task_status, "errorClass": payload.get("errorClass"),
        })
        try:
            consumed = self.store.save_worker_result(run, event, expected_revision=expected_revision,
                                                     integration_event_id=event_id)
        except ConcurrentWorkflowUpdate as exc:
            raise WorkflowError(str(exc), 409) from exc
        return {"run": self.get_run(run_id), "deduplicated": not consumed, "ignored": False}

    def apply_action(self, run_id: str, action: str, *, step_id: str | None = None,
                     note: str = "", actor: str = "local-operator") -> dict[str, Any]:
        run = self.get_run(run_id)
        expected_revision = int(run["revision"])
        run = deepcopy(run)
        note = (note or "").strip()
        current = self._step(run, run.get("currentStepId")) if run.get("currentStepId") else None
        event_action = action
        payload: dict[str, Any] = {"stepId": (step_id or (current or {}).get("id")), "note": note}

        try:
            if action == "complete_step":
                target = self._active_running_step(run, step_id)
                target["status"] = "succeeded"
                target["finishedAt"] = now_iso()
                target["retryable"] = False
                target["error"] = None
                target["evidence"].append("演示证据：节点完成命令已通过状态机校验（未连接真实执行器）")
                event_action = "step.succeeded"
                summary = f"节点完成：{target['name']}"
                self._advance(run)
            elif action == "fail_step":
                target = self._active_running_step(run, step_id)
                target["status"] = "failed"
                target["finishedAt"] = now_iso()
                target["error"] = note or "模拟瞬时错误：Worker 心跳丢失，结果未持久化"
                reason_lower = target["error"].lower()
                deterministic_markers = ("permission", "权限", "assertion", "断言", "schema", "policy", "策略", "拒绝")
                is_deterministic = any(marker in reason_lower for marker in deterministic_markers)
                target["retryable"] = target["attempt"] < target["maxAttempts"] and not is_deterministic
                run["status"] = "failed"
                run["currentStepId"] = target["id"]
                event_action = "step.failed"
                summary = f"节点失败：{target['name']}；可重试={str(target['retryable']).lower()}"
            elif action == "retry":
                target = self._failed_step(run, step_id)
                if not target["retryable"] or target["attempt"] >= target["maxAttempts"]:
                    raise WorkflowError("该失败节点不可重试或已达到最大尝试次数", 409)
                target["attempt"] += 1
                target["status"] = "running"
                target["startedAt"] = now_iso()
                target["finishedAt"] = None
                target["error"] = None
                target["retryable"] = False
                run["currentStepId"] = target["id"]
                run["status"] = "running"
                event_action = "step.retry_requested"
                summary = f"已排入第 {target['attempt']} 次尝试：{target['name']}（演示模式由操作台模拟 Worker 接管）"
            elif action == "approve":
                target = self._approval_step(run, step_id)
                if not note:
                    raise WorkflowError("审批必须填写理由，以便审计", 400)
                target["status"] = "succeeded"
                target["finishedAt"] = now_iso()
                target["evidence"].append(f"人工审批记录：批准；操作人={actor}；理由={note}")
                target["error"] = None
                run["currentStepId"] = target["id"]
                event_action = "approval.granted"
                summary = f"审批通过：{target['name']}"
                self._advance(run)
            elif action == "reject":
                target = self._approval_step(run, step_id)
                if not note:
                    raise WorkflowError("拒绝审批必须填写原因", 400)
                target["status"] = "failed"
                target["finishedAt"] = now_iso()
                target["error"] = f"人工拒绝：{note}"
                target["retryable"] = False
                run["status"] = "failed"
                run["currentStepId"] = target["id"]
                event_action = "approval.rejected"
                summary = f"审批拒绝：{target['name']}"
            elif action == "pause":
                if run["status"] != "running":
                    raise WorkflowError("只有 running 状态的运行可以暂停", 409)
                run["status"] = "paused"
                event_action = "run.paused"
                summary = "运行已暂停；当前节点检查点保留"
            elif action == "resume":
                if run["status"] != "paused":
                    raise WorkflowError("只有 paused 状态的运行可以恢复", 409)
                run["status"] = "running"
                event_action = "run.resumed"
                summary = "运行已恢复；等待执行器继续处理当前节点"
            elif action == "cancel":
                if run["status"] in RUN_TERMINAL:
                    raise WorkflowError(f"终态运行不能取消：{run['status']}", 409)
                for step in run["steps"]:
                    if step["status"] in {"pending", "running", "waiting_approval"}:
                        step["status"] = "cancelled"
                        step["finishedAt"] = now_iso()
                run["status"] = "cancelled"
                run["currentStepId"] = None
                event_action = "run.cancelled"
                summary = "运行已取消；未开始节点标记为 cancelled"
            else:
                raise WorkflowError(f"不支持的动作：{action}", 400)
        except WorkflowError:
            raise

        run["updatedAt"] = now_iso()
        run["revision"] = expected_revision + 1
        event = self._event(event_action, summary, actor=actor, payload=payload)
        try:
            self.store.save_updated_run(run, event, expected_revision)
        except ConcurrentWorkflowUpdate as exc:
            raise WorkflowError(str(exc), 409) from exc
        return self.get_run(run_id)

    def _step(self, run: dict[str, Any], step_id: str | None) -> dict[str, Any]:
        if step_id is None:
            raise WorkflowError("当前运行没有活动节点", 409)
        for step in run["steps"]:
            if step["id"] == step_id:
                return step
        raise WorkflowError(f"节点不存在：{step_id}", 404)

    def _active_running_step(self, run: dict[str, Any], step_id: str | None) -> dict[str, Any]:
        target = self._step(run, step_id or run.get("currentStepId"))
        if run["status"] != "running" or target["status"] != "running" or target["id"] != run.get("currentStepId"):
            raise WorkflowError("只能完成或模拟失败当前正在运行的节点", 409)
        return target

    def _failed_step(self, run: dict[str, Any], step_id: str | None) -> dict[str, Any]:
        target = self._step(run, step_id or run.get("currentStepId"))
        if target["status"] != "failed":
            raise WorkflowError("只能重试 failed 节点", 409)
        if run["status"] != "failed":
            raise WorkflowError("只有失败的运行可执行节点重试", 409)
        return target

    def _approval_step(self, run: dict[str, Any], step_id: str | None) -> dict[str, Any]:
        target = self._step(run, step_id or run.get("currentStepId"))
        if run["status"] != "waiting_approval" or target["status"] != "waiting_approval" or not target["requiresApproval"]:
            raise WorkflowError("当前运行不在等待审批门，不能执行审批", 409)
        return target

    def _advance(self, run: dict[str, Any]) -> None:
        status_by_id = {step["id"]: step["status"] for step in run["steps"]}
        for step in run["steps"]:
            if step["status"] != "pending":
                continue
            if not all(status_by_id.get(dep) == "succeeded" for dep in step["dependsOn"]):
                continue
            run["currentStepId"] = step["id"]
            step["startedAt"] = now_iso()
            if step["requiresApproval"]:
                step["status"] = "waiting_approval"
                run["status"] = "waiting_approval"
            else:
                step["status"] = "running"
                step["attempt"] = max(1, int(step["attempt"]) + 1)
                run["status"] = "running"
            return
        statuses = [step["status"] for step in run["steps"]]
        failed_steps = [step for step in run["steps"] if step["status"] == "failed"]
        if failed_steps:
            run["status"] = "failed"
            run["currentStepId"] = failed_steps[-1]["id"]
        elif all(status in {"succeeded", "cancelled"} for status in statuses) and "cancelled" not in statuses:
            run["status"] = "succeeded"
            run["currentStepId"] = None
        elif all(status == "succeeded" for status in statuses):
            run["status"] = "succeeded"
            run["currentStepId"] = None
        else:
            run["status"] = "queued"
            run["currentStepId"] = next((step["id"] for step in run["steps"] if step["status"] == "pending"), None)

    @staticmethod
    def _event(action: str, summary: str, *, actor: str = "system", payload: dict[str, Any] | None = None) -> dict[str, Any]:
        return {"at": now_iso(), "actor": actor, "action": action, "summary": summary, "payload": payload or {}}
