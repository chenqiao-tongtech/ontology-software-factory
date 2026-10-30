# Skill: 事件分诊与 Runbook 草案 (`incident-triage-runbook`)

**Version:** 1.0.0  
**Compatible roles:** ops-support  
**Human review required:** Yes

## Purpose

根据监控、部署和事件记录形成可追溯的分诊摘要和处置建议。

## Inputs

- `Product`
- `Component`
- `Version`
- `Artifact`
- `Deployment`
- `Incident`

## Required tools

- `catalog.read`
- `documents.read`
- `monitoring.read`
- `incident.read`
- `runbook.propose`
- `contract.validate`

## Operating rules

- 日志和告警先脱敏，限制上下文时间窗。
- 不读取未授权租户或不相关的个人数据。

## Acceptance criteria

- [ ] 按事实、假设和建议区分记录证据。
- [ ] 每项高风险操作包含前置检查、验证步骤和回退方案。
- [ ] 产物是建议/Runbook 草案，不直接触发生产命令。

## Stop / escalation conditions

- 时间窗口、部署 ID 或监控来源不明确。
- 处置需要执行生产重启、流量切换或恢复数据。

## Side-effect boundary

仅产生事件分析与 Runbook 草案，不执行生产操作。

> This file documents a reusable capability. It is not itself an authorization mechanism. Tool permissions are enforced by the runtime/policy layer, and every result must be validated against the corresponding output contract.
