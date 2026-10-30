# 软件工厂主控智能体与领域本体体系设计

| 文档属性 | 内容 |
|---|---|
| 文档编号 | OSF-ARCH-ONTOLOGY-001 |
| 版本 | 1.0 |
| 日期 | 2026-10-30 |
| 适用项目 | ontology-software-factory |
| 状态 | 架构设计基线，待 ADR 与分阶段实现 |
| 关联文档 | docs/system-design-specification.md、docs/ontology-design-and-evolution.md、docs/multi-agent-architecture.md、docs/connector-platform-and-ontology-ingestion.md |

## 1. 目的与结论

本文回答两个架构问题：软件工厂是否需要主控智能体；软件工厂应定义哪些本体，以及本体如何发现、评审、保存、使用、演进和退役。

核心结论：

1. 软件工厂需要一个逻辑上的主控角色（Factory Orchestrator），但不应将系统控制权交给一个不受约束的 LLM Agent。采用确定性控制平面、主控 Agent 和专业 Agent 分层协作。
2. 工作流引擎拥有流程状态权威性；Harness 拥有工具调用前的策略执行入口；策略与审批服务拥有授权决策；主控 Agent 负责计划与协调建议。任何 Agent 都不能绕过这些组件直接改变权威状态。
3. 软件工厂本体应分层建设：核心交付本体、生产运行本体、知识与治理本体、来源与证据本体、组织与策略本体。现有 software-factory-core ontology 已有 11 个核心交付类和一组 Agent/本体发现扩展类，应在此基础上渐进扩展，避免另起一套互不兼容的模型。
4. 本体发现结果必须先进入候选区。通过来源核验、结构和语义校验、Competency Questions、回归评测、影响分析和独立审批后，才能发布为正式版本。
5. 正式本体的权威版本应由 Git 版本化定义和发布清单管理；运行时数据库保存快照、候选、审批、运行绑定和事件；图数据库或图索引是可重建的查询投影，不应成为唯一权威源。

## 2. 设计目标与非目标

### 2.1 目标

- 为软件产品从需求到交付、部署、运维和升级提供统一语义。
- 让 Agent、Skill、Workflow、Tool、Connector、Runner、Artifact、Evidence 等对象可引用、可校验、可追踪。
- 支持跨产品复用核心概念，同时允许行业域、客户域扩展。
- 将代码、文档、数据库、API、事件、工单、运行系统中的知识转化为有来源、有版本、有审查记录的本体候选。
- 支持本体版本锁定、兼容性判断、消费者影响分析、迁移和回滚。
- 为知识图谱 UI、Agent 监控台、资产目录和质量治理提供统一对象 ID 与关系语义。

### 2.2 非目标

- 本体不替代 IAM、RBAC/ABAC、策略决策点、审批系统或数据库约束。
- 本体不直接授予 Agent 或用户任何工具权限。
- LLM 自动发现不等于自动发布；置信度、模型自评或单次 Benchmark 结果不构成发布授权。
- 不要求第一阶段引入完整 OWL 2 DL 推理机或独立图数据库集群。
- 不将所有客户业务数据、源文件正文、密钥和个人数据复制进全局本体仓库。

## 3. 主控智能体设计

### 3.1 是否需要主控 Agent

需要。软件工厂存在跨阶段目标分解、多个专业角色协调、结果汇总、异常处理和人工升级等任务。一个逻辑主控角色有助于保持全局目标、阶段边界和交付状态的一致性。

但主控 Agent 不应拥有全局无限权限，也不应自行维护唯一的系统状态。主控 Agent 是受控的计划与协调参与者，不是系统中的超级管理员。

建议命名：
- 产品/业务层：Factory Orchestrator（软件工厂主控智能体）
- 运行时组件：Orchestration Agent Adapter（主控 Agent 适配器）
- 权威流程组件：Workflow Engine（确定性工作流引擎）
- 执行治理组件：Harness Tool Gateway（Harness 工具网关）

### 3.2 分层控制架构

~~~mermaid
flowchart TB
  USER[用户 / 产品负责人 / 领域专家]
  PORTAL[Factory Portal / API]
  subgraph CP[确定性控制平面]
    INTAKE[需求规范化与范围校验]
    WF[Workflow Engine：状态、依赖、重试、暂停]
    POLICY[Policy Decision / Approval]
    HARNESS[Harness：上下文、预算、工具网关、审计]
    REG[Ontology / Skill / Tool / Connector Registry]
  end
  subgraph AGENTS[Agent 协作层]
    ORCH[Factory Orchestrator 主控 Agent]
    PLAN[需求与规划 Agent]
    ARCH[架构 Agent]
    DEV[实现 Agent]
    TEST[测试 Agent]
    SEC[安全 Agent]
    OPS[发布与运维 Agent]
    ONT[本体发现 / Critic Agent]
  end
  subgraph EXEC[受控执行层]
    TOOLS[Tool / Connector]
    RUNNER[Workspace / Runner]
    VERIFY[质量门禁与证据验证]
  end
  STORE[(状态库 / 证据库 / 版本化本体仓库)]
  USER --> PORTAL --> INTAKE --> WF
  WF <--> ORCH
  ORCH --> PLAN
  ORCH --> ARCH
  ORCH --> DEV
  ORCH --> TEST
  ORCH --> SEC
  ORCH --> OPS
  ORCH --> ONT
  AGENTS --> HARNESS
  HARNESS --> POLICY
  HARNESS --> REG
  HARNESS --> TOOLS --> RUNNER --> VERIFY
  WF --> STORE
  POLICY --> STORE
  VERIFY --> STORE
  REG --> AGENTS
~~~

控制权归属：

| 决策或状态 | 权威组件 | 主控 Agent 可做什么 | 禁止事项 |
|---|---|---|---|
| 需求范围与验收标准 | Requirement/Scope Validator + 人工确认 | 提炼需求、指出歧义、建议拆分 | 自行扩大已批准范围 |
| Workflow 状态 | Workflow Engine | 建议下一步、提交结构化计划 | 直接写状态库或跳过状态 |
| Agent 派发 | Workflow Engine / Task Runtime | 提议角色、Skill、依赖和并行组 | 任意创建无限任务或无限递归委派 |
| 工具权限 | Policy Decision + Harness | 请求工具调用并说明目的 | 自行授予权限、读取秘密或绕过网关 |
| 高风险审批 | 独立审批人/审批服务 | 提交审批材料、解释风险 | 自批、自生成审批凭证 |
| 质量结论 | 独立 Quality Gate | 汇总报告、提出修复建议 | 用自然语言声明替代机器证据 |
| 本体发布 | Ontology Governance | 提出变更、解释影响 | 直接覆盖正式版本 |
| 生产部署/回滚 | Release/Deployment Controller + 人工审批 | 准备执行计划 | 仅凭模型判断触发生产操作 |

### 3.3 主控 Agent 的职责

主控 Agent 的输入应包含：已批准需求、目标产品和版本、租户/项目边界、当前 Workflow 状态、可用 Agent/Skill/Tool 清单、本体快照 ID 与摘要、预算和截止时间、已有证据引用。

主控 Agent 的输出采用结构化 Plan，不接受自由文本作为执行指令。建议字段：

- planId、workflowRunId、goal、ontologyBinding；
- phases：阶段 ID、目标、输入引用、输出契约；
- assignments：roleId、skillId、taskContract、依赖、允许工具引用；
- joinPolicy：必需结果、独立验证要求、汇合条件；
- riskAssessment：风险等级、影响范围、需审批动作；
- budget：最大 Agent 数、轮次、工具调用、Token、时间；
- fallback：失败重试、替代角色、暂停或升级条件；
- acceptance：可机器验证的验收项及所需证据类型。

所有 plan 字段必须通过 Schema 和语义校验。Workflow Engine 依据批准后的 Plan 创建实际 Step/Task，并重新检查角色、Skill、工具、预算和策略约束。

### 3.4 主控 Agent 工作循环

1. 读取经授权的任务上下文和当前本体快照。
2. 检查需求是否完整，必要时向用户或领域专家提出澄清。
3. 生成有界任务计划，标明依赖、并行组、交付物和证据要求。
4. 将计划交给 Workflow Engine 校验和实例化。
5. 监控结构化状态和证据，不依赖 Agent 自报进度作为唯一事实。
6. 对失败进行分类：可重试、需要修复、策略拒绝、预算耗尽、外部依赖故障、人工决策。
7. 在允许的修复次数内重新规划；超过预算、出现冲突或高风险事项时暂停并升级。
8. 汇总独立验证结果，向用户提供交付状态、证据和已知限制。

### 3.5 多主控与多项目

第一阶段采用每个 Workflow Run 一个逻辑主控 Agent 实例；可以并行运行多个项目，但各 Run 独立绑定 tenantId、projectId、ontologySnapshotId、budget 和 policy context。

跨项目的工厂级治理由确定性服务和授权管理员负责。未来可增加 Factory Supervisor（跨项目运营分析角色），只提供容量、成本、队列和风险建议，不直接操作客户项目资源。

### 3.6 失败与安全策略

- 主控 Agent 超时或崩溃：Workflow Engine 保留状态，按幂等键恢复或重新创建主控任务。
- 主控输出非法：拒绝计划，不创建执行任务。
- 主控重复派发：由 Workflow/Task 的唯一键、状态机和 attempt fencing 防止重复生效。
- 主控与专业 Agent 冲突：提交冲突对象和证据，按预设优先级或人工评审解决，不通过“投票”覆盖安全策略。
- 预算超限：Harness/Workflow 停止派发并记账。
- 权限拒绝：拒绝是终态或显式待审批状态，不能由主控自动重试绕过。
- 主控 Agent 不可修改自身角色、策略、预算上限、审批人或本体发布权限。

## 4. 软件工厂本体体系总览

建议采用“核心本体 + 扩展本体 + 客户/行业域本体”的模块化结构。每个本体模块独立版本化，通过稳定 ID 和显式依赖组合。

### 4.1 本体分层

| 层 | 本体模块 | 核心职责 | 优先级 |
|---|---|---|---|
| L0 | Foundation & Governance Ontology | 稳定 ID、版本、租户/项目引用、来源、生命周期、分类、所有权 | P0 |
| L1 | Product & Delivery Ontology | 产品、需求、组件、版本、构建、测试、漏洞、制品、发布、部署、事件 | P0（已有基础） |
| L1 | Agent & Workflow Ontology | 团队、角色、主控 Agent、任务、交接、计划、Workflow、Step、事件、预算 | P0（部分已有） |
| L1 | Tool & Integration Ontology | Tool、Connector、Adapter、MCP Server、API、数据源、凭据引用、操作、副作用 | P0 |
| L1 | Skill & Knowledge Ontology | Skill、输入输出契约、知识资产、提示模板、评测集、模型配置 | P1 |
| L1 | Quality & Security Ontology | 测试策略、质量门禁、风险、漏洞、合规控制、审批、例外 | P0 |
| L1 | Evidence & Provenance Ontology | 来源、观察、证据、摘要、报告、审查决定、可追溯关系 | P0 |
| L1 | Runtime & Operations Ontology | Run、Trace、Span、日志、指标、告警、事故、SLO、成本、容量 | P1 |
| L1 | Asset & Supply Chain Ontology | 软件资产、制品库、依赖、许可证、SBOM、来源证明、兼容性 | P1 |
| L2 | Industry / Customer Domain Ontology | 客户业务对象、流程、规则、术语、行业事件 | 按项目启用 |
| L2 | Organization Ontology | 组织、团队、人员、服务所有者、责任矩阵 | P1；敏感数据隔离 |

### 4.2 核心类清单

以下清单是目标语义模型，不代表所有类已在当前代码中实现。当前 ontology/software-factory-ontology.json 已有 Requirement、Product、Component、Version、Artifact、Build、TestRun、Vulnerability、Release、Deployment、Incident 等 11 个核心交付类，并有 Agent 协作和本体发现相关扩展类。应保留其稳定语义，分批补齐下列对象。

#### A. Foundation & Governance

- OntologyModule：本体模块及其依赖。
- OntologyClass、OntologyProperty、OntologyRelation、OntologyConstraint：类、属性、关系和约束定义。
- OntologySnapshot、OntologyRevision、OntologyMapping：已发布快照、修订和映射。
- Tenant、Project、Environment：隔离和部署上下文引用。
- Owner、Steward、DomainExpert：责任角色引用，不直接等同身份认证。
- Classification、RetentionPolicy、LifecyclePolicy：数据分类、保留和生命周期策略引用。
- ChangeRequest、ReviewDecision、ApprovalRecord：变更、审查和审批记录。

#### B. Product & Delivery

- Requirement、AcceptanceCriterion、Product、ProductVersion。
- Component、ComponentVersion、Dependency、CompatibilityRule。
- ArchitectureDecision、ArchitectureComponent、InterfaceContract、Configuration.
- Build、TestRun、Artifact、Package、SBOM、Vulnerability。
- QualityGate、GateDecision、Release、Deployment、Rollback、Incident。

#### C. Agent & Workflow

- Agent、AgentTeam、AgentRole、AgentInstance。
- FactoryOrchestrator：主控 Agent 的角色/实例语义。
- AgentPlan、PlanPhase、AgentTask、AgentAttempt、AgentHandoff、AgentResult。
- WorkflowDefinition、WorkflowRun、WorkflowStep、WorkflowEvent、JoinCondition。
- CoordinationDecision、Escalation、Budget、ExecutionPolicyBinding。

#### D. Skill & Knowledge

- Skill、SkillVersion、SkillDependency、SkillContract。
- PromptTemplate、KnowledgeAsset、ReferenceDocument、CompetencyQuestion。
- ModelProvider、ModelDeployment、ModelProfile、EvaluationDataset、EvaluationRun。
- Capability、RoleCapabilityBinding。

#### E. Tool & Integration

- Tool、ToolVersion、ToolInvocation、ToolResult。
- Connector、ConnectorVersion、ConnectorOperation、ProtocolAdapter。
- SourceSystem、SourceAsset、SourceSnapshot、SyncJob、SyncCursor。
- API、APIEndpoint、EventSchema、MessageType、DatabaseSchema、Table、Column。
- CredentialReference、SecretScope、NetworkEgressPolicy。
- MCPServer、MCPToolBinding。

#### F. Quality, Security & Governance

- TestSuite、TestCase、TestResult、SecurityScan、Policy、PolicyDecision。
- Risk、Threat、Control、Exception、ApprovalRequest、ApprovalDecision。
- IdentityReference、RoleBinding、PermissionGrant（仅用于描述引用关系，不作为权限引擎本身）。
- AuditEvent、RetentionRule、DataResidencyConstraint。

#### G. Evidence & Provenance

- SourceEvidence、EvidenceRecord、EvidenceBundle、EvidenceClaim。
- ContentDigest、SourceRevision、Observation、ExtractionRun。
- Candidate、CandidateRevision、CandidateDiff、ValidationReport、BenchmarkResult。
- ProvenanceLink、ReviewerComment、ApprovalBinding。

#### H. Runtime & Operations

- RuntimeRun、Trace、Span、LogRecord、Metric、Alert、SLO。
- Service、ServiceInstance、Environment、Resource、Capacity、CostRecord。
- Incident、ChangeEvent、DeploymentEvent、OperationalFeedback。

### 4.3 关键关系

关系应使用有类型的谓词，不以任意字符串表达关键业务语义。首批关系建议：

- Product contains Component；Component has ComponentVersion；ComponentVersion dependsOn ComponentVersion。
- Requirement targets Product；Requirement satisfiedBy Artifact/Release；AcceptanceCriterion verifiedBy TestResult。
- AgentTeam contains AgentRole；AgentRole uses SkillVersion；SkillVersion requires Capability。
- FactoryOrchestrator creates AgentPlan；AgentPlan decomposesInto PlanPhase；PlanPhase assigns AgentTask；AgentTask executedBy AgentInstance。
- WorkflowRun instantiates WorkflowDefinition；WorkflowRun contains WorkflowStep；WorkflowStep dispatches AgentTask；WorkflowStep dependsOn WorkflowStep。
- AgentTask invokes ToolInvocation；ToolInvocation uses ToolVersion and ConnectorOperation。
- ToolInvocation authorizedBy PolicyDecision；highRiskInvocation requires ApprovalBinding。
- Build produces Artifact；TestRun validates Build/Artifact；QualityGate evaluates EvidenceBundle；GateDecision permits CandidatePromotion。
- Connector scans SourceSystem；ExtractionRun observes SourceAsset；Candidate derivedFrom SourceEvidence。
- OntologyRevision supersedes OntologyRevision；OntologySnapshot implements OntologyRevision；Consumer dependsOn OntologySnapshot。
- Deployment deploys Release；RuntimeRun produces Trace；Incident affects Service/Deployment；OperationalFeedback proposes OntologyChange。

关系定义必须补充 domain、range、cardinality、inverse（如适用）、约束、来源及是否允许跨租户引用。

## 5. 本体建模规则与技术表达

### 5.1 稳定标识

- 类、关系、属性和实例使用稳定 URI/ID；展示名称、别名可修改。
- 推荐命名空间：sf:（工厂核心）、sf-agent:、sf-ops:、sf-evidence:、industry:<domain>:、customer:<tenant>:。
- 实例 ID 不应由可变名称拼接；使用 UUID/ULID 或受控业务键。
- 每个对象至少具备 id、type、schemaVersion、ontologyBinding、createdAt、updatedAt、ownerRef、sourceRefs（适用时）。

### 5.2 分层约束

- JSON Schema：验证单对象结构、字段类型、枚举和基本格式。
- 语义校验器：验证跨对象引用、基数、状态转换、版本兼容、租户/项目一致性和业务不变量。
- SHACL：适合未来对 RDF 图执行形状约束；可先在离线 CI 使用。
- OWL 2：用于需要形式化类层级、等价类、属性特征和推理的场景；不应为了“使用本体”而引入复杂推理依赖。
- SPARQL：当 RDF 图存储和查询需求明确后采用。
- Property Graph：可用于高交互关系探索、路径分析和运行拓扑可视化；图数据库的节点/边应从权威本体快照投影生成。

### 5.3 语义与权限隔离

本体描述“是什么、如何关联、处于什么业务状态、受到哪些规则约束”；策略系统判断“当前主体能否对特定资源执行特定操作”。ontology 中的 role、permission、approval 等对象仅表达治理事实和引用，不直接授予权限。

## 6. 本体自动发现与知识接入

### 6.1 数据源范围

| 来源类型 | 典型对象 | 主要抽取内容 | 接入方式与边界 |
|---|---|---|---|
| 代码仓库 | 源码、配置、接口、测试、依赖文件 | 类、模块、API、依赖、组件所有权、状态枚举 | Git/本地扫描；解析优先于执行，不运行不可信代码 |
| 文档库 | 需求、设计、ADR、SOP、规范 | 术语、定义、流程、规则、异常、责任 | 文档解析 + ACL 过滤 + 片段证据 |
| 数据库 | Schema、表、列、约束、视图 | 数据实体、属性、主外键、数据分类、血缘 | 只读元数据账户；默认不抽取业务行数据 |
| API 契约 | OpenAPI、GraphQL、Protobuf | 服务、操作、请求响应对象、类型关系 | 离线文件和受控 API；保留版本 |
| 事件契约 | AsyncAPI、Kafka Schema Registry | 事件、生产者、消费者、消息 Schema | 文件导入或只读 API；保留 subject/version |
| 工单与项目管理 | Jira、GitHub Issues、需求平台 | 需求、状态、角色、依赖、变更历史 | API 只读扫描，保留权限边界 |
| 资产与供应链 | 制品库、SBOM、许可证、CI | 组件、版本、依赖、构建来源、漏洞 | 读取元数据和签名证明 |
| 运行系统 | OpenTelemetry、Prometheus、Kubernetes、告警系统 | 服务、调用关系、指标、SLO、事故 | 只读观测数据；明确时间窗口和采样限制 |
| 组织与策略 | IAM、服务目录、策略库 | 团队、所有者、策略引用和责任 | 只读同步；敏感身份属性不进入通用图谱 |

### 6.2 发现流水线

~~~mermaid
flowchart LR
  SRC[Source Systems] --> ACL[授权范围与分类检查]
  ACL --> SYNC[Connector Scan / Snapshot]
  SYNC --> PARSE[解析与标准化]
  PARSE --> EXTRACT[术语 / 关系 / 状态 / 约束抽取]
  EXTRACT --> EVID[逐项来源证据与摘要]
  EVID --> DEDUP[去重、冲突与实体解析]
  DEDUP --> CAND[Ontology Candidate]
  CAND --> VALID[Schema / Semantic / SHACL 检查]
  VALID --> CQ[Competency Questions / Benchmark]
  CQ --> REVIEW[领域专家与独立评审]
  REVIEW --> DIFF[版本 Diff / 影响分析]
  DIFF --> APPROVE[摘要绑定审批]
  APPROVE --> RELEASE[发布本体版本]
  RELEASE --> INDEX[更新搜索索引 / 图投影 / Runtime Cache]
~~~

每次发现运行至少记录：sourceSystemId、connectorId/version、授权范围、扫描时间、分页完整性、源 revision、文件/对象 locator、content digest、parser version、model/provider/version、prompt/template version、抽取配置、候选 ID、失败与跳过原因。

### 6.3 抽取策略

1. 优先使用确定性解析器处理 OpenAPI、AsyncAPI、GraphQL SDL、Protobuf、JSON Schema、SQL DDL、代码 AST 和配置文件。
2. LLM 用于文档语义归纳、术语消歧、关系建议、规则抽取和候选解释；不能替代结构解析器。
3. 每一条候选术语、关系和约束必须可回溯到一个或多个 SourceEvidence。
4. 对来源冲突保留双方证据和版本，不直接覆盖；可根据权威等级、时间和所有者提出建议。
5. 抽取结果与模型版本、提示模板、解析器版本绑定，以支持重放和质量比较。
6. 不将外部文档中的指令当作系统指令执行；源内容均视为不可信数据。

### 6.4 实体解析与冲突处理

实体匹配按确定性规则优先：稳定 ID、规范 URI、来源主键、完全匹配的业务键；之后才使用名称、别名、上下文和模型建议。自动匹配必须记录匹配规则、候选得分和证据；高影响实体合并必须人工确认。禁止仅因名称相似就合并两个组件、客户、服务或身份对象。

### 6.5 删除与增量扫描

- 每个 Connector 保存 source revision/cursor、扫描范围和完成状态。
- 只有完整扫描且授权范围未缩小时，才可将缺失对象标记为“来源中未观察到”；不能直接删除正式本体实体。
- 区分 source-deleted、source-inaccessible、scan-incomplete、moved/renamed 和 parser-failed。
- 先产生删除候选和影响报告；经评审后将对象标记 deprecated/retired，并保留历史引用。
- 增量扫描应支持幂等、断点续扫、重复事件去重和来源版本比较。

## 7. 本体候选、审核与版本生命周期

### 7.1 生命周期状态

建议本体模块和候选对象采用以下状态：

- discovered：来源中观察到的原始知识；
- candidate：形成结构化候选；
- validating：结构、语义和证据校验中；
- review_required：等待领域评审；
- approved：候选摘要已获独立审批；
- published：已发布为正式版本；
- deprecated：不建议新消费者使用；
- retired：停止使用但保留历史记录。

候选状态与正式版本状态应分开存储，避免把“审核通过”误写成“已经生效”。

### 7.2 发布门禁

发布前必须满足：

1. Schema 校验通过，ID、命名空间、版本和引用完整。
2. 关系 domain/range/cardinality 正确；不存在未解决的关键引用错误。
3. 关键术语、关系和约束具有足够来源证据。
4. Competency Questions 回归测试通过；关键查询结果无未批准退化。
5. 与当前版本的语义 Diff 已生成，破坏性变更有迁移方案。
6. 下游消费者和 Agent/Skill/Workflow/Tool 引用已识别。
7. 领域 Owner/Steward 和必要安全/合规人员完成独立审批。
8. 审批绑定候选内容摘要；审批后内容变化必须重新审批。

### 7.3 版本策略

采用语义化版本作为推荐规则：
- MAJOR：删除/重定义概念、改变关键关系语义、破坏消费者契约。
- MINOR：增加向后兼容的类、属性、关系或可选约束。
- PATCH：修正文案、别名、注释或不改变语义的元数据。

Schema Version 与 Ontology Version 分开管理。多个本体模块可以独立版本化，由 Ontology Release Manifest 锁定组合版本和依赖摘要。每个 Workflow Run 必须固定 ontologySnapshotId、ontologyVersion、schemaVersion 和 digest，执行期间不得静默切换。

### 7.4 迁移、回滚与兼容

- 发布前生成旧版到新版的 mapping/migration plan。
- 对已运行的 Workflow 保留原快照；新 Run 使用新发布版本。
- 兼容性报告列出消费者、字段映射、关系变更和潜在失效任务。
- 回滚通过重新激活历史发布清单完成，不删除新版本和审批记录。
- 无法自动迁移的对象进入人工处理队列。
- 外部图索引、搜索索引和缓存都可从发布快照重建。

## 8. 保存、查询和运行时使用

### 8.1 权威存储分工

| 数据类型 | 建议权威存储 | 用途 |
|---|---|---|
| 本体模块定义、Schema、词汇表、约束、Competency Questions | Git 版本库 | 审查、分支、Diff、发布 Tag |
| 发布清单、签名/摘要、依赖锁 | Git Release + 制品库 | 确定可重现的本体组合 |
| 候选、扫描任务、审批、状态和事件 | 事务型关系数据库 | 并发状态管理、审批和审计 |
| 来源正文和原始文件 | 原系统或受控对象存储 | 避免不必要复制；保留 ACL 与数据驻留要求 |
| 来源证据片段及摘要 | 受控证据库 | 引用定位、完整性核验、访问控制 |
| 图查询投影 | 图数据库/图索引 | 关系探索、路径查询、UI 可视化 |
| 全文/向量检索索引 | 搜索服务 | 术语检索、文档召回；可从权威数据重建 |
| Run 级绑定与缓存 | Workflow Store / Runtime Cache | 固定快照，避免执行期间语义漂移 |

当前 MVP 可继续使用 Git + JSON/JSON Schema + SQLite。随着并发、租户和审计要求增长，再引入 PostgreSQL、对象存储、图查询服务和事件总线。不要在第一阶段把图数据库设为唯一事实源。

### 8.2 本体在运行时的使用路径

- Requirement Intake：解析需求术语、目标产品、约束和验收标准。
- Planner：查询产品、组件、能力、Skill、Workflow 模板和兼容规则。
- Agent Runtime：把本体快照摘要绑定到任务输入、输出契约和 Evidence。
- Harness：读取角色、工具、数据分类和策略引用；授权仍由策略服务判断。
- Tool/Connector：将外部 API、事件、数据库 Schema 映射到标准对象。
- Quality Gate：按本体定义的验收对象、关系和不变量验证候选。
- Release Manager：关联 Requirement、Artifact、Build、TestRun、GateDecision 和 Release。
- Observability：按 Agent/Skill/Tool/Connector/Run/Trace/Cost 关系聚合运行数据。
- Ontology Workbench：显示类、关系、来源、版本 Diff、消费者和审批历史。

### 8.3 图谱 UI 与监控台

图谱工作台至少支持：
- 按本体模块、类、来源、租户/项目和版本筛选；
- 类/关系详情、属性、约束、反向关系和实例计数；
- 来源证据抽屉：来源系统、路径/对象 ID、revision、摘要、定位片段；
- 候选与正式版本叠加比较、差异高亮和冲突视图；
- 影响分析：下游 Role、Skill、Workflow、Tool、Connector、Schema 和项目；
- 审批状态、发布历史和回滚入口；
- 大图按需展开、邻居查询和路径查询，避免一次性渲染全部节点。

Agent 监控台应将 Run、Plan、Phase、Task、Attempt、Agent、Skill、ToolInvocation、Connector、Runner、Evidence、GateDecision 统一关联。时间线和 Trace 视图应从实际事件生成；不能用 Agent 自报文本伪造执行进度。图谱 UI 和监控 UI 共用语义 ID，但权限与数据范围按用户身份过滤。

## 9. 安全、隐私和合规边界

- 来源 Connector 使用只读身份，动作 Connector 使用独立凭据和独立审批。
- 证据记录优先保存 locator、revision、摘要和最小必要片段；受限内容通过原系统 ACL 获取。
- 本体默认不保存秘密值、访问令牌、密码、完整个人资料或不必要的客户业务明细。
- 租户和项目边界必须在查询、缓存、索引、图投影和证据读取全链路执行。
- 数据驻留、保留期限、删除请求和审计要求由数据治理策略执行；本体仅引用策略。
- Prompt injection 和恶意内容作为源数据处理，不能覆盖系统/开发者指令或触发工具执行。
- 跨租户共享概念应采用去标识化的通用定义；客户实例和证据默认隔离。
- 图数据库与向量索引必须支持按租户/项目过滤，且不能因缓存键缺失导致跨域泄露。

## 10. 现有实现映射与差距

基于当前仓库设计资产和已知实现状态：

| 能力 | 当前基础 | 目标差距 |
|---|---|---|
| 核心交付本体 | 11 个核心类、关系、受控词汇和不变量 | 产品版本、架构决策、接口契约、供应链等需逐步补齐 |
| Agent/本体发现扩展 | AgentTeam、AgentRole、Skill、AgentTask、AgentHandoff、AgentResult、CoordinationDecision、OntologyCandidate/Evidence/Evaluation/Approval/Revision 等 | 缺少统一主控 Agent/Plan/Phase/Attempt 与完整执行关系 |
| 本体校验 | JSON Schema、跨对象语义校验、消费者引用检查 | 需扩展模块化本体依赖、关系基数和 Competency Question 回归 |
| 版本治理 | 快照、摘要、结构 Diff、消费者影响分析、摘要绑定审批基础 | 发布清单、签名、迁移计划、模块依赖锁和自动回滚流程需加强 |
| 自动发现 | 本地目录、数据库 Schema、Git 元数据、OpenAPI/AsyncAPI/GraphQL/Protobuf/dbt/Schema Registry 离线导入；NVIDIA/Cognee 适配器基础 | 企业文档、工单、实时事件源、增量游标、完整删除检测和统一 Connector Runtime 集成仍需推进 |
| 候选治理 | 来源证据、Critic、Benchmark、人工审批提案 | 证据覆盖阈值、冲突队列、来源权威级别和回归门禁需统一 |
| 图谱呈现 | Portal 已有本体关系图原型和候选证据视图 | 需多模块浏览、版本 Diff、影响路径、大图性能和完整权限过滤 |
| 主控智能体 | 现有 Agent Team、Workflow 和主控相关协调基础 | 尚需定义 Factory Orchestrator 角色、Plan Schema、运行绑定和失败恢复闭环 |
| Harness 集成 | 本地 HarnessRuntime 已提供上下文、预算、工具授权和审计能力 | 需成为 Agent Runtime 默认 Tool Gateway，并关联 Workflow Run/Task/Trace |

以上状态区分设计定义与可运行能力。新增本体类或文档不代表对应运行时、UI 或外部连接器已经实现。

## 11. 分阶段实施路线图

### Phase 0：架构决策与模型基线

- 批准主控 Agent 与确定性控制平面的职责边界。
- 为 FactoryOrchestrator、AgentPlan、PlanPhase、AgentAttempt、OntologyModule、OntologyReleaseManifest 等对象补充 Schema。
- 建立本体模块命名空间、版本规则、稳定 ID 和依赖清单。
- 建立核心 Competency Questions 和语义回归集。

退出条件：设计评审通过；关键对象 Schema 可校验；不改变现有运行链路。

### Phase 1：主控 Agent 受控集成

- 新增 Factory Orchestrator Role/Skill/Plan Contract。
- 主控 Agent 只输出结构化 Plan。
- Workflow Engine 校验计划、生成 Step/Task，并负责状态转换。
- Harness Tool Gateway 统一拦截工具调用。
- 每个 Run 固定本体快照、Skill 摘要、预算和策略版本。
- 增加重复派发、越权、预算超限、主控超时、非法计划和审批不匹配测试。

退出条件：主控 Agent 不能绕过 Workflow/Harness；计划可重放；失败可恢复；全链路有审计。

### Phase 2：本体模块化与治理

- 将核心交付、Agent/Workflow、Tool/Connector、Evidence/Governance 模块化。
- 增加模块依赖和发布清单。
- 统一候选、差异、影响分析、审批与发布状态机。
- 建立术语/关系/约束回归测试。
- 运行时消费者锁定本体组合版本。

退出条件：发布可复现；破坏性变更有影响清单和迁移计划；旧 Run 不受新版本影响。

### Phase 3：增量发现与来源治理

- Connector 统一输出 SourceSnapshot、SourceEvidence 和 ExtractionRun。
- 实现 cursor、增量 diff、分页完整性、删除候选和冲突队列。
- 增加文档库、工单、实时事件和数据目录连接器。
- 支持规则解析 + LLM 抽取混合流水线。
- 评估 Cognee/图数据库作为派生索引的价值，保留 Git/发布清单权威源。

退出条件：来源可追踪；扫描不完整不会误删；候选能重放；跨租户隔离通过测试。

### Phase 4：图谱工作台与运行监控

- 本体图谱按模块/版本/来源展示。
- 支持差异、冲突、证据和消费者影响分析。
- Agent 监控台关联 Plan/Task/Attempt/Tool/Runner/Evidence/Trace。
- 支持失败定位、成本归因和运行控制（暂停/取消/重试需权限与审计）。

退出条件：从一次交付 Run 可追踪到需求、本体版本、Agent 计划、工具调用、质量证据和最终制品。

## 12. 建议的关键验收场景

1. 用户提交跨多个组件的需求，主控生成结构化计划，Workflow 校验并创建有界任务。
2. 某专业 Agent 请求未授权工具，Harness 拒绝并生成审计记录；主控不能改变拒绝结果。
3. Skill 在 Run 创建后被修改，运行时仍使用锁定版本，或按明确策略拒绝执行过期摘要。
4. 本体新版本改变 Component/Version 关系，影响分析列出所有 Role、Skill、Workflow 和 Tool 消费者。
5. Connector 扫描中途失败，不将未观察到的来源对象误判为已删除。
6. LLM 提出新术语但无来源证据，候选不得进入审批通过状态。
7. 候选经人工批准后内容摘要发生变化，原审批自动失效。
8. 新本体发布后，已有 Run 仍绑定原快照，新 Run 使用新版本。
9. 图谱 UI 显示来源证据和版本差异；无权用户不能通过图查询、搜索或缓存访问其他租户数据。
10. 端到端 Run 可追踪需求、Plan、Task、Agent、Skill、Tool、Connector、Runner、Evidence、Gate、Approval 和 Artifact。

## 13. 建议新增或更新的仓库资产

建议按实施阶段新增，不要求本次一次性落地全部代码：

- ontology/modules/foundation-governance.json
- ontology/modules/product-delivery.json
- ontology/modules/agent-workflow.json
- ontology/modules/tool-integration.json
- ontology/modules/evidence-provenance.json
- ontology/modules/quality-security.json
- ontology/releases/manifest.schema.json
- contracts/schemas/factory-orchestrator-plan.schema.json
- contracts/schemas/ontology-module.schema.json
- contracts/schemas/ontology-release-manifest.schema.json
- agents/roles/factory-orchestrator.json
- skills/factory-orchestration/skill.json
- workflows/definitions/factory-orchestration-v1.json
- docs/adr/ADR-XXXX-factory-orchestrator-control-boundary.md
- docs/adr/ADR-XXXX-modular-ontology-authority-and-storage.md

目录名称和对象字段应先与现有 Schema、Ontology Runtime、Workflow Engine、Portal API 对齐，再创建文件，避免重复定义和双重事实源。

## 14. 架构决策建议

建议批准以下决策作为后续 ADR 的初稿：

- ADR-A：采用“确定性控制平面 + 主控 Agent + 专业 Agent”的分层控制架构。
- ADR-B：Workflow Engine 拥有 Run/Step 状态权威性；Agent 只能提交结构化计划和结果。
- ADR-C：Harness 是 Agent 工具调用的强制中介；权限由策略层决定，审批独立于 Agent。
- ADR-D：采用模块化本体，Git 发布清单为正式语义版本权威；运行时 DB 保存状态，图数据库为派生投影。
- ADR-E：本体自动发现只生成候选；所有正式变更经过证据校验、回归、影响分析和摘要绑定审批。
- ADR-F：每个 Workflow Run 固定本体、Skill、Workflow、Tool/Connector 版本或摘要，禁止运行期间静默漂移。

## 15. 结语

软件工厂需要一个能理解整体目标并协调专业 Agent 的主控角色，也需要一套贯穿需求、研发、验证、交付和运营的统一领域语义。主控 Agent 提供灵活规划能力；确定性控制平面提供可验证的执行边界；模块化本体提供跨组件、跨流程和跨项目的语义基础。三者共同构成可治理、可追溯、可持续演进的软件工厂架构。
