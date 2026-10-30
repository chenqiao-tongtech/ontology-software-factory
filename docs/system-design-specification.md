# 本体驱动 AI 软件工厂系统设计说明书

| 文档属性 | 内容 |
|---|---|
| 文档编号 | OSF-SDS-001 |
| 文档版本 | 1.3 |
| 基线日期 | 2026-10-30 |
| 适用系统 | ontology-software-factory |
| 基线分支 | main |
| 系统定位 | 本体驱动的 AI 软件工厂参考实现与本地 MVP |
| 文档状态 | 现状基线版；设计变更通过 ADR 维护 |

## 1. 引言

### 1.1 编写目的

本文定义系统现状架构、边界、子系统职责、组件构成、数据模型、接口、运行机制、安全控制、部署方式、第三方依赖和验收要求。本文用于指导主控 Agent、模块化本体治理，以及 Harness Runtime、Skill Registry、Connector Runtime、本体发现连接器、Agent Tools 和统一监控台的持续建设。

盘点依据为仓库 main 分支在 2026-10-30 的代码、配置、测试及文档资产。文件存在情况按仓库内容描述；外部服务连通性、生产部署能力和企业级安全能力以独立验收记录为准。

### 1.2 系统目标

系统面向标准化软件产品及行业客户定制交付，形成需求接入、领域语义建模、资产解析、多 Agent 协作、确定性编排、受控工具执行、独立质量验证、候选制品交付和运行反馈的工程闭环。

### 1.3 设计原则

- 领域语义、Agent 框架和外部供应商保持解耦。
- 控制面负责授权、编排和状态管理；执行面负责受控操作。
- Agent 输出采用结构化契约，Workflow 控制任务状态。
- 工具执行权限由策略层授予，工具协议不授予权限。
- 本体发现结果保留来源证据，正式本体变更经过评审和版本治理。
- 生成过程与独立验证过程分离。
- 质量结论绑定具体候选版本、运行和制品摘要。
- 默认拒绝、最小权限、租户边界和秘密引用作为安全基线。
- 性能、成本和可用性指标通过实际运行测量建立。

### 1.4 术语

| 术语 | 定义 |
|---|---|
| Ontology | 描述领域概念、属性、关系、状态、事件和约束的语义模型 |
| Agent | 在指定角色和任务边界内执行推理及结构化产出的运行单元 |
| Harness | 管理 Agent 身份、上下文、策略、工具、预算、隔离和证据的运行控制层 |
| Skill | 具有版本、输入输出契约、执行步骤和验证标准的可复用任务能力 |
| Tool | 具备类型化输入输出和明确副作用边界的原子操作 |
| Connector | 连接外部数据源或动作系统的协议适配组件 |
| Workflow | 定义任务依赖、状态转换、审批和恢复规则的确定性流程 |
| Evidence | 绑定来源、运行、工具版本和制品摘要的验证材料 |
| Candidate | 等待验证、评审或批准的本体、代码、配置或交付候选对象 |

## 2. 系统范围与现状

### 2.1 业务范围

当前主要工程示例围绕 Kafka 配置产品交付，包括需求范围检查、资产选择、配置生成、结构校验、质量门禁、候选交付包、升级与回滚演练。Kafka 上游运行时的编译、重写及生产集群部署不属于当前 MVP 范围。

系统同时提供本体发现、候选评审、Agent Workflow、Worker 任务派发、来源同步、运行监控和本地控制台等扩展能力。

### 2.2 实现状态定义

| 状态 | 判定标准 |
|---|---|
| 已实现 | 存在可调用实现，并有相应自动化测试或验证入口 |
| 部分实现 | 存在代码或 UI 原型，外部服务、持久化、权限、生产运行或完整闭环仍有缺项 |
| 规划建设 | 已形成设计或目录定义，尚无可用运行实现 |
| 外部验收待完成 | 本地代码和 Mock/Fixture 测试存在，真实外部服务连通及权限配置尚未验证 |

模块文件存在不代表外部服务已连通；单元测试通过不代表生产运行能力已验收。

### 2.3 当前范围边界

- 本地参考运行模式和单机 SQLite 持久化。
- OpenAI LLM Provider 与 OpenAI Agents SDK 可选接入。
- 本地目录、SQLite、PostgreSQL、MySQL Schema 只读发现；GitHub/GitLab 仓库元数据扫描。
- 本体候选生成、来源证据校验、Critic、Benchmark 和人工审批提案。
- 有界 Agent 团队、角色/Skill 定义、结构化交接和 Agent Workflow。
- Worker 队列、租约、重试、幂等键、事务型 Outbox/Inbox 的单机参考实现。
- Tool Registry、MCP stdio 与 HTTP JSON 适配器。
- 受控工作区、固定测试套件、容器化测试和安全扫描路径。
- Kafka 配置包构建、质量门禁、制品摘要、候选交付与本地升级/回滚演练。
- 本地 Portal 与多个运行控制台。

企业 SSO、完整多租户生产控制面、分布式高可用调度、生产级 Secret Broker、生产级微虚机隔离、远程 PR 合并和生产部署适配器列入后续建设。

## 3. 总体架构

### 3.1 架构视图

~~~mermaid
flowchart TB
  USER[用户 / 领域专家 / 运维人员]
  subgraph UX[交互层]
    PORTAL[Factory Portal]
    CONSOLE[Workflow / Agent / Worker Consoles]
  end
  subgraph CONTROL[控制面]
    INTAKE[需求接入与范围校验]
    ONT[本体与契约 Registry]
    CATALOG[产品与资产目录]
    AGENT[Agent Team / Role / Skill]
    HARNESS[Harness：策略 / 上下文 / 预算 / 工具中介]
    WF[Workflow Engine]
    TASK[Task Runtime / Outbox / Inbox]
    CONN[Connector Runtime]
    TOOL[Tool Registry / Tool Gateway]
  end
  subgraph EXEC[执行面]
    WORKSPACE[Run-scoped Workspace]
    RUNNER[Restricted Runner]
    ADAPTER[HTTP / MCP / Git / DB / LLM Adapters]
  end
  subgraph VERIFY[验证与交付]
    TEST[Build / Test / Scan]
    GATE[Quality & Security Gate]
    APPROVAL[Human Approval]
    RELEASE[Artifact / Release Candidate]
  end
  DATA[(SQLite / JSON / Evidence / Deliverables)]
  OBS[Observability / Audit / Cost]
  USER --> UX --> INTAKE
  INTAKE --> ONT
  ONT --> AGENT
  CATALOG --> AGENT
  AGENT --> HARNESS --> WF --> TASK
  TASK --> TOOL
  TOOL --> CONN
  TOOL --> ADAPTER
  ADAPTER --> WORKSPACE --> RUNNER
  RUNNER --> TEST --> GATE --> APPROVAL --> RELEASE
  WF --> DATA
  TASK --> DATA
  CONN --> DATA
  RELEASE --> DATA
  DATA --> OBS --> UX
~~~

### 3.2 逻辑分层

| 层次 | 职责 | 主要组件 |
|---|---|---|
| 交互层 | 请求提交、运行查看、候选评审和运维操作 | Factory Portal、Workflow Console、Agent Workflow Console、AI Runtime Console、Worker Console、Integrated Console |
| 需求与语义层 | 需求规范化、领域语义、Schema 和跨对象校验 | Scope、Ontology Runtime、Contracts、Semantics |
| 资产层 | 产品、组件、版本、兼容性和交付配置 | Asset Catalog、Compatibility Matrix |
| Agent 能力层 | 团队拓扑、角色、Skill、交接、结构化结果 | Multi-Agent Architecture、Agent Runtime、Agent Models |
| 编排层 | Run/Step 状态、任务派发、审批、重试和事件集成 | Workflow Engine/Store、Task Runtime、Integration |
| 集成层 | Tool、MCP、HTTP、Git、数据库、LLM 和本体服务适配 | Tool Registry、Adapters、Source Connectors、Remote Connectors |
| 执行层 | 工作区、固定命令、测试和扫描 | Workspace Execution、Restricted Runner、Docker Runner |
| 验证交付层 | 质量策略、证据、制品、发布候选和回滚演练 | Quality Gate、Release Manager、E2E Delivery |
| 观测治理层 | 用量、成本、运行状态、审计和权限策略 | Observability、Runtime Observability、Policies、Ontology Governance |

### 3.3 关键控制边界

1. Workflow Engine 是流程状态的权威组件。
2. Agent Runtime 生成结构化候选结果，不能自行推进生产状态或批准高风险动作。
3. Harness 在 Agent 与工具之间实施策略、上下文和预算约束。
4. Tool Registry 负责工具定义、输入校验、角色权限和处理器分派。
5. Connector 负责外部协议、认证和数据映射；授权由统一策略层作出。
6. Runner 只执行经过批准的固定执行规格。
7. Quality Gate 只接受与本次候选制品摘要一致的真实报告。
8. Ontology Discovery 只产生候选变更；正式版本由治理流程维护。

## 4. 子系统设计

### 4.1 S1 需求接入与交互

**组件：** Factory Portal、Scope Checker、Requirement Intake、Workflow/Agent/Worker Console。

**输入：** 用户请求、产品范围、目标版本、约束条件和来源引用。

**输出：** 结构化需求、范围检查报告、Workflow Run 或本体发现任务。

**现状：** 本地 Portal 与多类 Console 页面已存在；Portal 服务和主要 API 具备本地参考实现。HTTP 服务默认绑定回环地址。生产身份认证、CSRF 防护、租户授权与外网暴露保护仍需建设。

### 4.2 S2 本体与语义契约

**组件：** ontology/software-factory-ontology.json、Ontology Runtime、Semantics、Contracts、Ontology Versioning、Ontology Governance。

**职责：**
- 定义领域类、属性、关系、状态和不变量；
- 通过 JSON Schema 校验对象结构；
- 通过 Python 语义校验检查跨对象引用及生命周期约束；
- 维护本体快照、结构 Diff 和消费者依赖图；
- 支持候选评审、审批提案和版本影响分析。

**现状：** 本体定义、结构/语义校验、版本快照与消费者引用分析已有实现。签名注册表、正式跨环境晋级、自动迁移和防篡改审计仍待建设。

### 4.3 S3 产品与资产目录

**组件：** Catalog、资产 Schema、兼容性矩阵、示例资产、生命周期策略。

**职责：** 管理产品、组件、版本、依赖、配置模板、客户化扩展、许可和来源元数据；根据需求和约束解析可用资产。

**现状：** JSON 资产目录和校验入口已实现；企业制品库、供应链证明和完整许可证治理仍需扩展。

### 4.4 S4 多 Agent、Harness 与 Skills

**组件：**
- Agent Team Topology：团队角色、顺序/并行关系、Join 条件和修复上限；
- Role Registry：职责、输入输出、允许工具和禁止动作；
- Skill Definitions：skills/*/skill.json 与 SKILL.md；
- Agent Runtime：OpenAI Agents SDK 可选适配器；
- Agent Models：结构化输出模型；
- Tool Registry：工具定义与权限交集；
- Harness：统一策略、上下文、预算、凭据、隔离和证据控制。

**现状：** 团队拓扑、角色文件、Skill 文件、Skill Schema、Agent SDK 适配器、结构化输出和工具权限交集已有实现。Agent Runtime 新增本体定义只读、连接器目录只读和依赖声明只读三类工具，并通过角色 Tool ID 与策略矩阵限制可见范围。本阶段新增 SkillRegistry，支持 Skill Schema 校验、角色/能力目录引用校验、指令文件读取及内容摘要锁；该 Registry 尚未接入 Agent Workflow 的运行时加载链路。新增 HarnessRuntime 本地参考实现，提供按角色字段白名单组装上下文、租户/项目绑定、工具调用预算、模型 Token 预算、独立审批回调、元数据审计和文件型 Kill Switch。HarnessRuntime 当前由调用方显式注入 ToolRegistry，尚未成为 OpenAIAgentsRuntime 的默认中介，也未提供企业 PDP、Secret Broker 或分布式预算存储。

**执行约束：** Agent 最大轮次受配置限制；默认工具范围有限；SDK tracing 默认关闭；生产部署、秘密读取、策略修改、自我审批和跨租户读取为全局拒绝动作。

### 4.5 S5 Workflow 与任务运行时

**组件：** Workflow Definition、Workflow Engine、SQLite Workflow Store、Task Runtime、Transactional Outbox/Inbox、Worker Console。

**职责：** 校验 DAG、管理 Run/Step 状态、执行合法状态转换、保存事件、创建 Worker 任务、租约与重试、去重和事件回投。

**现状：** 单机持久化状态机、Worker 任务队列、租约/重试、幂等键和 Outbox/Inbox 集成已实现。Workflow Engine 的并行调度、分布式多节点派发和 HA 能力须按现有代码进一步验收；SQLite 仅作为单机参考存储。

### 4.6 S6 Tools、Connectors 与外部适配

**组件：** Tool Registry、HTTP JSON Adapter、MCP stdio Adapter、LLM Provider、Source Connector Registry、Remote Repository Connector、Database Connectors、Ontology Provider Adapters、Connector Catalog。

**职责：**
- Tool Registry：工具 Schema、角色权限交集、输入验证和处理器调用；
- Protocol Adapter：HTTP JSON 和 MCP stdio 消息传输；
- Source Connector：只读扫描源资产、Schema 和仓库元数据；
- Action Connector：执行经过授权的外部写操作；
- Connector Catalog：登记连接器能力、方向、操作、实现状态、数据分类、认证方式、网络出口和审批要求。

**现状：**
- 本地目录、SQLite Schema、PostgreSQL Schema、MySQL Schema 连接器已有实现；
- GitHub/GitLab 远端仓库元数据连接器已有实现，受固定 Provider Host 约束，不下载远端文件正文；
- NVIDIA Auto Ontology 目录导入适配器与 Cognee 候选图适配器已有代码；真实服务连通待验收；
- HTTP JSON、MCP stdio 适配器已有实现；
- Connector Catalog 已有 Schema、目录加载与默认拒绝检查；
- Confluence、SharePoint、实时 Kafka Schema Registry API、GitHub PR、Jira 和 CI 动作连接器在目录中登记，当前属于规划状态；Schema Registry 文件导入已实现。

### 4.7 S7 受控执行

**组件：** Workspace Execution、Restricted Runner、Docker Test Runner、固定测试套件和扫描器适配。

**职责：** 创建 Run 级隔离工作区；限制读写路径；按固定 Suite ID 执行测试；采集退出码、日志、报告和摘要；限制容器权限、网络、资源和文件系统。

**现状：** 工作区副本、路径校验、固定 argv、Docker 测试执行和容器扫描路径已有实现。宿主机执行开关属于显式危险回退模式；当前隔离不等同于多租户生产级微虚机安全边界。Git Worktree 本地分支不提供远程 Push、PR、Commit 或 Merge。

### 4.8 S8 质量与安全

**组件：** Quality Gate、质量策略、配置验证、单元测试、Semgrep、Gitleaks、Trivy、Evidence Evaluator。

**职责：** 对候选配置或 Agent Workspace 执行独立检查；对缺失报告、工具缺失、摘要不匹配和扫描发现执行阻断或 incomplete 处理。

**现状：** Kafka 配置包质量门禁与 Agent Workspace 证据门禁均有实现。两条门禁的检查对象和策略范围不同。当前能力不能代表完整源码 SAST、全依赖 SCA、法律许可审查、生产镜像和运行集群验证。

### 4.9 S9 制品、交付与发布

**组件：** Software Factory Pipeline、E2E Delivery、Release Manager、Manifest、SHA-256、配置范围 SBOM、本地升级/回滚演练。

**现状：** 本地候选包构建、完整性校验、质量报告绑定和交付目录生成已有实现。配置范围 SBOM 不代表 Kafka 上游二进制及其全部依赖的完整 SBOM。生产部署、签名制品、OCI Registry 和客户环境升级仍待建设。

### 4.10 S10 观测与审计

**组件：** JsonlUsageLedger、Observability Report、Runtime Observability、Portal 聚合 API、运行控制台。

**职责：** 采集模型用量、运行状态、任务事件、质量状态、证据引用、同步状态和本地成本估算。

**现状：** 本地 JSONL/SQLite 聚合和只读监控视图已有实现；未知费率保留 unknown。Portal 统一监控 API 已增加 Harness 与 Connector 审计 JSONL 的元数据聚合，前端显示调用总量、状态分布和操作分布。审计路径通过 FACTORY_HARNESS_AUDIT 与 FACTORY_CONNECTOR_AUDIT 配置，默认位于 .local-runs。OpenTelemetry 采集、分布式 Trace、指标时序库、告警路由、SLO、租户隔离和防篡改审计仍待建设。

### 4.11 S11 横切安全治理

**组件：** Agent Permission Matrix、Tool Permissions、Context Policy、Quality Policy、Connector Policy、Approval Records、Secret References。

**现状：** 角色工具权限、默认拒绝动作、来源访问边界、审批检查和凭据环境变量引用已有局部实现。HarnessRuntime 提供本地上下文/预算/工具审计和 Kill Switch 参考实现；企业 IAM、OIDC、统一 PDP、Secret Broker、租户级策略、密钥轮换和集中审计服务仍待建设。

## 5. 核心数据对象与持久化

### 5.1 核心业务对象

| 对象类别 | 对象 |
|---|---|
| 业务语义 | OntologyClass、OntologyRelation、OntologyConstraint、OntologySnapshot |
| 需求与资产 | Requirement、Product、Component、Version、Compatibility、CustomerConfig |
| Agent 协作 | AgentTeam、AgentRole、Skill、AgentTask、AgentHandoff、AgentResult、ContextReference |
| 工作流 | WorkflowDefinition、WorkflowRun、WorkflowStep、WorkflowEvent、WorkerTask、OutboxEvent、InboxRecord |
| 工具执行 | ToolDefinition、ToolExecution、ConnectorDescriptor、SourceAsset、SourceSync |
| 质量与交付 | Artifact、BuildRecord、TestRun、SecurityReport、Evidence、GateDecision、Approval、ReleaseRecord |
| 观测 | UsageRecord、RuntimeEvent、TraceReference、CostEstimate |

### 5.2 主要存储

| 存储位置 | 内容 | 当前用途 |
|---|---|---|
| SQLite Workflow Store | Run、Step 状态和事件 | 本地工作流控制台 |
| SQLite Task Store | Worker 任务、租约、重试和 Outbox | 单机可靠派发参考实现 |
| SQLite Agent Workflow Store | Agent Workflow 运行与任务状态 | Agent Workflow Console 与 Portal 只读聚合 |
| 本地 JSON/JSONL | 配置、运行记录、用量和同步元数据 | 本地参考持久化 |
| Run Workspace | 候选代码、测试报告、安全报告和日志 | 单次执行证据 |
| Deliverables | 候选交付文件、Manifest 和质量材料 | 本地交付演练 |
| Git 仓库 | 本体、契约、资产、角色、Skills、Workflow 和策略定义 | 版本控制与评审 |

SQLite 文件和本地运行目录不得提交到源码仓库。多实例生产部署需迁移至支持并发、备份、加密、租户隔离和恢复演练的持久化服务。

## 6. 外部接口与协议

### 6.1 本地 HTTP 服务

| 服务 | 启动入口 | 默认端口 |
|---|---|---:|
| Factory Portal | scripts/run_factory_portal.py | 8770 |
| AI Runtime Console | scripts/run_ai_runtime_console.py | 8768 |
| Agent Workflow Console | scripts/run_agent_workflow_console.py | 8769 |
| Workflow Console | scripts/run_workflow_console.py | 8765 |
| Worker Console | scripts/run_worker_console.py | 按脚本配置 |
| Integrated Console | scripts/run_integrated_console.py | 按脚本配置 |

各服务默认用于本机开发和演示。未检查的端点契约以实际 API 实现和对应文档为准。生产接入需统一 API 版本、认证、授权、限流、错误码、幂等键和审计字段。

### 6.2 外部协议

| 协议 | 用途 | 安全要求 |
|---|---|---|
| HTTPS JSON API | LLM、GitHub/GitLab、NVIDIA 等服务 | 固定 Host/出口策略、TLS、秘密引用、超时和重试 |
| MCP stdio | 管理员配置的本地 MCP Server | 仅信任管理员配置命令；隔离进程、环境变量和权限 |
| SQL metadata | PostgreSQL/MySQL Schema | 只读账户、TLS、Host allow-list、只查询元数据 |
| SQLite | 本地 Schema 与状态持久化 | 只读源连接、数据库文件访问权限 |
| JSON/JSON Schema | 领域契约、Tool、Workflow、Skill 和 Connector 定义 | Schema 版本、严格校验和兼容性策略 |
| Docker CLI | 固定测试和扫描任务 | digest 固定、无网络、只读文件系统、资源限制 |

### 6.3 Connector 接口约束

每个 Connector Descriptor 至少定义稳定 ID、类别、方向、操作列表、实现状态、数据分类、认证方式、凭据引用、网络出口等级、审批要求和说明。Source Connector 采用只读原则；Action Connector 的写操作必须由独立策略判定，并绑定审批记录和幂等键。

## 7. 安全设计

### 7.1 身份与权限

- Agent Role、Skill、Tool、Connector 和 Runner 分别声明能力边界。
- 有效工具集合取角色声明、策略许可、运行时已注册处理器的交集。
- 未知主体、工具、操作或连接器默认拒绝。
- 本体概念和关系不授予系统权限。
- 生产发布、删除、数据迁移、权限变更和密钥轮换要求独立审批。

### 7.2 数据与凭据保护

- 密钥通过环境变量或 Secret Reference 注入。
- 密钥不得写入 JSON 配置、Prompt、日志、候选本体和证据正文。
- Source Connector 保留数据来源 ACL 和租户范围。
- 发送给 LLM 的材料须经过数据分类、敏感信息检测和最小化处理。
- 监控 API 只返回必要的运行元数据，不返回 Prompt、模型原始响应和原始工具参数。

### 7.3 执行隔离

- 工作区路径限定在 Run 目录。
- Tool 使用固定输入 Schema 和固定处理器。
- 测试执行采用固定 Suite ID 和固定 argv。
- Docker 执行配置网络禁用、只读 rootfs、能力集收缩、非 root 用户及资源限制。
- 宿主机回退执行必须显式启用，并限定在可信开发环境。
- 外部网络出口控制由部署层实施，应用层 Host allow-list 不能替代防火墙。

### 7.4 证据完整性

Evidence 应绑定 runId、taskId、attemptId、source revision/digest、candidate digest、tool ID/version、policy version、时间、退出码和报告摘要。旧报告、其他 Run 的报告或摘要不匹配的报告不得用于当前质量放行。

## 8. 非功能要求

| 类别 | 设计要求 | 当前状态 |
|---|---|---|
| 正确性 | Schema、语义约束、状态转换和证据摘要校验 | 本地实现 |
| 安全性 | 默认拒绝、最小权限、路径限制和秘密最小化 | 局部实现；企业 IAM 待建设 |
| 可靠性 | 幂等、有限重试、租约、Outbox/Inbox 和恢复 | 单机参考实现 |
| 可观测性 | 运行状态、阶段、耗时、错误、Token 和证据索引 | 本地聚合实现 |
| 可扩展性 | Adapter、Registry、Schema 和版本化配置 | 基础接口存在；统一运行时待建设 |
| 可维护性 | 单一职责、ADR、自动化验证和依赖审查 | 仓库具备相关基线 |
| 性能 | 建立任务排队、模型调用、扫描、图谱渲染的基准 | 需基于真实任务测量 |
| 可用性 | 备份、恢复、HA、灾备和容量规划 | 生产设计待完成 |

不得在缺少实测数据时声明吞吐量、延迟、并发量或 SLA 指标。

## 9. 部署与运行设计

### 9.1 当前本地开发部署

- Python 3.11+；
- 建议使用独立虚拟环境；
- 基础安装使用 pip install -e .；
- 根据任务安装 llm、agent-runtime、postgres、mysql extras；
- 使用 Makefile 执行校验、测试和本地服务启动；
- Docker、Git、Semgrep、Gitleaks、Trivy 按功能选装；
- Portal 与 Console 默认仅绑定 127.0.0.1。

### 9.2 建议的生产目标部署形态

生产部署建议拆分为 API/Portal、Workflow Control Plane、Agent Workers、Connector Workers、Execution Runners、Evidence/Artifact Store、Relational Database、Secrets/IAM、Observability 等服务。通过队列实现异步任务派发，使用独立身份和短期凭据访问外部系统。Runner 放置于隔离执行网络，按租户和风险级别分配容器或微虚机。

上述形态属于目标部署设计，当前仓库未提供完整生产 Helm Chart、Terraform、HA 数据库、企业 IAM 和微虚机编排。

### 9.3 启动与验证

~~~bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
make validate
make test
make portal
~~~

真实 Agent Runtime：

~~~bash
python -m pip install -e '.[agent-runtime]'
export OPENAI_API_KEY='由受控密钥管理机制注入'
export OPENAI_MODEL='已获账户授权的模型 ID'
make agent-workflow-console
~~~

LLM 本体发现：

~~~bash
python -m pip install -e '.[llm]'
export OPENAI_API_KEY='由受控密钥管理机制注入'
export OPENAI_MODEL='已获账户授权的模型 ID'
python scripts/run_ontology_discovery.py --source docs/architecture.md
~~~

数据库连接器需安装对应 extra，并使用专用只读账户及 TLS 配置。真实外部连接需单独执行集成验收。

## 10. 第三方依赖与工具清单

### 10.1 Python 运行依赖

以根目录 pyproject.toml 为权威：

| 依赖 | 版本约束 | 依赖组 | 用途 |
|---|---|---|---|
| setuptools | >=68 | 构建后端 | PEP 517 构建 |
| jsonschema[format] | >=4.21,<5 | 基础依赖 | JSON Schema 与格式校验 |
| openai | >=1.99,<4 | llm / agent-runtime | OpenAI API Provider |
| openai-agents | >=0.4,<1 | agent-runtime | Agent、Runner、Function Tool |
| psycopg[binary] | >=3.2,<4 | postgres | PostgreSQL Schema 连接 |
| PyMySQL | >=1.1,<2 | mysql | MySQL Schema 连接 |

Pydantic 等传递依赖由安装器根据 Agent SDK 元数据解析。项目运行时还使用 Python 标准库中的 http.server、urllib、sqlite3、subprocess、pathlib、hashlib、threading、queue、json 等模块。

### 10.2 外部 CLI 与运行环境

| 组件 | 用途 | 启用条件 |
|---|---|---|
| Git | 仓库元数据、Worktree | 安装 Git 并按需配置 |
| GNU Make | 快捷命令 | 可选，亦可直接运行 Python 脚本 |
| Docker Engine | 固定测试与容器扫描 | 构建本地测试镜像并显式启用 |
| Semgrep | SAST | 配置本机 CLI 或固定镜像 |
| Gitleaks | 秘密扫描 | 配置本机 CLI 或固定镜像 |
| Trivy | 漏洞、依赖和配置扫描 | 配置本机 CLI 或固定镜像及数据库缓存 |
| 浏览器 | Portal/Console | 使用 Web UI 时需要 |

当前静态前端采用 HTML/CSS/JavaScript，不要求 Node.js、npm 或前端构建链。

### 10.3 外部服务和适配器

| 服务/组件 | 当前接入方式 | 状态 |
|---|---|---|
| OpenAI API | OpenAI Python SDK / Responses API | 可选；需真实 Key 和模型访问 |
| OpenAI Agents SDK | openai-agents | 可选；需安装 extra 并单独配置 |
| GitHub.com | 远端仓库元数据 API | 代码实现；真实权限和连通待验收 |
| GitLab.com | 远端仓库元数据 API | 代码实现；真实权限和连通待验收 |
| PostgreSQL | psycopg / information_schema | 代码实现；需 DSN、只读权限和 TLS |
| MySQL | PyMySQL / information_schema | 代码实现；需 DSN、只读权限和 TLS |
| NVIDIA Auto Ontology | HTTP 目录适配器 | 代码实现；真实实例连通待验收 |
| Cognee | 调用方注入 client/graph model | 可选适配器；生产晋级未实现 |
| MCP Server | 本地 stdio 子进程 | 适配器实现；仅信任管理员配置的 Server |

LLM、Git、数据库和外部本体服务调用会产生网络及数据处理边界。部署方须确认凭据权限、数据分类、服务区域、保留政策和第三方处理条款。

### 10.4 依赖治理

- 版本范围以 pyproject.toml 为准。
- 可选依赖按需安装，不纳入基础运行路径。
- 新增 SDK 或连接器依赖须提交 ADR、锁定版本范围、许可信息、漏洞扫描结果和集成测试。
- 外部容器镜像生产使用不可变 digest。
- 依赖升级需运行 Schema、契约、单元、集成和端到端回归。

## 11. 测试与验收策略

### 11.1 测试层级

1. 静态配置与 JSON Schema 校验；
2. 模块单元测试；
3. Tool、Connector、Workflow、Agent 契约测试；
4. SQLite/本地文件集成测试；
5. 真实 PostgreSQL/MySQL、Git Provider、LLM、MCP 和外部语义服务连接测试；
6. 端到端软件交付演练；
7. 安全负向测试、故障注入和恢复演练。

### 11.2 现有验证入口

- make validate：架构基线、范围、本体、目录、Agent、Workflow、连接器和消费者引用检查；
- make test：Python unittest 测试集；
- make demo-pipeline、make demo-gate、make demo-e2e：软件交付演练；
- make demo-ontology-discovery、make demo-ontology-discovery-worker：本体发现演练；
- GitHub Actions：执行 make validate 与 make test。

真实服务集成测试应单独标记环境、服务版本、凭据类型、执行时间和结果。Fixture/Mock 测试不得作为真实连接证明。

### 11.3 发布准入

候选发布需满足：需求与范围校验通过、输入契约有效、依赖版本明确、测试证据完整、安全扫描无阻断项、证据摘要匹配、质量策略通过、人工审批有效、制品完整性验证通过。任何必需证据缺失或状态不确定时，发布资格保持阻断。

## 12. 后续建设计划

| 序号 | 建设方向 | 主要交付物 | 前置条件 |
|---|---|---|---|
| 1 | Harness Runtime | 将现有本地 Harness 接入 Agent/Workflow；补齐 PDP 接口、策略版本、预算持久化、审计和 Kill Switch 运维接口 | 现有 Tool/Role/Policy/Workflow 契约 |
| 2 | Skill Registry | 将现有内容寻址 Registry 接入 Agent Runtime；补齐 Skill 依赖、回归测试、发布/弃用和发现 API | 现有 Skill JSON/SKILL.md |
| 3 | Connector Runtime | 将现有只读扫描 Runtime 接入 Portal 与 Source Sync；补齐同步游标、健康状态、凭据注入和动作连接器幂等执行 | Source Connector、Connector Catalog |
| 4 | 本体发现连接器扩展 | 已支持 OpenAPI/AsyncAPI JSON、GraphQL SDL、Protobuf、dbt manifest/catalog 和 Schema Registry JSON 导出；继续接入文档 SaaS、实时 Schema Registry、数据目录和运维元数据 | Connector Runtime 与 Source Evidence 模型 |
| 5 | Agent Tools 扩展 | 本体查询、代码分析、依赖分析、测试、扫描、制品和工单工具 | Harness Tool Gateway 与独立权限 |
| 6 | 统一监控台 | Agent/Skill/Tool/Connector/Workflow Trace、证据导航、成本、告警和运行控制 | 统一事件与 Trace 关联模型 |
| 7 | Factory Orchestrator 与本体模块治理 | 受限主控 Role/Skill、AgentPlan Schema、Typed Output、确定性校验、Workflow Run 绑定的不可变计划持久化、计划提交 API、本体模块清单 | assignment 级 Worker Task 实例化和动态阶段调度尚未接通；模块清单仍基于单一权威本体 JSON |

每个方向均需交付代码、Schema、单元与集成测试、运行说明、依赖更新、权限矩阵、监控指标和验收报告。跨模块能力按 ADR 管理。

## 13. 架构决策与变更管理

当前关键决策记录位于 docs/adr/，包括 MVP 边界、集成优先、受控工作流、JSON Schema 优先、本体/资产版本、Agent Role/Skill、Workflow 状态机、Worker 派发、Outbox/Inbox、LLM Provider 和 Agent Runtime 等决策。

新增组件、外部依赖、持久化技术、权限模型、执行隔离方式或服务边界时，应提交 ADR，说明背景、备选方案、选择理由、成本、风险、迁移策略和重新评估条件。架构变更同步更新机器可读基线、子系统分解、依赖清单、安装指南、验收矩阵和本说明书版本记录。

## 附录 A：主要源码模块索引

| 模块 | 文件 |
|---|---|
| Agent Runtime | agent_runtime.py、agent_models.py、agent_contracts.py、factory_orchestration.py、multi_agent_architecture.py、agent_workflow.py |
| Workflow/Worker | workflow_engine.py、workflow_store.py、task_runtime.py、integration.py |
| Ontology | ontology_runtime.py、semantics.py、ontology_discovery.py、ontology_discovery_service.py、ontology_discovery_worker.py、ontology_governance.py、ontology_versioning.py、ontology_modules.py |
| Catalog/Scope | catalog.py、scope.py、architecture_baseline.py |
| Connectors/Tools | source_connectors.py、remote_connectors.py、database_connectors.py、source_sync.py、source_webhooks.py、connector_catalog.py、tool_registry.py、adapters/* |
| Execution/Quality | workspace_execution.py、quality_gate.py、release_manager.py、e2e_delivery.py、production_pipeline.py |
| Observability | observability.py、runtime_observability.py |

## 附录 B：主要配置与契约目录

| 目录 | 内容 |
|---|---|
| ontology/ | 正式本体、候选 Schema、发现策略、消费者引用映射和逻辑模块清单 |
| contracts/schemas/ | Agent、Worker、Workflow、Factory Orchestrator Plan 和业务对象契约 |
| agents/roles/、agents/teams/ | Agent 角色和团队拓扑 |
| skills/ | Skill 定义、说明和 Schema |
| tools/registry.json、policies/ | 工具目录、权限矩阵、上下文和质量策略 |
| workflows/definitions/ | Workflow 定义与版本 |
| connectors/、config/integrations/ | 连接器描述和数据源配置 |
| catalog/ | 产品与组件资产目录 |
| runners/ | 受限执行器、容器构建定义和扫描规则 |
| observability/ | 成本费率示例与观测配置 |


## 14. 修订记录

| 版本 | 日期 | 修订内容 |
|---|---|---|
| 1.0 | 2026-10-30 | 建立系统现状、架构、组件、依赖、接口、安全和部署基线 |
| 1.1 | 2026-10-30 | 纳入 HarnessRuntime、SkillRegistry、ConnectorRuntime、API/事件契约解析器、Agent 元数据工具及 Portal 审计监控扩展 |
| 1.2 | 2026-10-30 | 纳入 Factory Orchestrator 受限规划角色、Skill、Plan Schema/Typed Output、确定性计划校验、本体 1.1.0 与 49 类/47 关系逻辑模块清单；明确 Workflow 运行时集成和独立模块发布仍未完成 |
| 1.3 | 2026-10-30 | 增加 Workflow Engine 的 AgentPlan 校验提交与 SQLite 不可变持久化，记录计划摘要和工作流事件，增加计划提交 API 与运行详情查询；assignment 级 Worker Task 实例化仍待完成 |
