# 多智能体协作架构验收清单（MVP）

- [ ] AGENT-01：团队拓扑中的每个角色均存在于 `agents/roles/`，未知角色被拒绝。
- [ ] 协调控制器是确定性 Workflow/State Machine，不以 LLM 对话作为权威状态。
- [ ] AGENT-02：Agent 交接通过 `contracts/schemas/agent-handoff.schema.json`，包含输入引用、上下文范围、工具、期限、预算与验收条件。
- [ ] AGENT-03：测试与安全审查针对同一冻结候选快照独立执行，并按 all-required 规则汇合。
- [ ] AGENT-05：生成 Agent 不能批准自己的高风险结果；Agent 不能直接变更 Workflow 状态或为自己增加工具权限。
- [ ] AGENT-04：修复循环、Agent 跳数、并行任务数、模型/工具预算和超时均有上限。
- [ ] 关键分歧、重试上限耗尽、审批拒绝或过期时转人工复核/终止。
- [ ] 真实工具证据、候选制品摘要和最终 GateDecision 可以通过 runId/taskId/correlationId 关联。

校验命令：

```bash
python scripts/validate_multi_agent_architecture.py
python -m unittest tests.test_multi_agent_architecture -v
```

这些检查验证拓扑与交接契约的本地一致性，不代表真实 Agent SDK、企业 IAM 或外部执行系统已完成集成。
