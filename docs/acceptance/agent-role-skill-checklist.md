# 第 18 篇验收清单

| ID | 验收标准 | 证据 | 当前说明 |
|---|---|---|---|
| AGT-01 | 七个岗位使用稳定 ID，并定义输入/输出实体、职责和交接要求 | `agents/roles/*.json` | 配置已提供 |
| AGT-02 | Skill 具有版本、兼容角色、工具要求、验收条件与失败条件 | `skills/*/skill.json` 与 `SKILL.md` | 配置已提供 |
| AGT-03 | Role 引用的 Skill 都存在且兼容 | `python scripts/validate_agent_contracts.py` | 自动校验 |
| AGT-04 | Skill 所需工具被当前 Role 明确授权 | Agent contract validator | 自动校验 |
| AGT-05 | 全局禁止工具不会被分配给 Agent | `policies/agent-permissions.json` 与校验器 | 自动校验 |
| AGT-06 | 上下文明确分为共享、局部和受限，秘密不进入模型上下文 | `policies/context-policy.json`、Role definitions | 配置已提供 |
| AGT-07 | Task/Result 满足 JSON Schema，结果状态与证据规则一致 | `contracts/schemas/agent-task.schema.json`、`agent-result.schema.json` | 示例可验证 |
| AGT-08 | 负向测试覆盖权限冲突、未知工具、上下文重叠和人工复核状态 | `tests/test_agent_contracts.py` | 自动化测试 |

> 本篇验收的是配置与契约一致性，不代表已经实现真实 Agent runtime、IAM、工具沙箱或生产审批执行器。
