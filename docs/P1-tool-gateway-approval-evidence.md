# P1 最后三项收尾设计与实施记录

> 日期：2026-10-31  
> 范围：统一 Tool Gateway、独立 Tool Approval、统一 Evidence Contract  
> 实现级别：本地 SQLite 参考实现；生产化仍需共享数据库、可信身份与外部系统适配。

## 1. 本轮目标与边界

本轮将 P1 最后三项从接口设想推进到可测试的持久化实现：

1. Tool Gateway：提供统一工具调用入口，绑定 Run/Task/Tool/参数摘要，完成调用幂等和结果复用。
2. Tool Approval：将高风险工具审批保存为独立记录，绑定调用内容，校验审批人/执行人分离、有效期和一次性消费。
3. Evidence Contract：在任务选择启用版本化证据契约时，将证据绑定到 Run、Task、输入摘要、工具版本、退出码和报告摘要。

这里的“统一”指新接入的 Agent 工具和适配器应经 Gateway；不意味着仓库内所有脚本、Portal 路由或任意第三方 MCP Server 已自动迁移。旧代码仍可能直接调用 ToolRegistry/Adapter，必须通过后续写路径盘点和适配器迁移逐项收口。

## 2. Tool Gateway

实现：`src/ontology_software_factory/governance.py`

### 2.1 调用流程

```text
Agent / Workflow / Connector Adapter
              |
              v
          ToolGateway
              |
       SQLiteInvocationLedger
       - idempotency key
       - Run / Task / Tool
       - canonical payload SHA-256
       - started / completed / failed
              |
              v
          HarnessRuntime
       - kill switch
       - principal / tenant
       - approval validation
       - budget / audit
              |
              v
          ToolRegistry
       - role & policy intersection
       - JSON Schema
       - trusted handler dispatch
              |
              v
     HTTP / MCP / local / CI adapters
```

### 2.2 幂等语义

- 相同幂等键且绑定信息和参数摘要一致：若已完成，返回缓存 JSON 结果，不重复派发。
- 相同幂等键但 Run/Task/Tool/参数摘要不同：拒绝并抛出 `InvocationError`。
- 状态为 `started` 或 `failed`：拒绝自动再次派发，要求对账/人工确认。进程可能在外部系统完成写入后、写回本地账本前崩溃；自动重试会造成重复副作用。
- 结果必须可 JSON 序列化才能缓存；非 JSON 结果保留 fail-closed 状态，不做不安全重放。

Agent Runtime 已将工具函数回调改为经 ToolGateway，幂等键由 Run、Task、Tool 和规范化参数摘要生成。Gateway 将幂等键继续传入 Harness 和 ToolRegistry；可信 Adapter Handler 可声明第二个参数接收 ToolInvocationContext（Run/Task/Tool/Idempotency Key/Payload Digest），并将该键传给外部服务。单参数 Handler 保持兼容。Harness 仍执行权限、预算、审批和审计；Gateway 不能绕过 Harness。

### 2.3 外部适配器规则

HTTP JSON Adapter 已支持 `Idempotency-Key` 请求头。接入外部写 API 时，可信 Handler 从 ToolInvocationContext 读取幂等键，并传给 `HTTPSJSONAdapter.request_json(..., idempotency_key=...)`；同时确认远端服务确实执行去重。仅发送请求头并不能证明远端支持幂等。

MCP 协议本身没有通用的工具调用幂等语义。MCP Server 必须在其工具 schema/业务 API 中定义幂等键，Adapter 将其映射到服务器端去重机制；若不支持，Gateway 只能提供本地防重复派发和人工对账保护，不能承诺跨系统 exactly-once。

## 3. 独立 Tool Approval

实现：`ApprovalStore`（同文件），由 Harness 在高影响工具调用前消费审批凭证。

记录字段：

| 字段 | 用途 |
|---|---|
| approvalId | 唯一审批记录 |
| runId / taskId / tenantId | 调用范围 |
| toolId | 被批准的工具 |
| payloadSha256 | 规范化参数摘要，参数改变即失效 |
| requestedBy / requestedAt | 申请人和申请时间 |
| expiresAt | 审批有效期 |
| status | pending / approved / rejected / expired |
| decidedBy / decidedAt / reason | 审批人、决策时间和审计理由 |
| consumedAt | 一次性消费时间 |

### 3.1 状态规则

- 申请人不能批准自己的请求。
- 执行人不能与申请人或审批人相同。
- 审批凭证必须匹配 Run、Task、Tenant、Tool 和参数摘要。
- 过期、拒绝、未审批、已消费或绑定不匹配均 fail closed。
- 审批消费通过 SQLite 事务原子完成，阻止同一凭证并发重放。
- ToolRegistry 不再接受简单的 `approval_granted=True` 作为授权凭证；高影响工具必须由 Harness 在审批记录验证后发放内部 dispatch capability。

### 3.2 接入示例

```python
from ontology_software_factory.governance import ApprovalStore
from ontology_software_factory.harness import HarnessRuntime

approval_store = ApprovalStore(".local-runs/governance.sqlite3")
harness = HarnessRuntime(
    project_root=".",
    tool_registry=registry,
    audit_path=".local-runs/harness-audit.jsonl",
    approval_store=approval_store,
)

payload = {"releaseId": "rel-123", "targetEnvironment": "production"}
approval_store.request(
    approval_id="APR-001",
    run_id="run-001",
    task_id="task-001",
    tenant_id="tenant-a",
    tool_id="release.simulation.promote",
    payload=payload,
    requested_by="requester-id",
    ttl_seconds=900,
)
approval_store.decide(
    "APR-001", decision="approved",
    actor="approver-id", reason="Reviewed release evidence",
)
harness.invoke_tool(
    principal, run_id="run-001", task_id="task-001",
    tool_id="release.simulation.promote", payload=payload,
    approval_ref="APR-001",
)
```

> 示例中的 actor ID 必须来自已认证身份系统。当前参考实现只校验传入的 actor 标识和角色分离，不负责认证用户身份、MFA 或授权委派。

## 4. Evidence Contract

实现：`validate_evidence_contract()` 与 `SQLiteTaskStore.complete()`。

任务 payload 可选包含 `evidenceContract`。不配置该字段的旧任务保持兼容；配置后，完成任务时强制验证。

契约字段：

- `contractVersion`
- `runId`
- `taskId`
- `inputSha256`
- `toolVersion`
- `exitCode`
- `reportSha256`

每个 Evidence item 仍必须有 `type`、`uri`、`sha256`，并新增 `provenance` 对象，逐项匹配 Run/Task/Input Digest/Tool Version/Exit Code/Report Digest。

### 4.1 Task ID 绑定

任务入队时允许 `evidenceContract.taskId="$TASK_ID"`，由 Task Store 在生成稳定 Task ID 后替换，避免调用者预先猜测 Task ID。完成时还会验证：

- 契约 Task ID 等于当前 Task ID；
- 如果任务 payload 带有 `runId` 或 `workflowRunId`，契约 Run ID 必须匹配；
- 如果任务 payload 带有 `input`，契约 Input SHA-256 必须等于该输入的规范化 JSON 摘要。

Evidence 仍是来源描述和摘要，不代表系统已经证明远端 URI 内容可取回或内容摘要与远端实际字节一致。生产系统应由 Artifact Store/Attestation 服务完成上传、签名、内容寻址和来源验证。

## 5. 验证

新增 `tests/test_governance.py` 覆盖：

- 申请人自批拒绝；
- 审批凭证参数摘要不匹配拒绝；
- 一次性消费和重放拒绝；
- 审批过期拒绝；
- Harness 高影响工具调用必须提供独立持久化审批；
- Tool Gateway 完成结果复用、参数变化冲突；
- Evidence Contract 的 Task/Run/Input/Tool/Exit/Report 来源绑定。

另更新 Agent Runtime Harness 测试，确认 Agent 工具函数通过 ToolGateway，而不是直接调用 Harness。ToolRegistry 测试确认简单布尔值不能伪造高影响审批。

运行命令：

```bash
python -m unittest discover -s tests -p 'test_governance.py'
python -m unittest discover -s tests -p 'test_agent_runtime_harness.py'
python -m unittest discover -s tests -p 'test_task_runtime.py'
python -m unittest discover -s tests -p 'test_tool_registry.py'
make validate
make test
```

## 6. 尚未完成的企业级工作

- SQLite 适用于单机/单服务参考实现；多节点必须迁移到共享数据库并保证事务隔离、唯一约束和故障恢复。
- actor 字符串并非身份认证。生产环境须从 IAM/SSO 注入不可伪造的身份声明，并实施 RBAC/ABAC、MFA 和审批委派。
- 所有 MCP/HTTP/Portal/CLI/后台任务写入口仍需盘点，逐项迁移到 Gateway；不能仅凭 Agent Runtime 已接入就声称全仓库只有一个写入口。
- 外部系统若不支持幂等键，需要业务侧去重、查询对账、补偿事务或人工处置。
- 审批消费与外部写入不是同一分布式事务。若进程在审批消费后、外部操作前崩溃，审批会被消耗但操作未发生；需引入审批预留/确认状态或由工作流统一编排。
- Evidence URI 目前不自动抓取、校验或签名远端制品；需要 Artifact Store 和签名证明服务。
- 高风险操作仍需审批 UI、审计导出、密钥托管和安全验收。

## 7. P1 收尾判断

本轮实现了三项功能的可运行本地基线和单元/集成测试。P1 是否通过最终验收，仍以最新 head 的 CI 结果为准；全仓库写入口迁移、可信身份接入、分布式事务/对账和生产 Artifact Attestation 是明确的后续生产化任务，不能宣称已完成。
