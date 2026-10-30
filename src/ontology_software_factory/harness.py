"""Central Harness services for context minimization, tool authorization, budgets and audit.

This module is a local reference implementation. It is not an enterprise IAM,
distributed policy service, or production secret broker.
"""
from __future__ import annotations

import hashlib
import json
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .tool_registry import ToolRegistry, ToolPolicyError


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
    ):
        self.root = Path(project_root).resolve()
        self.tool_registry = tool_registry
        self.audit_path = Path(audit_path).resolve()
        self.budget = budget or HarnessBudget()
        self.approval_validator = approval_validator or (lambda _ref, _run, _tool: False)
        self.kill_switch_path = Path(kill_switch_path).resolve() if kill_switch_path else None
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

    def usage(self, run_id: str) -> dict[str, int]:
        with self._lock:
            value = self._usage_for(run_id)
            return {
                "toolCalls": value.tool_calls,
                "contextBytes": value.context_bytes,
                "inputTokens": value.input_tokens,
                "outputTokens": value.output_tokens,
            }

    def record_model_usage(self, run_id: str, *, input_tokens: int = 0, output_tokens: int = 0) -> None:
        if input_tokens < 0 or output_tokens < 0:
            raise ValueError("token usage must be non-negative")
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
    ) -> Any:
        if self.kill_switch_path and self.kill_switch_path.exists():
            raise HarnessDenied("Harness kill switch is active")
        if not run_id or not task_id or not principal.principal_id:
            raise HarnessDenied("principal, run_id and task_id are required")
        definition = self._tool_defs.get(tool_id)
        if definition is None:
            raise HarnessDenied(f"unknown tool: {tool_id}")
        approved = False
        if definition.get("approvalRequired") is True:
            approved = bool(
                approval_ref
                and self.approval_validator(approval_ref, run_id, tool_id)
            )
            if not approved:
                raise HarnessDenied("valid independent approval record is required")
        with self._lock:
            usage = self._usage_for(run_id)
            if usage.tool_calls >= self.budget.max_tool_calls:
                raise HarnessBudgetExceeded("tool call budget exceeded")
            usage.tool_calls += 1
        started = time.monotonic()
        status = "succeeded"
        result: Any = None
        try:
            result = self.tool_registry.invoke(
                principal.role_id, tool_id, payload, approval_granted=approved
            )
            return result
        except Exception as exc:
            status = "denied" if isinstance(exc, (PermissionError, ValueError)) else "failed"
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
                "tenantId": principal.tenant_id,
                "toolId": tool_id,
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
