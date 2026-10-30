# S5 下一阶段：确定性 Workflow 与 State Machine

> 状态：设计与实施验收基线。现有引擎已具备 DAG 定义校验、持久化状态、Worker 事件投影、幂等去重等基础；本文规定并行汇合与恢复语义的下一步验收口径。

## 权威边界

Workflow Store 是运行状态唯一权威来源。Agent、Worker、UI 和外部事件只能提交命令/结果，不能直接修改运行状态。所有状态变更必须由引擎校验前置条件后，在同一事务中写入状态和事件。

## 目标状态模型

Run：`queued | running | waiting_approval | paused | succeeded | failed | cancelled`

Step：`pending | ready | queued | running | waiting_approval | retry_wait | succeeded | failed | skipped | cancelled`

每个 Step 至少记录：stepId、attempt、maxAttempts、dependsOn、requiredEvidence、idempotencyKey、lease/timeout、startedAt、finishedAt、resultRef、errorClass。

## 调度规则

1. 创建 Run 后，将所有依赖已满足的步骤置为 ready；不假设只有一个 currentStep。
2. Worker 领取任务时进行原子 claim，并写入 leaseOwner、leaseExpiresAt 和 attempt。
3. 依赖全部成功才可调度下游；任一必需依赖失败时按显式 failurePolicy 传播失败或进入补偿。
4. 并行分支必须显式声明 joinPolicy：`all_required`、`any_success` 或 `quorum`。发布、安全等门禁默认只能使用 all_required。
5. 重试只针对 allowlist 中的 transient error class；达到 maxAttempts 后进入失败路径，不允许无限重试。
6. 人工审批是独立 Step，审批记录绑定 candidateDigest、policyVersion、approver、decision、reason、createdAt 和 expiry。
7. 暂停时不丢弃已完成结果；恢复后先核验运行合同摘要和租约，再继续派发。
8. 取消需要停止未领取任务、标记在途任务取消请求，并记录无法撤销的外部副作用。
9. 补偿是新的显式工作流动作，不等同于数据库回滚；每个外部副作用必须声明补偿能力和不可补偿风险。

## 事件协议

事件至少包含 eventId、eventType、aggregateId、aggregateRevision、occurredAt、correlationId、causationId、actor、payloadSchemaVersion。消费者必须幂等；旧 revision、错误 attempt、已取消 Run 的迟到事件不得推进状态。

建议事件：`run.created`、`step.ready`、`task.claimed`、`step.started`、`step.succeeded`、`step.retry_scheduled`、`step.failed`、`approval.requested`、`approval.decided`、`run.paused`、`run.resumed`、`run.cancelled`。

## 验收测试

- DAG 环、未知依赖、重复 Step ID 均在 Run 创建前拒绝。
- 两个无依赖步骤可同时 ready；all_required join 在全部分支成功前不得放行。
- 两个 Worker 竞争同一任务时最多一个 claim 成功。
- lease 过期后可重新领取，旧 attempt 的迟到结果被忽略。
- 重复 eventId 不重复推进；同一事件的并发消费只有一次生效。
- 暂停期间到达的结果事件被安全延期，恢复后可继续投影。
- 审批绑定的 candidateDigest 与当前候选不一致时拒绝。
- 重试次数耗尽、取消、补偿失败均有明确终态和审计事件。
- 崩溃恢复后状态可由持久化记录恢复，不依赖内存队列。

## 实施切片

A. 引入 Step readiness 与多任务调度接口，同时保持旧串行定义兼容。  
B. 增加 joinPolicy 与 all-required 集成测试。  
C. 引入 lease/heartbeat/reclaim 与 attempt fencing。  
D. 将审批、暂停、恢复、取消和补偿统一为命令处理器。  
E. 增加事件版本、revision fencing、重放和故障注入测试。

## 非目标

本阶段不直接承诺 Kafka/RabbitMQ 等外部消息中间件部署；SQLite 仍定位于单机参考实现。生产化需要独立数据库、消息传递、HA 与备份恢复设计。
