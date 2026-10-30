# 本体版本绑定的 Agent Runtime

本阶段将经审批的本体快照绑定到真实 Agent Workflow 的每一次运行。目标不是在 Prompt 中简单写一个版本号，而是让版本摘要、Agent Task 契约、Agent Result 契约和 Evidence 在同一条执行链中保持一致。

## 1. 执行链路

```text
Portal activeOntologySnapshotId
        |
        v
load_active_ontology_binding()
  - load full snapshot
  - recompute SHA-256
  - verify snapshotId / ontologyVersion / schemaVersion
        |
        v
WorkflowEngine.create_run()
  - persist immutable ontologyBinding on run
        |
        v
enqueue_workflow_step()
  - copy binding into Worker task payload
        |
        v
AgentWorkflowStepHandler
  - verify snapshot digest again
  - load Role definition
  - check Role input/output types exist in pinned ontology
  - create and validate Agent Task JSON Schema
        |
        v
OpenAIAgentsRuntime.run_agent()
  - verify binding + task contract
  - provide classes / relations / vocabularies / invariants to Agent
  - validate typed entity references in returned output
        |
        v
Agent Result contract + SHA-256 Evidence
  - snapshot ID / digest / ontologyVersion / schemaVersion
  - output entity types match Role outputEntityTypes
```

## 2. 运行时版本选择

真实 Agent Workflow 只读取 Portal 中的**活动本体版本指针**。工作流创建时将完整快照复制到 Workflow Run 持久化记录；后续每个 Worker Task 使用该运行自己的快照，不会在阶段之间重新读取最新活动指针。

因此：
- 新版本发布不会改变已经创建的运行。
- 已有运行继续使用创建时绑定的快照。
- 找不到活动快照、快照摘要不一致、版本元数据与内容不一致时，创建或执行失败关闭。
- 不接受只带 `ontologyVersion` 而没有快照 ID 和摘要的 Agent Task。

## 3. Agent Task 契约

`contracts/schemas/agent-task.schema.json` 新增必需字段：

- `ontologyVersion`
- `ontologySnapshotId`
- `ontologyDigest`
- `ontologySchemaVersion`

Task 仍然包含 task / tenant / project / role、输入实体类型、期望输出实体类型、验收标准、上下文引用、敏感级别、资源限制和幂等键。运行时会将 JSON Schema 中的实体类型 enum 与所绑定快照的类集合对齐，并进一步验证输入实体类型属于 Role 的 `inputEntityTypes`。每个 Role 引用的 Skill 也会逐个读取 `skill.json`，验证 Skill 输入/输出类存在于同一快照、Skill 声明兼容当前 Role，且 Skill 所需工具全部位于 Role 的工具授权列表内。Workflow 派发的 Role / Skill ID 必须与注册的阶段处理器和 Role 声明一致。

## 4. Agent Result 契约

`contracts/schemas/agent-result.schema.json` 增加相同的版本绑定字段。每个 Agent 阶段保存：

- `output.json`：模型结构化输出、Agent Task 契约和本体绑定元数据。
- `agent-result.json`：按 Role 声明的 `outputEntityTypes` 生成的结果封套。
- `evidence/`：Workflow 所要求的阶段证据。
- `evidence-index.json`：输出摘要、Agent Result 摘要和本体版本绑定。

Evidence metadata 包含 `ontologySnapshotId`、`ontologyDigest` 和 `ontologyVersion`。Agent Result 的输出实体类型必须与 Role 的输出类型集合完全一致。Runtime 会把本体类、关系、受控词汇、不变量以及已验证的 Skill 契约作为结构化上下文提供给 Agent，而不是只在 Prompt 中传递一个版本字符串。

注意：Agent Result 封套证明执行器按 Role 声明登记了哪些输出类型，不等于模型生成内容已经通过业务数据库写入或领域专家验收。当前结构化 Pydantic 输出模型与领域实体之间仍是参考映射，复杂实体还需要后续专门的领域对象映射器和业务校验器。

## 5. 直接 Agent Pipeline

`SoftwareFactoryPipeline` 对标记为需要本体绑定的真实 Runtime，同样解析活动快照、生成 Agent Task 契约并传入 Runtime。确定性 Fake Runner 测试替身不要求外部快照，不会触发真实模型调用。

## 6. 初始化活动版本

首次使用前需要在 Portal 中建立正式版本基线：

1. 启动 `make portal`，打开 `http://127.0.0.1:8770`。
2. 进入本体工作台的版本快照，创建快照并记录 `snapshotId`。
3. 进入版本治理，针对该快照创建 `promote` 提案。
4. 由不同操作者完成审批，再由第三个操作者执行。
5. 确认活动版本指针指向目标快照。

也可以使用 Portal HTTP API 完成同一流程：

```bash
curl -sS -X POST http://127.0.0.1:8770/api/ontology/versions/snapshot \
  -H 'Content-Type: application/json' \
  -d '{"actor":"ontology-requester","reason":"建立初始运行时本体基线"}'
```

从响应中取得 `snapshot.snapshotId`，然后：

```bash
curl -sS -X POST http://127.0.0.1:8770/api/ontology/governance/proposals \
  -H 'Content-Type: application/json' \
  -d '{"snapshotId":"ont-替换为实际ID","action":"promote","actor":"ontology-requester","reason":"首次发布基线"}'
```

从响应中取得 `proposal.proposalId`，使用不同操作者审批：

```bash
curl -sS -X POST http://127.0.0.1:8770/api/ontology/governance/proposals/替换为实际提案ID/decision \
  -H 'Content-Type: application/json' \
  -d '{"actor":"ontology-reviewer","decision":"approve","notes":"已检查初始本体基线","acceptBreakingChanges":false}'
```

再由第三个操作者执行：

```bash
curl -sS -X POST http://127.0.0.1:8770/api/ontology/governance/proposals/替换为实际提案ID/execute \
  -H 'Content-Type: application/json' \
  -d '{"actor":"ontology-executor","reason":"执行已批准的初始基线发布"}'
```

以上 actor 是本地演示审计字段，不是身份认证；真实多人环境必须接入 IAM。

## 7. 启动真实多 Agent Workflow

在一个终端设置模型凭据并启动：

```bash
export OPENAI_API_KEY='...'
export OPENAI_MODEL='账户可用的模型 ID'
export AGENT_TRACE_ENABLED=false
python -m pip install -e '.[agent-runtime]'
make agent-workflow-console
```

浏览器打开 `http://127.0.0.1:8769`。状态面板应显示活动本体版本和快照 ID。创建运行后，页面按顺序执行：

1. **派发当前步骤**：将当前 Workflow Step 写入 Worker 队列。
2. **执行一个 Worker 任务**：真实调用 OpenAI Agents SDK。
3. **Relay 回写事件**：将 Worker 结果回写 Workflow。
4. 重复以上步骤，直到安全审查完成。
5. 最后进入人工复核步骤；由独立人员批准或拒绝。

运行记录会展示本体版本、快照 ID、任务、Worker、Outbox、Evidence 和 Agent Result。真实模型调用会产生 API 费用，并将任务上下文发送到所配置的模型服务。

## 8. 验收与故障排查

| 现象 | 检查 |
|---|---|
| 创建运行时报 no active ontology snapshot | Portal 中尚未执行初始 promote；完成版本治理流程 |
| snapshot digest mismatch | 本地 Portal 状态中的快照内容与摘要不一致；不要手工编辑快照，重新从正式本体创建并审批新快照 |
| Role input/output type absent | Role 配置引用了所绑定版本中不存在的类；修订本体或 Role 后重新校验和发布 |
| Agent Task contract invalid | 检查 task schema、role ID、资源限制、版本绑定和实体类型 |
| Agents SDK missing | 执行 `pip install -e '.[agent-runtime]'` |
| API 认证或模型错误 | 检查当前 shell 的 `OPENAI_API_KEY` 和账户可用的 `OPENAI_MODEL` |
| Agent 输出结构错误 | 检查对应 Role 的 Pydantic Output Model 与模型结构化输出支持 |

测试覆盖版本加载、摘要篡改拒绝、缺少活动版本拒绝、Role 类引用检查、Task 契约绑定、Worker 传播、Agent Result 生成和缺少绑定时 fail-closed。GitHub CI 通过不代表真实 OpenAI 账户和模型已在本环境完成端到端调用。
