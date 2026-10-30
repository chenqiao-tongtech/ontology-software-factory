# S4 下一阶段：多智能体运行时硬化

> 状态：设计与实施验收基线。本文不把拓扑配置校验等同于多 Agent 生产运行。

## 目标

把已有的 Role、Skill、Team、Handoff 契约从“静态可校验”推进到“每次任务执行均受策略约束、可追踪、可复核”。

## 必须落地的运行时不变量

1. **身份与能力分离**：Agent Role 是业务职责声明；实际工具权限由 Policy Runtime 根据主体、任务、租户、环境、风险等级和资源范围计算。模型不得通过提示词或输出字段扩权。
2. **输入冻结**：每个 AgentTask 固定 workflowRunId、taskId、attemptId、roleVersion、skillDigest、ontologySnapshotId/digest、输入 ArtifactRef 和 context manifest。
3. **最小上下文**：只注入任务所需的 approved-shared、task-local 或 restricted-reference-only 内容；秘密只传 secretRef，不传明文。
4. **结构化输出**：输出必须通过角色专属 JSON Schema；未通过时作为 validation_error，不得伪装成业务失败或自动进入下一阶段。
5. **交接可重放**：Handoff 使用不可变引用，带 correlationId、deadline、budget、acceptanceCriteria、failurePolicy 和 idempotencyKey。
6. **独立验证**：生产者与验证者使用不同 task identity；验证对象是冻结候选摘要，不是生产者会话中的可变文件。
7. **预算与停止**：限制最大 hop、并发数、token/tool budget、单任务超时和总运行期限；耗尽后停止或人工升级。

## 建议执行协议

`created → policy_checked → context_built → executing → output_validated → evidence_attached → handoff_accepted`

任何阶段失败均产生带分类的终态或可重试结果。重试必须创建新 attemptId，不得复用旧输出作为新尝试证据。

## 错误分类

| 类别 | 默认处理 | 是否自动重试 |
|---|---|---|
| schema_invalid | 保留校验错误，要求修正输出 | 有界 |
| policy_denied | 拒绝并审计 | 否 |
| context_forbidden | 拒绝并审计 | 否 |
| transient_timeout / rate_limited | 退避重试 | 是，有上限 |
| provider_error | 按错误码分类 | 仅瞬态错误 |
| budget_exceeded | 终止任务 | 否 |
| material_disagreement | 转人工复核 | 否 |
| stale_contract_digest | 终止当前 Run，要求新 Run | 否 |

## 验收测试

- 未授权工具即使由模型明确请求也必须被拒绝。
- role/skill/ontology 任一摘要变化，旧 Run 不得继续执行。
- Agent 输出缺字段、额外字段或类型错误时不得产生 accepted handoff。
- 同一幂等键重复提交只产生一个逻辑任务。
- attempt 过期的迟到结果不得覆盖当前状态。
- 并行验证必须绑定同一 candidateDigest，且任一必需证据缺失时不得汇合为通过。
- 达到 hop、并发、预算或 deadline 上限时能确定性停止。
- Agent 不能批准自己的高风险产物，也不能写入 Workflow 权威状态。

## 交付顺序

1. 为 AgentTask/Handoff/AgentResult 增加显式 attempt 与 contract lock 引用。
2. 将工具授权统一收敛到 policy decision 接口，拒绝由 Agent 自报权限。
3. 将 schema validation、budget accounting 和 stale-result rejection 接入执行边界。
4. 增加独立验证快照与 all-required join 的集成测试。
5. 在控制台展示 task、attempt、handoff、policy decision 和 evidence 关联。

## 非目标

本阶段不承诺多租户 IAM、企业级密钥管理、跨区域调度或高可用 Agent 集群；这些需要独立基础设施与安全评审。
