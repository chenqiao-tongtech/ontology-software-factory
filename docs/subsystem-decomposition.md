# 子系统、模块与组件分解

本文件是第 15 篇的详细设计基线。机器可读清单见 `config/architecture-baseline.json`；两者需要保持一致。

## 分解规则

每个模块必须有单一的主要责任、明确定义的输入输出、依赖方向、可独立验证的验收标准。实现状态采用：

- `implemented`：有实现且本地测试覆盖；仍不自动意味着生产环境验收。
- `partial`：存在参考实现，但关键外部连接、沙箱、真实证据或生产级特性缺失。
- `planned`：有设计但尚未实现。

## 子系统清单

### S1 需求与交互
- Portal/Console：提交请求，展示状态和证据。
- Requirement Intake：解析结构化需求，检查字段和来源。
- Scope Checker：将请求与 MVP/非目标及验收条件比对。

接口：`ProductionRequest -> Requirement + ValidationReport`。

### S2 语义核心与契约
- Ontology Registry：词汇表、类、关系、状态与受控术语。
- Entity Schema：单对象结构校验。
- Semantic Validator：跨对象引用、类型、版本和生命周期不变量校验。
- Contract Versioning：Schema 版本与兼容性策略。

接口：`Entity/Graph -> ValidationResult`。语义核心不得反向依赖 Agent SDK、数据库驱动或单一云厂商。

### S3 资产与产品目录
- Product/Component/Version Catalog。
- Dependency Resolver 与 Compatibility Matrix。
- Customer Config 与 Custom Patch 分层。
- License/Provenance/SBOM metadata。

接口：`Requirement + constraints -> ResolvedAssetSet + evidence refs`。未验证的兼容性必须标记 unknown，而不是 compatible。

### S4 多智能体协作与 Agent 能力（核心子系统）
- **Team Topology Registry**：明确成员角色、协作模式、阶段依赖、并行组、Join 条件、修复循环上限与升级路径。
- **Role Registry**：职责、输入输出、可用/禁止工具与责任边界。
- **Skill Registry**：版本、输入/输出 Schema、前置条件、验收标准、失败语义与回归集。
- **Typed Handoff Contract**：`runId/taskId/attemptId`、发送/接收角色、输入引用、上下文范围、工具白名单、deadline、budget、验收条件和升级策略。
- **Context Loader / Conflict Resolver**：已批准共享、任务局部、受限引用分区；真实工具证据优先，关键分歧升级人工。
- **Agent Runtime Adapter**：可替换 LLM/Agent 框架，输出候选结果，不拥有工作流状态或授权权力。

接口：`TeamTopology + Task + approved context -> Handoff -> CandidateResult/Evidence refs`。Workflow 是确定性协调器；MVP 有界支持顺序交接、并行独立验证、All-required Join 和最多 2 次修复循环。Agent 不决定自身授权，不直接改写 Workflow 状态，不批准自身高风险输出。

### S5 编排与任务管理
- Workflow Definition / DAG。
- State Machine / transition guards。
- Worker queue、租约、重试、取消和暂停恢复。
- Outbox/Inbox、去重、回放、补偿。

接口：`Run/Task/Event -> next state + dispatch command`。状态只由合法转换和可追溯事件驱动。

### S6 工具集成
- Tool Registry：参数 Schema、风险级别、副作用和允许角色。
- MCP stdio / HTTP JSON API adapter。
- Git / CI / Test / Scanner / Artifact adapters。
- Credential interface 和标准错误映射。

接口：`Authorized ToolRequest -> ToolResult`。工具协议不替代授权与业务契约。

### S7 受控执行
- Restricted Runner / Worker。
- 工作区管理、命令白名单、资源/超时限制。
- 日志、退出码、产物和执行摘要采集。
- 未来的容器/微虚机隔离与网络策略。

接口：`ApprovedExecutionSpec -> ExecutionRecord`。不能把“固定命令包装器”声称为完整安全沙箱。

### S8 质量与安全
- 配置/Schema Validator、Unit/Integration Test Runner。
- SAST、SCA、Secrets、License、SBOM 组件。
- Quality/Security Policy Evaluator 与 Gate。
- 风险豁免、复核与审计记录。

接口：`Versioned artifact + actual reports -> GateDecision`。缺证据 = incomplete/block，不允许默认为通过。

### S9 交付与发布
- Bundle Builder、Manifest、Digest。
- SBOM / provenance evidence。
- Approval Record 与 Release Manager。
- Environment Config、Preflight、Health Check、Upgrade/Rollback。

接口：`Gate-passed candidate + approval -> Release/DeliveryRecord`。MVP 只演练本地配置升级/回滚，不连接生产集群。

### S10 观测与生命周期
- Run/Event Ledger、Metrics、Logs。
- Model/Tool/Runner Usage & Cost Ledger。
- Audit Query/Export。
- Ontology/Workflow Change Proposal、评审与回归。

接口：`Events + usage + feedback -> metrics/report/change proposal`。建议不直接变成生产规则更改。

### S11 横切治理
- IAM/Identity Adapter。
- Policy Pack、Approval Service。
- Secret references、tenant boundary、budget/rate limits。
- Security audit 与 break-glass 机制。

接口：`Principal + Action + Resource + Context -> Allow/Deny/RequireApproval`。领域本体只提供语义上下文，不是授权来源。

## 多智能体协作必须拥有的关键对象

`AgentTeam`, `AgentRole`, `Skill`, `AgentTask`, `AgentHandoff`, `AgentResult`, `ContextReference`, `CoordinationDecision`, `ReviewDecision`。这些对象通过 `contracts/schemas/agent-handoff.schema.json` 及后续结果契约实现版本化；其状态由 Workflow/事件账本管理，不依赖某个 Agent 的会话记忆。

## 跨模块关键对象

`Requirement`, `Product`, `Component`, `Version`, `Artifact`, `Build`, `TestRun`, `Vulnerability`, `Release`, `Deployment`, `Incident`, `AgentTask`, `AgentResult`, `WorkflowRun`, `ToolExecution`, `Approval`, `Evidence`, `GateDecision`, `UsageRecord`。

前 11 个是第 16 篇核心语义词汇；后续对象应按实际共享需求进入扩展模型，而非一次全部塞入核心。
