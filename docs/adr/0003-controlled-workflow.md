# ADR-0003：生产顺序由显式工作流控制，Agent 不自行决定发布状态

- 状态：Accepted（本系列参考实现的设计决定）
- 日期：2026-10-27

## 背景

多个 Agent 可能对任务完成条件、重试或发布时机形成不同判断。自然语言对话不能替代一致的状态机和可验证证据。

## 决策

将 Agent 当作受控工作流节点。每个节点有明确输入、输出、可调用工具、错误语义和完成条件。发布状态只由工作流控制器根据真实工具结果、策略校验和授权记录决定。

## 安全约束

- 默认最小权限，读写职责分离。
- 构建与测试在隔离执行环境完成。
- 高影响操作需要人工审批。
- 设定最大循环/重试次数、超时和成本上限。
- 外部文档、工具输出和 Agent 消息均视为不可信输入，需结构验证。

这些约束与 OWASP Agent Security Cheat Sheet 中的最小权限、输入验证、人工介入、会话隔离和执行限制建议一致：[OWASP AI Agent Security](https://cheatsheetseries.owasp.org/cheatsheets/AI_Agent_Security_Cheat_Sheet.html)。
