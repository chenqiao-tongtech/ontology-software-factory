"""Central Harness services for context minimization, tool authorization, budgets and audit.

This module is a local reference implementation. It is not an enterprise IAM,
distributed policy service, or production secret broker.
"""
from __future__ import annotations

import hashlib
import json
import threading
import time
from uuid import uuid4
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .tool_registry import ToolRegistry, ToolPolicyError, _approval_dispatch_grant, _harness_dispatch_grant


class HarnessDenied(PermissionError):
    """A Harness policy check rejected an operation."""


class HarnessBudgetExceeded(RuntimeError):
    """A run exceeded its configured local execution budget."""


@dataclass(frozen=True)
class HarnessPrincipal:
    principal_id: str
    role_id: str
    tenant_id: str
    project_id: str


@dataclass(frozen=True)
class HarnessBudget:
    max_tool_calls: int = 20
    max_context_bytes: int = 48_000
    max_input_tokens: int = 100_000
    max_output_tokens: int = 40_000
    max_run_tool_calls: int = 500


@dataclass
class _Usage:
    tool_calls: int = 0
    context_bytes: int = 0
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass(frozen=True)
class HarnessContext:
    run_id: str
    task_id: str
    role_id: str
    fields: dict[str, Any]
    evidence_refs: tuple[str, ...]
    context_bytes: int


class HarnessRuntime:
    """Policy-aware façade over ToolRegistry with minimal context and metadata-only audit."""

    def __init__(
        self,
        *,
        project_root: str | Path,
        tool_registry: ToolRegistry,
        audit_path: str | Path,
        budget: HarnessBudget | None = None,
        approval_validator: Callable[[str, str, str], bool] | None = None,
        kill_switch_path: str | Path | None = None,
        usage_store: Any | None = None,
        approval_store: Any | None = None,
        policy_version: str = "unknown",
        policy_digest: str = "unknown",
    ):
        self.root = Path(project_root).resolve()
        self.tool_registry = tool_registry
        self.audit_path = Path(audit_path).resolve()
        self.budget = budget or HarnessBudget()
        self.approval_validator = approval_validator or (lambda _ref, _run, _tool: False)
        self.kill_switch_path = Path(kill_switch_path).resolve() if kill_switch_path else None
        self.usage_store = usage_store
        self.approval_store = approval_store
        self.policy_version = str(policy_version)
        self.policy_digest = str(policy_digest)
        self._usage: dict[str, _Usage] = {}
        self._lock = threading.RLock()
        self._tool_defs = {item["toolId"]: item for item in json.loads(
            (self.root / "tools/registry.json").read_text(encoding="utf-8")
        )["tools"]}
        self._roles = {
            item["roleId"]: item for item in (
                json.loads(path.read_text(encoding="utf-8"))
                for path in sorted((self.root / "agents/roles").glob("*.json"))
            )
        }
        self._context_policy = json.loads(
            (self.root / "policies/context-policy.json").read_text(encoding="utf-8")
        )

    def _usage_for(self, run_id: str) -> _Usage:
        return self._usage.setdefault(run_id, _Usage())

    def record_lifecycle_event(
        self, *, run_id: str, task_id: str, event_type: str,
        principal: HarnessPrincipal, metadata: dict[str, Any] | None = None,
        status: str = "recorded",
    ) -> dict[str, Any]:
        """Append a metadata-only lifecycle event to the same audit stream as tool calls.

        Payloads, prompts, model outputs and secret values are deliberately excluded.
        """
        if not run_id or not task_id or not principal.principal_id:
            raise HarnessDenied("principal, run_id and task_id are required")
        safe_metadata = {
            str(key): value for key, value in (metadata or {}).items()
            if key in {
                "workflowId", "workflowVersion", "ontologySnapshotId",
                "ontologyDigest", "runtimeContractLockDigest", "model",
                "provider", "latencyMs", "errorType", "toolCount",
            }
            and isinstance(value, (str, int, float, bool, type(None)))
        }
        event = {
            "occurredAt": datetime.now(timezone.utc).isoformat(),
            "eventType": str(event_type),
            "runId": run_id, "taskId": task_id,
            "principalId": principal.principal_id, "roleId": principal.role_id,
            "tenantId": principal.tenant_id, "projectId": principal.project_id,
            "policyVersion": self.policy_version, "policyDigest": self.policy_digest,
            "status": status, "metadata": safe_metadata,
        }
        self.audit_path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n"
        with self._lock:
            with self.audit_path.open("a", encoding="utf-8") as handle:
                handle.write(line)
                handle.flush()
        return event

    def usage(self, run_id: str) -> dict[str, int]:
        if self.usage_store is not None:
            return self.usage_store.get_harness_usage(run_id)
        with self._lock:
            value = self._usage_for(run_id)
            return {
                "toolCalls": value.tool_calls,
                "contextBytes": value.context_bytes,
                "inputTokens": value.input_tokens,
                "outputTokens": value.output_tokens,
            }

    def _record_usage(
        self, *, run_id: str, task_id: str, event_type: str,
        tool_calls: int = 0, context_bytes: int = 0,
        input_tokens: int = 0, output_tokens: int = 0,
        provider: str | None = None, model: str | None = None,
        tool_id: str | None = None, status: str = "recorded",
        metadata: dict[str, Any] | None = None,
        limits: dict[str, int] | None = None, enforce_limits: bool = False,
    ) -> dict[str, Any]:
        if self.usage_store is None:
            return {"allowed": True, "usage": self.usage(run_id)}
        return self.usage_store.record_harness_usage(
            event_id=f"harness:{uuid4().hex}", run_id=run_id, task_id=task_id,
            event_type=event_type, policy_version=self.policy_version,
            policy_digest=self.policy_digest, occurred_at=datetime.now(timezone.utc).isoformat(),
            tool_calls=tool_calls, context_bytes=context_bytes,
            input_tokens=input_tokens, output_tokens=output_tokens,
            provider=provider, model=model, tool_id=tool_id, status=status,
            metadata=metadata, limits=limits, enforce_limits=enforce_limits,
        )

    def assert_model_budget_available(self, run_id: str) -> None:
        current = self.usage(run_id)
        if current["inputTokens"] >= self.budget.max_input_tokens:
            raise HarnessBudgetExceeded("run input token budget is exhausted")
        if current["outputTokens"] >= self.budget.max_output_tokens:
            raise HarnessBudgetExceeded("run output token budget is exhausted")

    def record_model_usage(
        self, run_id: str, *, input_tokens: int = 0, output_tokens: int = 0,
        task_id: str = "unknown-task", provider: str | None = None,
        model: str | None = None, response_id: str | None = None,
        latency_ms: int | None = None,
    ) -> None:
        if input_tokens < 0 or output_tokens < 0:
            raise ValueError("token usage must be non-negative")
        if self.usage_store is not None:
            recorded = self._record_usage(
                run_id=run_id, task_id=task_id, event_type="model.usage",
                input_tokens=input_tokens, output_tokens=output_tokens,
                provider=provider, model=model,
                metadata={"responseId": response_id, "latencyMs": latency_ms},
                limits={"inputTokens": self.budget.max_input_tokens,
                        "outputTokens": self.budget.max_output_tokens},
                enforce_limits=False,
            )
            usage = recorded.get("usage", {})
            if usage.get("inputTokens", 0) > self.budget.max_input_tokens:
                raise HarnessBudgetExceeded("run input token budget exceeded after recording actual usage")
            if usage.get("outputTokens", 0) > self.budget.max_output_tokens:
                raise HarnessBudgetExceeded("run output token budget exceeded after recording actual usage")
            return
        with self._lock:
            value = self._usage_for(run_id)
            if value.input_tokens + input_tokens > self.budget.max_input_tokens:
                raise HarnessBudgetExceeded("input token budget exceeded")
            if value.output_tokens + output_tokens > self.budget.max_output_tokens:
                raise HarnessBudgetExceeded("output token budget exceeded")
            value.input_tokens += input_tokens
            value.output_tokens += output_tokens

    def assemble_context(
        self,
        principal: HarnessPrincipal,
        *,
        run_id: str,
        task_id: str,
        shared: dict[str, Any],
        task_local: dict[str, Any] | None = None,
        evidence_refs: list[str] | None = None,
    ) -> HarnessContext:
        role = self._roles.get(principal.role_id)
        if role is None:
            raise HarnessDenied("unknown role")
        role_context = role.get("contextPolicy", {})
        shared_allowed = set(role_context.get("sharedContextFields", []))
        local_allowed = set(role_context.get("taskLocalContextFields", []))
        restricted = set(role_context.get("restrictedContextFields", []))
        shared_input = dict(shared or {})
        if shared_input.get("tenant_id") != principal.tenant_id:
            raise HarnessDenied("shared context tenant does not match principal tenant")
        if shared_input.get("project_id") not in (None, principal.project_id):
            raise HarnessDenied("shared context project does not match principal project")
        fields = {key: value for key, value in shared_input.items()
                  if key in shared_allowed and key not in restricted}
        for key, value in (task_local or {}).items():
            if key in restricted:
                raise HarnessDenied(f"restricted context field rejected: {key}")
            if key in local_allowed:
                fields[key] = value
        refs = tuple(sorted(set(str(item) for item in (evidence_refs or []) if str(item))))
        payload = json.dumps({"fields": fields, "evidenceRefs": refs}, ensure_ascii=False, sort_keys=True)
        size = len(payload.encode("utf-8"))
        if size > self.budget.max_context_bytes:
            raise HarnessBudgetExceeded("assembled context exceeds byte budget")
        if self.usage_store is not None:
            recorded = self._record_usage(
                run_id=run_id, task_id=task_id, event_type="context.assembled",
                context_bytes=size, limits={"contextBytes": self.budget.max_context_bytes},
                enforce_limits=True, metadata={"roleId": principal.role_id},
            )
            if not recorded.get("allowed"):
                raise HarnessBudgetExceeded("run context byte budget exceeded")
        else:
            with self._lock:
                usage = self._usage_for(run_id)
                if usage.context_bytes + size > self.budget.max_context_bytes:
                    raise HarnessBudgetExceeded("run context byte budget exceeded")
                usage.context_bytes += size
        return HarnessContext(run_id, task_id, principal.role_id, fields, refs, size)

    def invoke_tool(
        self,
        principal: HarnessPrincipal,
        *,
        run_id: str,
        task_id: str,
        tool_id: str,
        payload: dict[str, Any],
        approval_ref: str | None = None,
        idempotency_key: str | None = None,
    ) -> Any:
        started = time.monotonic()
        status = "denied"
        result: Any = None
        approved = False
        try:
            if self.kill_switch_path and self.kill_switch_path.exists():
                raise HarnessDenied("Harness kill switch is active")
            if not run_id or not task_id or not principal.principal_id:
                raise HarnessDenied("principal, run_id and task_id are required")
            definition = self._tool_defs.get(tool_id)
            if definition is None:
                raise HarnessDenied(f"unknown tool: {tool_id}")
            if definition.get("approvalRequired") is True:
                if approval_ref and self.approval_store is not None:
                    try:
                        self.approval_store.consume(
                            approval_ref, run_id=run_id, task_id=task_id,
                            tenant_id=principal.tenant_id, tool_id=tool_id,
                            payload=payload, executor=principal.principal_id,
                        )
                        approved = True
                    except PermissionError as exc:
                        raise HarnessDenied(str(exc)) from exc
                else:
                    # Compatibility path for older integrations. New high-impact
                    # integrations should inject ApprovalStore and use its bound records.
                    approved = bool(
                        approval_ref
                        and self.approval_validator(approval_ref, run_id, tool_id)
                    )
                if not approved:
                    raise HarnessDenied("valid independent approval record is required")
            # Persistent stores perform the budget check and counter increment atomically,
            # and retain a budget_exceeded event for audit. A read-then-write check here
            # would race across HarnessRuntime instances.
            if self.usage_store is not None:
                recorded = self._record_usage(
                    run_id=run_id, task_id=task_id, event_type="tool.invoked",
                    tool_calls=1, tool_id=tool_id,
                    limits={"toolCalls": min(self.budget.max_tool_calls, self.budget.max_run_tool_calls)},
                    enforce_limits=True, metadata={"roleId": principal.role_id},
                )
                if not recorded.get("allowed"):
                    status = "budget_exceeded"
                    raise HarnessBudgetExceeded("Agent/Run tool call budget exceeded")
            else:
                with self._lock:
                    usage = self._usage_for(run_id)
                    if usage.tool_calls >= min(self.budget.max_tool_calls, self.budget.max_run_tool_calls):
                        status = "budget_exceeded"
                        raise HarnessBudgetExceeded("Agent/Run tool call budget exceeded")
                    usage.tool_calls += 1
            result = self.tool_registry.invoke(
                principal.role_id, tool_id, payload,
                _approval_grant=_approval_dispatch_grant() if approved else None,
                run_id=run_id, task_id=task_id, idempotency_key=idempotency_key,
                _harness_grant=_harness_dispatch_grant(),
            )
            status = "succeeded"
            return result
        except HarnessBudgetExceeded:
            status = "budget_exceeded"
            raise
        except (HarnessDenied, ToolPolicyError, PermissionError, ValueError):
            status = "denied"
            raise
        except Exception:
            status = "failed"
            raise
        finally:
            elapsed_ms = int((time.monotonic() - started) * 1000)
            result_digest = None
            if result is not None:
                try:
                    encoded = json.dumps(result, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
                    result_digest = hashlib.sha256(encoded).hexdigest()
                except (TypeError, ValueError):
                    result_digest = "unavailable"
            event = {
                "occurredAt": datetime.now(timezone.utc).isoformat(),
                "runId": run_id,
                "taskId": task_id,
                "principalId": principal.principal_id,
                "roleId": principal.role_id,
                "toolId": tool_id,
                "policyVersion": self.policy_version,
                "policyDigest": self.policy_digest,
                "status": status,
                "approvalRef": approval_ref if approved else None,
                "durationMs": elapsed_ms,
                "resultSha256": result_digest,
            }
            self.audit_path.parent.mkdir(parents=True, exist_ok=True)
            line = json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n"
            with self._lock:
                with self.audit_path.open("a", encoding="utf-8") as handle:
                    handle.write(line)
                    handle.flush()
