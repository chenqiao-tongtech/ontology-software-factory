# Skill: 候选发布就绪度检查 (`release-readiness-check`)

**Version:** 1.0.0  
**Compatible roles:** release-coordinator  
**Human review required:** Yes

## Purpose

检查测试、安全、版本、兼容性和制品证据是否齐全，并形成审批请求。

## Inputs

- `Product`
- `Component`
- `Version`
- `Artifact`
- `Build`
- `TestRun`
- `Vulnerability`
- `Release`

## Required tools

- `catalog.read`
- `artifacts.read`
- `release.manifest.write`
- `approval.request`
- `contract.validate`

## Operating rules

- 只读取当前发布所需证据和授权范围内的资产。
- 不把上游 Agent 的总结当作原始执行事实。

## Acceptance criteria

- [ ] 清单引用精确版本、制品摘要和所有必需证据。
- [ ] 缺失或过期证据被列为 blocker。
- [ ] 审批请求由独立主体决定，Agent 不执行批准或部署。

## Stop / escalation conditions

- 测试或安全证据缺失、过期或不匹配当前制品。
- 发现未解决的关键门禁失败。

## Side-effect boundary

只生成候选清单并请求审批；不发布、不合并、不部署。

> This file documents a reusable capability. It is not itself an authorization mechanism. Tool permissions are enforced by the runtime/policy layer, and every result must be validated against the corresponding output contract.
