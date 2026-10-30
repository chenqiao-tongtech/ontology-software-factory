# ADR 0009：使用事务性 Outbox + Workflow Inbox 连接 Worker 与 Workflow

- 状态：Accepted for the local reference implementation
- 日期：2026-10-27

## 背景

Article 20 的 Worker task store 与 Workflow store 独立持久化。若 Worker 先更新任务、再通过普通函数或 HTTP 通知 Workflow，就会出现状态与通知的双写窗口；反过来，Workflow 消费成功后 Relay 还可能在确认 Outbox 前崩溃，形成重复投递。

## 决策

1. Worker 任务终态、Task Event 和 `integration_outbox` 在任务存储的一个 SQLite 事务中提交。
2. Relay 以租约方式 claim Outbox，接收端完成后才 acknowledge。
3. Workflow Store 在一个事务中提交 Run 更新、Workflow Event 与 `workflow_inbox` 的 `eventId` 去重记录。
4. 事件带 `workflowRunId`、`workflowStepId`、`workflowAttempt`、`taskId`、结果/证据或错误分类。
5. 暂停 Run 的事件延后处理；取消/终态 Run、节点不匹配或旧 attempt 的事件只做审计，不复活状态。
6. Outbox 重放保留原始事件 ID；死信可被观测并人工处理。

## 结果

优点：避免生产者双写丢事件；允许 Relay 崩溃恢复；接收端重复消费不会重复推进 Run；可以对迟到事件进行审计。

代价：需要 Outbox 清理、Inbox 保留、重试/死信监控、事件 schema 兼容和运营流程。此模式是至少一次投递 + 幂等消费，不是端到端 exactly-once。

## 事务边界

任务存储和工作流存储的业务事务仍然相互独立。演示环境使用同一 SQLite 文件只是为了便于本地运行，不代表跨 Store 单事务；实际生产环境应按服务边界部署数据库与消息设施。

## 未解决事项

- 当前控制台和演示 Handler 无身份认证、授权或容器隔离。
- 没有实现多实例 relay leader election 或面向生产的消息代理。
- 业务外部副作用的幂等/对账由未来的执行器适配器负责。
