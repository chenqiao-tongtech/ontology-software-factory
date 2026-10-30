# 工作流执行闭环验收清单

## 自动化检查

- [ ] `python -m unittest discover -s tests -v` 全部通过。
- [ ] `workflows/schemas/workflow-run.schema.json` 与 `contracts/schemas/workflow-integration-event.schema.json` 是有效 JSON Schema。
- [ ] Worker 终态成功时，任务状态、任务事件与 Outbox 事件原子提交。
- [ ] Worker 终态失败/死信时产生一次终态 Outbox 事件；`retry_wait` 不产生终态结果事件。
- [ ] Workflow Run、Workflow Event 与 Workflow Inbox 记录在同一个接收端事务提交。
- [ ] 相同 integration event ID 的重复投递不会再次增加 revision。
- [ ] 旧 workflow attempt、非当前 step 的迟到结果不会改变活动状态。
- [ ] 取消的 Workflow Run 不会被 Worker 结果复活；暂停时事件延期而不是确认消费。
- [ ] relay 租约过期后事件可再次被认领；接收端 Inbox 负责重复去重。
- [ ] 当前步骤有 `requiredEvidence` 时，成功结果必须满足证据类型契约。

## 控制台手工验收

1. 启动 `python scripts/run_integrated_console.py --host 127.0.0.1 --port 8767`。
2. 创建一条 Workflow Run。
3. 点击“派发当前节点”，确认 Worker Task 出现在任务列表。
4. 运行一次 Worker；确认 Task 进入终态，Outbox 中出现待投递事件。
5. 点击 Relay 或 Drain，确认 Outbox 变成 delivered，Workflow 节点推进，执行证据可见。
6. 在 Outbox 列表重放已确认事件，确认 Run revision 不因同一 eventId 重复增加。
7. 查看健康卡片和事件账本，确认错误可观测。

## 明确不在验收范围内

- 真实 LLM、CI、仓库写入和部署执行。
- 多节点/多区域生产可用性、生产 RBAC、OIDC、CSRF 防护。
- 外部业务副作用 exactly-once。
