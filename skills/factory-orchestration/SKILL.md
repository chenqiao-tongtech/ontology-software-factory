# Skill: 软件工厂生产计划编排 (`factory-orchestration`)

**Version:** 1.0.0  
**Compatible role:** `factory-orchestrator`  
**Human review:** Required

## Purpose

将已批准的软件需求转化为有界的多阶段 Agent 计划，并提交确定性 Workflow Engine 校验。

## Inputs

- `Requirement`
- `Product`
- `Component`
- `Artifact`

## Output

- `AgentPlan`
- `Artifact`（计划说明和风险摘要）

结构化计划必须符合 `contracts/schemas/factory-orchestrator-plan.schema.json`。

## Planning rules

1. 先核对需求基线、验收条件、项目边界和本体快照。
2. 将目标拆分为有依赖关系的阶段；仅在输入和产出契约允许时并行。
3. 每项分配必须引用已注册的 Role 和该 Role 声明的 Skill。
4. 为每项任务定义输入引用、输出类型和机器可验证的验收条件。
5. 声明预算、最大并发、重试和升级人工处理的条件。
6. 对不确定事实标记假设或待澄清，不得补造业务事实。

## Prohibited behavior

- 不直接派发任务或改变 Workflow 状态。
- 不授予、扩展或绕过工具权限。
- 不批准自身计划或高风险操作。
- 不发布本体、不合并受保护分支、不部署生产环境。
- 不把计划生成描述为任务已经执行。

## Handoff

Workflow Engine 必须重新校验计划 Schema、Role/Skill 兼容性、依赖关系、预算、权限和审批条件，然后才能创建 Workflow Step/Task。Skill 指令不是权限机制；运行时策略仍然是唯一工具授权来源。