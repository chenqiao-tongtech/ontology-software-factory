"""Article 21: workflow-task closed-loop integration with a transactional outbox.

The task transition and its outbox row share one SQLite transaction. Delivery to the
workflow store is at-least-once; the workflow inbox deduplicates by integration event ID.
"""
from __future__ import annotations

import hashlib
import time
from typing import Any

from .task_runtime import SQLiteTaskStore
from .workflow_engine import WorkflowEngine


class IntegrationEventDeferred(RuntimeError):
    """A valid event cannot be applied yet (for example, its workflow is paused)."""


def _queue_retry_classes(step: dict[str, Any]) -> list[str]:
    aliases = {
        "transient_timeout": ["transient", "timeout"],
        "transient_network_error": ["transient", "timeout"],
        "worker_lost": ["worker_lost"],
        "rate_limited": ["rate_limited"],
        "transient": ["transient"],
        "timeout": ["timeout"],
    }
    result: set[str] = set()
    for item in step.get("retryableErrorClasses", []):
        result.update(aliases.get(str(item), [str(item)]))
    return sorted(result)


def enqueue_workflow_step(store: SQLiteTaskStore, run: dict[str, Any], step: dict[str, Any],
                          input_payload: dict[str, Any] | None = None, *,
                          task_type: str = "demo.workflow-step", worker_max_attempts: int = 3,
                          queue: str = "default", worker_backoff_base_seconds: float = 1.0,
                          worker_backoff_max_seconds: float = 60.0) -> tuple[dict[str, Any], bool]:
    """Translate an active workflow step into a stable, idempotent Worker task envelope."""
    if run.get("status") != "running" or run.get("currentStepId") != step.get("id") or step.get("status") != "running":
        raise ValueError("only the current running workflow step can be dispatched")
    if step.get("requiresApproval") or step.get("executionMode") == "human":
        raise ValueError("human/approval steps must not be dispatched to a Worker")
    if not run.get("id") or not step.get("id"):
        raise ValueError("workflow run and step IDs are required")
    attempt = int(step.get("attempt", 0))
    if attempt < 1:
        raise ValueError("workflow step attempt must be >= 1")
    business_operation_id = f"{run['id']}:{step['id']}"
    idempotency_key = f"workflow:{run['id']}:{step['id']}:attempt:{attempt}"
    payload = {
        "workflowRunId": run["id"], "workflowStepId": step["id"],
        "workflowId": run.get("workflowId"), "workflowVersion": run.get("workflowVersion"),
        "workflowAttempt": attempt, "businessOperationId": business_operation_id,
        "correlationId": f"corr:{run['id']}:{step['id']}:{attempt}",
        "environment": run.get("environment", "test"), "requestedBy": run.get("requestedBy", "unknown"),
        "roleId": step.get("roleId"), "skillId": step.get("skillId"),
        "ontologyBinding": run.get("ontologyBinding"),
        "workerMaxAttempts": worker_max_attempts,
        "input": input_payload or {},
    }
    timeout = float(step.get("timeoutSeconds", 60))
    return store.enqueue(
        task_type=task_type, payload=payload, idempotency_key=idempotency_key, queue=queue,
        max_attempts=worker_max_attempts, timeout_seconds=timeout,
        retryable_error_classes=_queue_retry_classes(step),
        required_evidence=list(step.get("requiredEvidence", [])),
        backoff_base_seconds=worker_backoff_base_seconds,
        backoff_max_seconds=worker_backoff_max_seconds,
    )


def demo_workflow_step_handler(payload: dict[str, Any], context) -> dict[str, Any]:
    """Produce clearly labeled demo artifacts; it never calls a real LLM/CI/deployer."""
    context.check_deadline()
    workflow_run = payload["workflowRunId"]
    step_id = payload["workflowStepId"]
    digest_seed = f"{context.idempotency_key}|{payload.get('input', {})}|demo-artifact"
    digest = hashlib.sha256(digest_seed.encode("utf-8")).hexdigest()
    evidence = []
    for evidence_type in context.required_evidence:
        evidence.append({
            "type": evidence_type,
            "uri": f"demo://artifacts/{workflow_run}/{step_id}/{context.attempt}/{evidence_type}",
            "sha256": digest,
            "metadata": {"generatedBy": "demo-workflow-handler", "notProductionArtifact": True},
        })
    return {
        "output": {
            "workflowRunId": workflow_run, "stepId": step_id,
            "summary": f"演示执行器已处理 {step_id}；此结果不代表真实 Agent/CI/部署完成",
            "inputAccepted": True,
        },
        "evidence": evidence,
    }


class WorkflowOutboxRelay:
    """Relays durable task-result events to a workflow engine with inbox dedupe."""

    def __init__(self, task_store: SQLiteTaskStore, workflow_engine: WorkflowEngine, *,
                 relay_id: str = "workflow-outbox-relay", lease_seconds: float = 30,
                 max_delivery_attempts: int = 12):
        self.task_store = task_store
        self.workflow_engine = workflow_engine
        self.relay_id = relay_id
        self.lease_seconds = lease_seconds
        self.max_delivery_attempts = max_delivery_attempts

    def run_once(self, *, limit: int = 20) -> dict[str, Any]:
        events = self.task_store.claim_outbox(self.relay_id, limit=limit, lease_seconds=self.lease_seconds)
        delivered = 0
        deferred = 0
        ignored = 0
        failed = []
        for event in events:
            try:
                result = self.workflow_engine.apply_worker_event(event["payload"])
                if result.get("ignored"):
                    ignored += 1
                ok = self.task_store.mark_outbox_delivered(event["eventId"], self.relay_id)
                if ok:
                    delivered += 1
                else:
                    failed.append({"eventId": event["eventId"], "error": "outbox lease was lost before acknowledgement"})
            except IntegrationEventDeferred as exc:
                deferred += 1
                # Operator pause is intentional back-pressure, not a delivery failure.
                self.task_store.defer_outbox(event["eventId"], self.relay_id, str(exc), delay_seconds=2)
            except Exception as exc:
                delay = min(60.0, 2.0 ** min(int(event["deliveryAttempts"]) - 1, 6))
                state = self.task_store.release_outbox(event["eventId"], self.relay_id,
                    f"{type(exc).__name__}: {exc}", delay_seconds=delay,
                    max_delivery_attempts=self.max_delivery_attempts)
                failed.append({"eventId": event["eventId"], "error": f"{type(exc).__name__}: {exc}", "outboxState": state})
        return {"claimed": len(events), "delivered": delivered, "ignored": ignored,
                "deferred": deferred, "failed": failed, "relayId": self.relay_id}

    def drain(self, *, max_batches: int = 20, batch_size: int = 20) -> dict[str, Any]:
        total = {"batches": 0, "claimed": 0, "delivered": 0, "ignored": 0, "deferred": 0, "failed": []}
        for _ in range(max_batches):
            result = self.run_once(limit=batch_size)
            total["batches"] += 1
            for key in ("claimed", "delivered", "ignored", "deferred"):
                total[key] += int(result[key])
            total["failed"].extend(result["failed"])
            if result["claimed"] == 0:
                break
        return total
