# S6–S8 下一阶段：工具、Runner 与独立质量验证

> 状态：设计与实施验收基线。现有项目已有工具注册、HTTP/MCP 适配、受控工作区、固定测试/扫描执行和 fail-closed 证据检查；本文规定从本地参考实现走向可审计执行面的下一阶段要求。

## 分层职责

- **Tool Registry（S6）**：登记工具能力、输入/输出 Schema、风险等级、权限范围、版本、超时、幂等性和副作用。
- **Runner / Worker（S7）**：执行固定且可审计的动作；不接受模型生成的任意 shell 命令，不继承不必要的宿主机环境。
- **Evidence / Quality Gate（S8）**：验证真实执行证据、候选摘要、工具版本和策略版本；不以 Agent 自述代替执行结果。

## Tool Contract 最低字段

`toolId, version, description, inputSchema, outputSchema, riskLevel, permissionScope, timeoutSeconds, idempotency, sideEffect, networkPolicy, secretRefs, evidenceTypes, enabled`

工具调用必须记录：toolCallId、runId、taskId、attemptId、principal、policyDecisionId、inputDigest、toolVersion、startedAt、finishedAt、exitCode/status、outputDigest、evidenceRefs。

## Runner 安全要求

1. 默认 deny；工具必须显式注册、启用并通过策略授权。
2. 参数必须先通过 JSON Schema 和业务语义校验。
3. 执行使用固定 argv、`shell=False`、最小环境变量、stdin 关闭、超时与资源限制。
4. 对不可信代码优先使用无网络、只读根文件系统、非 root、capability drop、资源配额的容器/微虚机。
5. 镜像必须按 digest 固定；运行时禁止隐式 pull 或自动切换到较弱执行后端。
6. 工作区、输入、输出与证据目录必须隔离；路径穿越、符号链接逃逸和隐藏路径访问默认拒绝。
7. 外部副作用工具必须具备审批、幂等键、审计和可声明的补偿/回滚策略。
8. MCP/HTTP 适配器只负责协议转换，不自动授予工具权限；远端服务身份、TLS、超时和响应 Schema 仍需验证。

## 质量门禁规则

Gate 输入必须包含 candidateDigest、runId、policyVersion、requiredEvidenceTypes、toolEvidenceRefs。每项证据至少校验：

- 证据类型与 Schema；
- 来源工具身份与版本；
- 绑定的 candidateDigest；
- 执行时间与有效期；
- 退出码和结构化结果；
- 报告文件摘要；
- 是否存在阻断级发现。

状态只允许 `passed | failed | incomplete | not_applicable`。缺证据、摘要不匹配、报告不可解析、扫描器未执行或证据过期均为 incomplete/blocked，不能默认为 passed。质量门禁与人工发布审批是两个独立闸门。

## 推荐证据链

`Requirement → WorkflowRun → AgentTask → ToolCall → RunnerExecution → Evidence → GateDecision → CandidateRelease`

所有对象通过稳定 ID 和 digest 关联。Evidence 应不可变；修复候选后必须生成新 digest 并重新执行受影响的验证。

## 验收测试

- 未注册、禁用或策略拒绝的工具不可执行。
- 错误输入 Schema、超时、非零退出码、缺失报告和报告 JSON 损坏均不得通过。
- 证据绑定旧 candidateDigest 时不得用于新候选。
- 扫描器版本或镜像 digest 未固定时，生产策略不得判定为通过。
- Runner 失败或容器不可用时不得静默退回宿主机。
- 同一幂等键重复请求不会重复产生外部副作用。
- 质量门禁只消费 Evidence，不消费 Agent 自述中的“测试通过”文本。
- Gate PASS 后仍需要独立审批，审批过期或候选摘要变化时必须重新审批。

## 当前边界与生产化前置

本仓库当前控制台是本地开发界面；没有企业 SSO、租户隔离、KMS、不可篡改审计存储或生产级集群调度。扫描范围必须按实际工具报告说明，不得宣称覆盖未扫描的镜像、运行时、云资源或第三方系统。
