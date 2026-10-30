# 工作流执行闭环：Outbox、Relay、Inbox 与状态回写

## 1. 目标与边界

第 18 篇定义 Agent / Skill 契约，第 19 篇定义 Workflow Run 状态机，第 20 篇实现 Worker 任务队列。本篇把三者连接为：

`Workflow Step -> Worker Task -> Task Result + Outbox -> Relay -> Workflow Inbox + Run Update`

当前参考实现面向单机演示，使用 SQLite 和标准库 HTTP 服务。它展示了关键事务边界及故障恢复语义，不等于生产级消息中间件或多节点调度器。演示 Worker 仅注册 `demo.workflow-step`，输出 `demo://` 证据，不执行真实 LLM、CI/CD 或部署。

## 2. 为什么需要 Outbox

任务状态和需要通知工作流的事件如果通过两次独立写入完成，会发生双写故障：任务已成功，但进程在写事件前崩溃；或者事件先发送而任务事务回滚。参考实现把 Worker 任务的终态更新、任务事件账本与 `integration_outbox` 事件写入放进任务存储的同一 SQLite 事务。事务提交后，Relay 才能读取并发送该事件。

Outbox 避免“业务状态已提交、待发送事件却丢失”的双写窗口，但并不承诺只投递一次。Relay 可能在 Workflow 消费成功后、Outbox 确认前崩溃，因此事件可重投。

## 3. Relay 与 Inbox 的幂等处理

- Outbox 事件带稳定的 `eventId`，并保存 `workflowRunId`、`workflowStepId`、`workflowAttempt`、`taskId`、状态与结果/证据。
- Relay 通过租约认领事件，调用 Workflow Engine，并且只在接收端事务成功后确认 Outbox。
- Workflow Store 的 `workflow_inbox.integration_event_id` 是唯一键。工作流 Run 更新、Workflow Event 追加、Inbox 去重记录在同一接收端事务中提交。
- 同一事件重投时，Inbox 判重，避免再次推进节点或重复增加 Run revision。
- 如果工作流已取消、当前节点已变化或 attempt 不匹配，迟到结果作为被忽略的事件记录，不得复活终态 Run 或覆盖新一轮尝试。
- 如果工作流暂停，Relay 延迟重试，不把事件确认为已消费；主动暂停不计入投递失败预算，也不会单独导致死信；恢复后可继续投影。

## 4. 事件生命周期

Outbox 状态为 `pending -> leased -> delivered`；短暂错误可以 `leased -> pending` 并安排下一次可投递时间；达到最大投递次数进入 `dead_letter`，需告警、排查或人工重放。Outbox 重放保留原始 `eventId`，所以接收端 Inbox 仍可去重。

工作流 Step 结果由 `workflowAttempt` 和当前 Step 状态进行 fencing。每次 workflow retry 会增加 workflow attempt；旧 attempt 的迟到事件不会完成新 attempt。Worker Task 的 `attempt` 与 Workflow Step 的 `workflowAttempt` 是不同概念：前者是同一个任务的运行尝试，后者是工作流业务步骤的一轮尝试。

## 5. 事务边界

本地演示使用一个 SQLite 文件，但 task store 和 workflow store 各自管理连接与事务；它们不是一个跨 Store 的分布式事务。闭环靠两个本地事务与可靠重试实现：

1. **生产者事务**：Worker 终态 + Task Event + Outbox Event 原子提交。
2. **消费者事务**：Workflow Run + Workflow Event + Inbox 记录原子提交。
3. **两事务之间**：Relay 至少一次投递；Inbox 提供幂等效果。

“两个 Store 共用同一个 SQLite 文件”只是本地演示的方便，不应误认为两个独立数据库已具备单个原子事务。生产环境可以让两个服务独立存储，通过 Outbox Relay、消息代理和 Inbox/业务去重实现同样的协议。

## 6. 运行与验证

```bash
python -m unittest discover -s tests -v
python scripts/run_integrated_console.py --host 127.0.0.1 --port 8767
```

打开 `http://127.0.0.1:8767`：创建 Run -> 派发当前 Step -> 运行一个 Worker -> Relay 一次或 Drain Outbox -> 查看 Workflow Run、Task、Outbox、Inbox 事件。默认数据库位置是 `data/integrated-console/software_factory.sqlite3`。测试应优先使用临时数据库；不要把运行数据库加入 Git。

## 7. 故障矩阵

| 故障点 | 可能现象 | 恢复机制 |
|---|---|---|
| Worker 在提交任务事务前崩溃 | 任务仍可被租约恢复/重试 | Worker lease 与任务恢复 |
| Worker 提交终态事务后崩溃 | Task 与 Outbox 都存在 | Relay 后续继续投递 |
| Relay 在 Workflow 消费前崩溃 | Outbox 租约过期 | 其他 Relay 重新认领 |
| Workflow Inbox/Run 事务提交前崩溃 | 消费未提交 | Outbox 重投，重新处理 |
| Workflow Inbox/Run 事务提交后、Outbox 确认前崩溃 | 事件可能再次投递 | Inbox 按 `eventId` 去重 |
| 旧 attempt 的结果迟到 | 不应覆盖当前新 attempt | attempt + current-step fencing |
| Run 已取消时结果迟到 | 终态不能被 Worker 结果复活 | 记为 ignored integration event |
| Relay 超过最大交付次数 | Outbox 进入 dead letter | 告警、分析、人工重放或修复后重投 |

## 8. 生产化补齐清单

- 使用受支持的关系数据库/消息代理，制定迁移、备份、保留与分区策略。
- 对 Relay 加分布式 leader/竞争租约策略、吞吐控制、指标、死信告警和运营工具。
- 对外部副作用（合并代码、创建云资源、发布部署）使用独立业务幂等键、第三方幂等能力或对账流程。不能靠消息 Inbox 使远端副作用自动 exactly-once。
- 对消息签名/权限、租户边界、敏感数据、数据保留和密钥进行治理。
- 加入 schema 兼容策略、版本化事件、trace/correlation ID、成本账单和审计留痕。
- 将 worker handler 运行在具备 CPU/内存/时间配额的受限子进程或容器中；本地演示没有生产安全隔离。

## 9. 参考资料

- AWS Prescriptive Guidance, Transactional outbox pattern: https://docs.aws.amazon.com/prescriptive-guidance/latest/cloud-design-patterns/transactional-outbox.html
- microservices.io, Transactional outbox: https://microservices.io/patterns/data/transactional-outbox.html

## 10. 示例事件与契约检查

- `examples/workflow-integration/worker-success-event.json` 展示成功事件的结果与证据结构。
- `examples/workflow-integration/worker-failure-event.json` 展示终态失败事件的错误字段。
- `contracts/schemas/workflow-integration-event.schema.json` 对事件 envelope 做结构校验；证据是否满足当前 Step 要求，仍由 Workflow Engine 的业务契约检查负责。


## Internal artifact side effects

`artifact-write` represents a write under the workflow run's isolated artifact root. It is not a permission to modify the checked-out repository, execute generated files, merge a branch, or deploy. The workflow schema keeps it distinct from `repository-write` and `external`.
