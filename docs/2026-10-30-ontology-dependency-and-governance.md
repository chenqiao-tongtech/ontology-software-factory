# 本体依赖图、兼容性门禁与受控版本治理

本轮把上一轮的内容摘要快照扩展为一个本地参考级的本体治理闭环：**显式引用 → 消费者依赖图 → 变更影响分析 → 兼容性评估 → 独立审批 → 版本目录发布/回退**。

## 1. 显式消费者引用

`ontology/consumer-reference-map.json` 定义从仓库哪些配置字段读取引用：

- Agent Role：`inputEntityTypes`、`outputEntityTypes`、`skillIds`、`toolIds`
- Skill：`inputEntityTypes`、`outputEntityTypes`、`compatibleRoleIds`、`requiredToolIds`
- Workflow：每个 Step 的 `roleId`、`skillId`
- Tool：`agents/tool-catalog.json` 中的工具 ID
- Agent Task / Result Contract：JSON Schema 中与正式本体类名完全匹配的 `enum` 值

这里使用仓库已有的结构化类型字段，不从 Role/Skill 的自然语言描述猜测语义。引用映射定义字段契约，消费者数据仍以各个实际配置文件为准。

CI 新增 `make ontology-consumers`，检查类引用、Role/Skill/Tool 引用和 Workflow Step 引用是否可解析。完整 `make validate` 已纳入这项校验。

## 2. 消费者依赖图与影响分析

新增 `GET /api/ontology/dependencies`。

图节点包含：

- 正式本体类
- Agent Role
- Skill
- Workflow 与 Workflow Step
- Tool Contract
- Agent Task / Result JSON Contract
- 人工审批角色

图边表达实体类型消费、Role 使用 Skill/Tool、Skill 兼容 Role/需要 Tool、Workflow Step 派发 Role/调用 Skill、Contract 约束实体类型等关系。

按类查询下游影响：

```text
GET /api/ontology/dependencies?classes=Requirement,Artifact
```

快照差异接口 `GET /api/ontology/diff?from=...&to=...` 也返回消费者影响闭包。闭包沿依赖图双向遍历，以保守地找出需要复核的关联消费者；它表示“需要评估”，不表示该 Agent 在运行时一定会失败。

## 3. 兼容性检查

新增 `GET /api/ontology/compatibility?from=...&to=...`。当前采取保守规则：

| 变化 | 判定 |
|---|---|
| 新增类 / 新增关系 | 默认兼容，但需评审 |
| 删除类 / 删除关系 | 破坏性变化 |
| 修改关系 source、target、field、cardinality | 破坏性变化 |
| 删除受控词汇值或词汇集 | 破坏性变化 |
| 删除既有 MVP 不变量 | 破坏性变化 |
| 新增受控词汇值 / 新增不变量 | 需评审，默认兼容 |
| 说明文字或非结构元数据修改 | 需评审 |

破坏性变更要求本体业务版本主版本递增；版本号不能倒退。兼容性检查是规则化的静态门禁，不替代数据迁移评估、消费者回归测试或领域专家判断。

## 4. 独立审批、发布和回退

新增 API：

- `POST /api/ontology/governance/proposals`：提交 promote 或 rollback 提案。
- `POST /api/ontology/governance/proposals/{id}/decision`：独立审批或驳回。
- `POST /api/ontology/governance/proposals/{id}/execute`：审批后执行版本目录指针更新。
- `GET /api/ontology/governance`：读取活动版本、提案与发布记录。

治理约束：

1. 申请人不能审批自己的提案。
2. 执行人必须同时不同于申请人和审批人。
3. 审批绑定快照摘要，执行前再次核对摘要。
4. 活动版本在提案创建后发生变化时，旧提案不能覆盖新指针。
5. 兼容性检查不通过时，必须显式接受风险并提供审批说明。
6. 回退同样走提案、独立审批和执行流程；降级/删除风险不能被静默忽略。

**重要边界：** 当前执行的是 Portal 本地状态中的 `activeOntologySnapshotId` 目录指针，发布记录明确标注 `runtimeActivation=catalog-pointer-only`。它不会改写 `ontology/software-factory-ontology.json`，也不会自动切换其他服务、Agent Runtime 或数据库中的本体版本。真正的运行时激活需要后续将该目录接入契约解析器、任务上下文和各服务的版本协商。

## 5. Portal UI

本体工作台新增：

- **依赖影响**：查看 Role、Skill、Workflow、Tool、Contract 的关系，并按本体类查询影响消费者。
- **版本快照**：创建快照、查看历史、比较结构差异和兼容性报告。
- **发布治理**：提交 promote/rollback 提案、独立审批、独立执行版本目录指针更新。

## 6. 验证与当前限制

新增测试覆盖：

- 依赖图的 Role/Skill/Workflow/Tool/Contract 关联
- 从本体类到下游消费者的影响遍历
- 无效类和工具引用检测
- 删除类的破坏性判定与主版本要求
- 主版本递增后的破坏性变更人工评审
- 新增类和词汇值的兼容性判定
- 首次基线发布、申请/审批/执行职责分离
- 回退的风险确认
- 并发活动指针变化后的过期提案拒绝

本地 Portal 默认仍是 loopback 单用户参考服务，actor 字段是操作留痕而非身份认证。生产环境必须由 OIDC/IAM、服务端授权、不可篡改审计、签名快照、数据库事务和实际消费者版本协商补齐安全边界。
