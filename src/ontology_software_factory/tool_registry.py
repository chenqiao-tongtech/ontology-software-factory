from __future__ import annotations
import json
import hashlib
import inspect
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Callable
from jsonschema import Draft202012Validator

class ToolPolicyError(PermissionError):
    pass


_APPROVAL_DISPATCH_GRANT = object()


def _approval_dispatch_grant() -> object:
    """Internal capability issued only after Harness approval validation."""
    return _APPROVAL_DISPATCH_GRANT


@dataclass(frozen=True)
class ToolInvocationContext:
    run_id: str
    task_id: str
    tool_id: str
    idempotency_key: str | None
    payload_sha256: str

class ToolRegistry:
    """Default-deny in-process tool registry. Tool handlers are injected by trusted code."""
    def __init__(self, root: str | Path, handlers: dict[str, Callable[[dict[str, Any]], Any]]):
        self.root = Path(root).resolve()
        self.tools = json.loads((self.root/'tools/registry.json').read_text(encoding='utf-8'))['tools']
        policy = json.loads((self.root/'policies/tool-permissions.json').read_text(encoding='utf-8'))
        self.policy_version = str(policy.get("policyVersion", "unknown"))
        self.policy_digest = hashlib.sha256(
            json.dumps(policy, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        self.role_policy = policy['roles']
        self.approval_required = set(policy.get('productionToolsRequireApproval', []))
        self.roles = {}
        for p in sorted((self.root/'agents/roles').glob('*.json')):
            obj=json.loads(p.read_text(encoding='utf-8'))
            self.roles[obj['roleId']] = set(obj.get('toolIds', []))
        self.handlers = dict(handlers)
        self.by_id = {t['toolId']: t for t in self.tools}
    def effective_tools(self, role_id: str) -> list[str]:
        if role_id not in self.roles or role_id not in self.role_policy:
            return []
        return sorted(self.roles[role_id] & set(self.role_policy[role_id]) & set(self.handlers) & set(self.by_id))
    def invoke(self, role_id: str, tool_id: str, payload: dict[str, Any], *, _approval_grant: object | None = None,
               run_id: str = "", task_id: str = "", idempotency_key: str | None = None) -> Any:
        if tool_id not in self.effective_tools(role_id):
            raise ToolPolicyError(f'tool {tool_id!r} is not enabled for role {role_id!r}')
        if tool_id in self.approval_required and _approval_grant is not _APPROVAL_DISPATCH_GRANT:
            raise ToolPolicyError(f'tool {tool_id!r} requires an independent approval record')
        definition=self.by_id[tool_id]
        errors=list(Draft202012Validator(definition['inputSchema']).iter_errors(payload))
        if errors:
            raise ValueError(f'invalid tool input: {errors[0].message}')
        # Never permit the caller to select a Python callable or shell command from payload.
        handler = self.handlers[tool_id]
        context = ToolInvocationContext(
            run_id=run_id, task_id=task_id, tool_id=tool_id,
            idempotency_key=idempotency_key,
            payload_sha256=hashlib.sha256(
                json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest(),
        )
        try:
            inspect.signature(handler).bind(payload, context)
        except (TypeError, ValueError):
            return handler(payload)
        return handler(payload, context)
