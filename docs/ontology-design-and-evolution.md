# 软件工厂本体的设计与演进方案

## 1. 定位

软件工厂本体是多个模块共享的业务语义模型。它说明对象是什么、如何关联、状态如何解释和哪些关系应被校验；它不独立授予系统权限，不证明外部数据真实，不替代数据库事务、工作流、策略引擎或安全扫描。

## 2. 从能力问题（Competency Questions）出发

- 需求由什么验收条件验证？
- 产品由哪些组件组成，组件默认版本属于谁？
- 某制品由哪个构建和源码版本产生？
- 哪些测试真实验证了哪个构建？
- 安全发现影响哪些组件/版本？
- 哪些构建、测试和安全证据足以满足发布策略？
- 一个客户交付用了哪个标准版本和哪些隔离的配置差异？
- 某部署或事件如何追溯到版本、执行记录和证据？

每个类/关系至少应支持一个业务问题或成为多个子系统稳定共享的概念。无具体使用场景的概念先放入候选扩展，不直接加入核心。

## 3. 核心类与候选扩展

第一版核心类：`Requirement`, `Product`, `Component`, `Version`, `Artifact`, `Build`, `TestRun`, `Vulnerability`, `Release`, `Deployment`, `Incident`。该列表与 `ontology/software-factory-ontology.json` 保持一致。

候选扩展分为两组：交付侧的 `CustomerEnvironment`, `CustomerConfig`, `WorkflowRun`, `ToolExecution`, `Approval`, `Evidence`, `CostRecord`；多智能体操作域的 `AgentTeam`, `AgentRole`, `Skill`, `AgentTask`, `AgentHandoff`, `AgentResult`, `ContextReference`, `CoordinationDecision`, `ReviewDecision`。本次把后一组纳入独立的 `operationalExtensions`，作为第 15 篇的设计基线；这些扩展通过稳定 ID、任务/运行关联和证据引用连接到 11 类交付核心，而不是把运行状态、权限策略直接混进核心实体。

## 3.1 LLM 辅助本体发现：候选生成，而非自动发布

本体发现采用四阶段候选流水线：术语发现、关系发现、约束与能力问题发现、独立 Critic；再执行 Schema/端点/引用核验、Benchmark 评估与人工评审。候选对象包含来源清单与摘要、每项证据引用、模型调用 trace、评测结果和 candidate digest。未核验的来源引用、未解析的关系端点、Critic blocker 或未满足门禁条件时，不能批准。

外部组件通过适配器接入，不作为本体定义的权威：NVIDIA Auto Ontology 可只读提供外部语义目录元数据；Cognee 可把候选图暂存到隔离 review dataset；LLMs4OL/OLLM 用作本体学习任务和 Benchmark 设计参考。具体选型与限制见 `docs/ontology-discovery.md`。

正式本体变更遵循“候选 → 评测 → 人工审批（绑定 digest）→ 版本化差异提案 → Schema/语义/Agent/Workflow/Policy 回归 → 单独发布”。模型输出不直接写入正式本体、权限、工作流或安全策略。

## 4. 关系和不变量

- Product contains Component。
- Component references a Version that belongs to the same Component.
- Build references Component/Version and source revision; successful Build must have traceable output as required by the policy.
- TestRun references the Build it validated and its actual report artifact.
- Vulnerability references affected Component and Version(s).
- Release references Product/Version(s), builds, tests and evidence.
- Deployment references a Release and named Environment.
- Incident references affected deployment/components and related evidence where available.

状态、事件、动作需区别建模：状态是对象当前生命周期；事件记录状态变化；动作是需要参数、前置条件、权限和后置条件的命令。`approved` 不是工具可以执行的充分条件，还需检查主体授权、目标资源、风险策略、审批有效期和当前对象版本。

## 5. 表示与验证策略

MVP 采用 machine-readable JSON vocabulary + JSON Schema Draft 2020-12 + Python semantic checks。JSON Schema 验证单对象结构；语义校验验证跨对象 ID、类型、版本归属、唯一性和部分生命周期不变量。只有实际需要 RDF 互操作、OWL 推理或 SHACL 图约束时才引入相应技术。

## 6. 从本体到运行时

`ontology/` 与 `operationalExtensions` → 版本化 `contracts/`（含 AgentHandoff）→ 语义校验与 Team Topology → Workflow/Policy/Adapters → actual execution evidence。业务语义可帮助形成策略上下文，但授权必须由 IAM/策略组件独立判定；生成的候选变更也不能直接覆盖发布版本。

## 7. 版本与治理

每次变更需记录：变更目的、owner、ontology/schema version、改变的类/关系、向后兼容性、数据/接口迁移方式、受影响 Agent/Skill/Workflow/Policy、正负向回归测试和批准记录。破坏性变化需版本升级与弃用窗口。运行反馈只能产生变更建议，不能无审批地自动写回生产本体。

## 8. 多智能体扩展建模原则

- `AgentTeam` 描述已批准拓扑与边界，不能当作 IAM 角色本身。
- `AgentRole` 表达业务职责；实际工具授权仍由策略运行时决定。
- `AgentTask` / `AgentHandoff` 传递引用、预算、期限和验收条件，避免共享任意可变上下文。
- `AgentResult` 是候选输出；`ReviewDecision` 必须说明验证主体和证据来源。
- `CoordinationDecision` 是 Workflow 控制器记录的派发/汇合/重试/停止决策，而不是 LLM 的自由文本命令。
