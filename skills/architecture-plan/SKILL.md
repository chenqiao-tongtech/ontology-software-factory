# Skill: 架构方案与 ADR 草案 (`architecture-plan`)

**Version:** 1.0.0  
**Compatible roles:** solution-architect  
**Human review required:** Yes

## Purpose

根据批准需求、资产目录和非功能约束生成可评审的方案。

## Inputs

- `Requirement`
- `Product`
- `Component`
- `Version`

## Required tools

- `catalog.read`
- `documents.read`
- `workspace.read`
- `architecture.plan.write`
- `contract.validate`

## Operating rules

- 使用获批版本与需求 ID，不复制整库或其他租户资料。
- 把外部资料与架构决策分开并保留来源。

## Acceptance criteria

- [ ] 写明范围、非目标、架构模块和接口边界。
- [ ] 列出假设、替代方案、风险及验证计划。
- [ ] 新依赖引用资产目录或明确标记为未批准候选。

## Stop / escalation conditions

- 目标架构需要未授权的数据边界变化。
- 核心要求与现有资产/约束存在未决冲突。

## Side-effect boundary

只在任务工作区写入方案草稿，不批准架构变更。

> This file documents a reusable capability. It is not itself an authorization mechanism. Tool permissions are enforced by the runtime/policy layer, and every result must be validated against the corresponding output contract.
