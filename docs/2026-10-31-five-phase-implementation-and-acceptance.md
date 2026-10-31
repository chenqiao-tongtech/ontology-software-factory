# 软件工厂五阶段实施与验收基线

> 日期：2026-10-31  
> 仓库：chenqiao-tongtech/ontology-software-factory  
> 基线：main 分支 2026-10-30 最新可见提交；本文件所在工作分支为增量交付分支。  
> 定位：本地 MVP / 工程参考实现，不等于生产级企业软件工厂。

## 0. 实施原则与状态口径

本文件将五阶段工作统一到一条工程主线：先统一运行时控制面，再完成本体与图谱平台，再统一 Agent 可观测性，然后打通真实交付闭环，最后建设企业级生产治理。

状态定义：

- **已有基础**：仓库中存在相关代码或 UI；不代表已通过当前提交的全量测试。
- **部分打通**：至少有一个可运行链路，但仍有关键路径、持久化或外部服务边界。
- **待实施**：缺少关键服务、控制面、部署能力或验收证据。
- **外部验收**：需要真实 Provider、数据库、Git 平台、容器运行时或企业基础设施；本地 Fixture / Mock 不构成证明。

本轮只将能够由仓库代码与文档支持的内容列为已有能力。不得将设计文档、UI 页面、Mock 测试或配置样例当作生产集成证明。

## 1. 五阶段总览

| 阶段 | 目标 | 核心系统边界 | 退出条件 |
|---|---|---|---|
| P1 统一运行时与治理控制面 | Agent、Workflow、Tool、Policy、Evidence 使用同一运行身份与版本锁 | Harness / Runtime Contract / Tool Gateway / Run Store | 所有 Agent 工具调用经统一授权入口；运行版本锁可验证；事件与证据可追溯；拒绝路径有测试 |
| P2 本体与知识图谱平台 | 本体从静态文件升级为可发现、可评审、可查询、可发布的治理资产 | Source Connectors / Discovery / Ontology Registry / Graph Workbench | 来源证据可追溯；候选审批与快照版本化；结构 Diff 和消费者影响分析可区分；图谱与正式版本一致 |
| P3 多 Agent 监控与协作 | 从孤立控制台变成统一 Run Command Center | Agent Run / Workflow Run / Task / Handoff / Tool Call / Evidence | 拓扑、时间线、任务交接、重试、审批、预算和错误均来自真实运行存储；Fixture 和 Live 模式明显区分 |
| P4 真实软件交付闭环 | 将候选代码/制品推进到受控 PR、CI、扫描、签名、发布和部署反馈 | Workspace / Git Adapter / CI Adapter / Quality Gate / Artifact Store / Release | Gate 绑定同一源码摘要；真实 CI 状态可追溯；审批和发布状态机有效；失败可回滚或阻断 |
| P5 生产部署与企业治理 | 支持多用户、多租户、多节点和可恢复运行 | IAM / PDP / Secret Broker / Distributed Store / Scheduler / OTel / Backup | 身份、权限、密钥、隔离、审计、监控、备份恢复均有环境级验收证据 |

## 2. P1：统一运行时与治理控制面

### 2.1 目标架构

~~~text
Portal / API
   |
Run Controller ---- Runtime Contract Lock
   |                  | ontology snapshot digest
   |                  | workflow definition digest
   |                  | role / skill digests
   |                  | tool policy digest
   v
Workflow Engine <----> Task Runtime / Worker
   |
Agent Runtime
   |
Harness Context + Budget + Approval + Audit
   |
Tool Gateway (default deny)
   |
Registered Tool Adapter / MCP / HTTP
   |
Evidence Store + Event Ledger
~~~

### 2.2 当前仓库资产

- src/ontology_software_factory/harness.py：HarnessPrincipal、HarnessBudget、上下文控制、工具调用入口、预算和审计。
- src/ontology_software_factory/tool_registry.py：默认拒绝的工具注册表，合并 Role 声明、Policy 和实际 Handler。
- src/ontology_software_factory/ontology_runtime.py：本体快照校验、Role/Skill 合约校验和 Runtime Contract Lock。
- src/ontology_software_factory/agent_runtime.py：OpenAI Agents SDK 适配器，工具调用要求活动 Harness Context。
- src/ontology_software_factory/task_runtime.py：SQLite 任务队列、幂等键、租约、心跳、重试、超时、Evidence Contract。
- src/ontology_software_factory/workflow_store.py：Workflow Run、事件和持久化状态。
- policies/tool-permissions.json、policies/context-policy.json：工具与上下文策略。

### 2.3 本阶段需要完成的工程闭环

1. **统一身份对象**：Run、Task、Agent、Tool Invocation 全部携带 runId、taskId、tenantId、projectId、principalId、roleId；缺失身份时默认拒绝。
2. **唯一 Tool Gateway**：Agent Runtime、Workflow Handler、MCP、HTTP 和 Portal 动作不得自行绕过 Harness 调用高风险 Handler。注册表只允许可信代码注入 Handler，模型输出不能选择 Python 函数或 Shell 命令。
3. **统一授权决策**：合并 Role、Tool Registry、Policy、环境、资源范围和审批记录；生产写操作需要独立审批，Agent 不得自批。
4. **运行契约锁**：Run 创建时固定 Ontology Snapshot、Workflow、Role、Skill、Tool Policy 的摘要；每次执行前验证摘要，漂移时 fail closed。
5. **预算与取消**：统一工具调用、上下文字节、输入/输出 Token、时间、并发和费用额度；真实 usage 缺失时保留 unknown，不估算。
6. **生命周期事件**：Run、Task、Handoff、ToolInvocation、Approval、Evidence 的创建/开始/完成/失败/取消都产生幂等事件。
7. **Evidence Contract**：Evidence 至少绑定 runId、taskId、sourceTreeDigest 或 inputDigest、toolId/version、开始/结束时间、退出码、报告摘要和状态。
8. **兼容旧 Run**：无版本锁的历史 Run 只能进入显式兼容/只读路径，不允许默认为当前策略版本继续执行。

### 2.4 P1 验收

- 任一 Agent Tool Invocation 可追溯到唯一 Run、Task、Role 和策略摘要。
- 禁止工具、缺少审批、策略摘要变化、跨租户引用、预算耗尽均拒绝执行。
- 重复请求使用相同幂等键时不会重复产生外部副作用。
- Run 取消后不再派发新 Task；已运行工具按可取消能力明确记录最终状态。
- Evidence 与对应输入摘要一致，不能复用其他 Run 的旧报告。
- 单元/契约/集成测试覆盖 allow、deny、approval、drift、timeout、retry、duplicate 和 cancellation。

### 2.5 尚未达到的边界

当前 Harness、Tool Registry、Runtime Contract Lock 已有本地实现，但不能据此认定所有 Provider、Agent Framework、MCP Server、Workflow Handler 和 Portal 写操作都已统一经过控制面。SQLite 单机预算账本也不是分布式预算服务；本地 actor 字段不是企业身份认证。

## 3. P2：本体与知识图谱平台

### 3.1 目标架构

~~~text
Source Systems
  | local repo / GitHub / GitLab / docs / SQLite / PostgreSQL / MySQL
  v
Source Connector Registry
  | bounded read-only scan / sync cursor / source identity
  v
Asset Inventory + Provenance Evidence
  |
  v
Ontology Discovery (rules + optional LLM + independent critic)
  |
  v
Candidate Registry
  | schema / evidence / evaluation / conflicts
  v
Review & Approval
  |
  v
Ontology Registry (immutable snapshots + semantic versions)
  |                         |
  v                         v
Graph Projection        Dependency Index
  |                         |
Graph Workbench         Impact Analysis
~~~

### 3.2 当前仓库资产

- ontology/software-factory-ontology.json、ontology/module-manifest.json。
- src/ontology_software_factory/ontology_discovery.py、ontology_discovery_service.py、ontology_discovery_worker.py。
- src/ontology_software_factory/source_connectors.py、source_sync.py、source_webhooks.py。
- src/ontology_software_factory/database_connectors.py、remote_connectors.py。
- src/ontology_software_factory/ontology_versioning.py、ontology_governance.py、ontology_modules.py。
- apps/factory-portal/ 与 docs/ontology-graph-workbench.md。
- 相关测试：test_source_connectors.py、test_ontology_discovery.py、test_ontology_versioning.py、test_ontology_governance.py、test_remote_database_connectors.py。

### 3.3 本阶段需要完成的工程闭环

1. **连接器统一**：本地目录、GitHub/GitLab、SQLite、PostgreSQL、MySQL 都使用统一 Source Connector 接口；明确同步游标、分页、限额、错误分类和健康状态。
2. **证据不可伪造**：本地文件内容可提供 SHA-256；远端只读元数据不能伪造文件内容 hash；SQL 连接只采集 Schema 元数据，不读取业务行。
3. **候选治理**：候选术语、关系、约束和 competency questions 必须关联来源 locator、source revision、采集时间、内容摘要（可用时）、提取器版本和模型/Prompt 元数据。
4. **人工审批**：候选与正式本体分离；审批人、发布人和提案者职责分离；所有变更形成 Revision 和 Snapshot。
5. **版本发布**：快照内容不可变，版本号与 digest 同时存在；支持 Diff、兼容性检查、弃用标记和显式回滚提案。
6. **消费者索引**：建立 Agent Role、Skill、Workflow、Tool、API Contract、Event Schema 对本体类/关系的稳定引用索引；将本体结构影响与消费者影响分别报告。
7. **图谱投影**：图谱展示必须绑定正式本体快照或明确标注候选版本；节点、关系、证据和消费者可互相导航。图数据库可作为投影/查询层，不可在未定义同步一致性前成为第二个权威源。
8. **查询接口**：支持按概念、关系、来源、版本、状态、消费者查询，并对大图采用按需加载和分页。

### 3.4 P2 验收

- 任一候选术语/关系可回到来源文件或 Schema 字段定位。
- Source scan 为 partial 时，不将未扫描到的资产判定为已删除。
- 远端 repository tree revision 变化时标记需复核，不冒充文件内容变化。
- 图谱边详情可显示关系名、源/目标、字段、基数和校验规则。
- 两个快照 Diff 能列出类、关系、词汇、不变量变更。
- 消费者影响分析只返回实际索引到的 Role/Skill/Workflow/Tool/Contract，不根据猜测补齐。
- 候选不能直接覆盖正式本体；未审批发布必须失败。

### 3.5 尚未达到的边界

当前已有多类连接器和本体工作台基础，但同步历史仍是本地可修改状态，缺少生产凭据保险库、OIDC、租户授权、强制网络出口策略、持久化注册中心、签名快照和大规模图谱协作编辑。数据库适配器的单元测试不等于真实服务器 TLS/权限验收。

## 4. P3：多 Agent 监控与协作中心

### 4.1 目标视图

- **Topology**：主控 Agent、专业 Agent、Workflow、Task、Tool 和依赖关系。
- **Timeline**：Run 阶段、Task 开始/结束、Handoff、Approval、Retry、Tool Invocation。
- **Task Board**：队列、租约、Worker、尝试次数、等待原因、超时和死信。
- **Evidence Drawer**：输入摘要、输出摘要、工具报告、退出码、证据链接；不展示隐藏思维链。
- **Budget Panel**：Provider、模型、Token、延迟、工具调用数、已配置费率下的费用；费率未知时显示未知。
- **Human Control**：暂停、取消、审批、拒绝、重试和恢复；每个动作记录独立 actor、原因和审计事件。

### 4.2 当前仓库资产

- src/ontology_software_factory/agent_workflow.py、task_runtime.py、workflow_engine.py、workflow_store.py。
- src/ontology_software_factory/runtime_observability.py、observability.py。
- apps/agent-workflow-console/、apps/ai-runtime-console/、apps/workflow-console/、apps/worker-console/、apps/integrated-console/。
- SQLite workflow store、worker_tasks、workflow_events 及 Harness usage ledger。

### 4.3 本阶段需要完成的工程闭环

1. 统一运行对象 API：AgentRun、WorkflowRun、Task、Handoff、ToolInvocation、Approval、Evidence。
2. UI 只读投影与命令接口分离；查询接口不能触发重试、同步或外部动作。
3. 每条事件有稳定 eventId、occurredAt、runId、taskId、actor、action、schemaVersion 和幂等策略。
4. 将实时状态与历史事件分离，允许按 Run/Task 分页查询。
5. UI 显示真实 Provider/模型/usage/latency；Mock/Fake/Fixture 使用明显的 simulation 标识。
6. 隐藏思维链不进入监控 API；只记录必要的结构化摘要、工具元数据、错误和 Evidence。
7. 人工干预通过独立命令 API 执行，并校验当前状态、权限、审批和幂等键。

### 4.4 P3 验收

- 同一个 Run 的拓扑、时间线、Task 列表和 Evidence 引用一致。
- 重复事件不会重复累计 usage 或重复执行人工命令。
- 取消、超时、重试、dead-letter 和迟到结果有可解释状态。
- UI 能区分 live run、offline fixture、mock provider 和 historical record。
- 监控 API 不返回 Prompt 原文、隐藏思维链、原始密钥或不必要的敏感工具参数。
- 对每个失败节点可定位错误类别、attempt、日志/报告摘要和下一步允许动作。

### 4.5 尚未达到的边界

当前存在多个控制台和 SQLite 只读投影，但尚不等于统一实时 Command Center。没有可证明的多节点事件总线、OpenTelemetry Collector、集中日志、告警和跨租户成本归集。

## 5. P4：真实软件交付闭环

### 5.1 目标交付链

~~~text
Approved Requirement
   -> Agent Plan / Human Approval
   -> Isolated Workspace
   -> Git Branch / Commit / Pull Request
   -> CI Build + Test + SAST + SCA + Secret Scan
   -> Quality Gate (same source digest)
   -> Artifact Store + SBOM + Signature + Provenance
   -> Release Approval
   -> Staging Deployment
   -> Health Verification
   -> Production Approval / Deployment
   -> Runtime Feedback / Rollback
~~~

### 5.2 当前仓库资产

- src/ontology_software_factory/workspace_execution.py。
- src/ontology_software_factory/production_pipeline.py、quality_gate.py、release_manager.py、e2e_delivery.py。
- runners/restricted_runner.py、runners/container/。
- policies/quality/。
- .github/workflows/ci.yml。
- GitHub/GitLab 元数据连接器，但不是完整的 PR/CI 写操作连接器。

### 5.3 本阶段需要完成的工程闭环

1. Git Provider Adapter：只允许策略授权的分支创建、提交和 PR；保护分支合并必须保持禁止或独立审批。
2. CI Adapter：触发构建并记录 provider、pipeline ID、commit SHA、job 状态和报告引用；Webhook 需要签名验证和重放保护。
3. Source Digest Binding：所有测试、扫描、SBOM、Artifact 和 Gate 结果绑定同一 commit/tree digest；输入变化则旧 Gate 失效。
4. Scanner Evidence：Semgrep、Gitleaks、Trivy、SCA/License、容器/IaC 扫描统一结构；工具缺失、报告损坏、扫描超时为 incomplete/block。
5. Artifact Store：本地文件存储接口先行，再扩展 OCI Registry / Nexus / Artifactory / Object Storage；保存不可变摘要和保留策略。
6. Provenance：记录源码、构建器、依赖锁、构建参数、工具版本、SBOM、扫描报告、审批和签名。
7. Release State Machine：candidate、approved、staged、deployed、verified、rolled_back、rejected；状态转换由确定性服务控制。
8. Deployment Adapter：先 staging；生产环境默认禁用写操作，要求二次审批、变更窗口、健康检查、回滚策略和审计。

### 5.4 P4 验收

- 修改源码后，旧测试报告和旧 Gate 不得放行新提交。
- 质量报告与 commit/tree digest 完全匹配。
- 缺失扫描工具、缺失报告或无法解析报告时 fail closed。
- PR 创建、CI 触发、发布和部署均有独立审批与审计事件。
- 发布包 SHA-256 可复验；SBOM 与制品内容一致。
- Staging 部署失败时回滚演练可验证；Production 操作在未显式启用时不可执行。
- Kafka 示例仍明确为配置制品交付，不宣传为 Kafka 上游二进制构建或真实集群部署。

### 5.5 尚未达到的边界

现有 release_manager 是本地候选包、Manifest、SHA-256、配置范围 SBOM 和本地升级/回滚演练。它不等于完整上游依赖 SBOM、制品签名、OCI Registry、真实 CI/CD 或生产部署。Docker 测试执行器也不自动等于对抗性强隔离沙箱。

## 6. P5：生产部署与企业治理

### 6.1 目标部署拓扑

~~~text
Users / Enterprise IdP
       |
Ingress / WAF / API Gateway
       |
OSF API + Web Portal (stateless replicas)
       |
PDP / Policy Service ---- Secret Broker / KMS
       |
Distributed Workflow Scheduler + Worker Pools
       |
PostgreSQL HA / Event Store / Object Storage
       |
Artifact Registry / CI Providers / Graph Projection
       |
OpenTelemetry Collector -> Metrics / Logs / Traces / Alerts
       |
Backup / Restore / DR
~~~

### 6.2 目标能力

1. IAM/SSO：OIDC/SAML 登录、组织/项目/租户映射、角色和服务身份、短期凭据。
2. PDP：集中策略决策，按租户、项目、资源、工具、环境、风险和审批判断；默认拒绝。
3. Secret Broker：密钥引用、短期注入、轮换、吊销和审计；应用日志不得回显秘密。
4. Multi-tenancy：租户隔离的数据库行/Schema/实例策略、对象存储前缀、缓存命名空间、队列和 Worker 资源隔离。
5. Distributed Runtime：PostgreSQL 或等价持久化存储、分布式调度、并发租约、Outbox/Inbox、任务恢复和 Worker 水平扩展。
6. Observability：OpenTelemetry Trace/Metrics/Logs，Run/Task/Tool 的 trace correlation，SLO、告警和成本预算。
7. Network & Sandbox：出站 allow-list、DNS 防护、隔离容器或 microVM、资源限额、镜像签名和运行时策略。
8. Backup/DR：数据库备份、对象存储版本化、恢复演练、RPO/RTO 目标和故障演练。
9. Compliance：数据分类、保留期限、删除策略、审计导出、区域化部署和供应链风险管理。

### 6.3 P5 验收

- 未认证请求不能访问 Portal/API；租户 A 无法读取或修改租户 B 的对象。
- 用户、服务账号和审批身份可追溯，权限撤销在规定时限内生效。
- 密钥只通过 Broker 引用或短期注入，日志和 Evidence 不含明文秘密。
- 多节点并发下无重复发布副作用；任务租约过期后可恢复且有一致性审计。
- 备份恢复演练满足经业务方确认的 RPO/RTO。
- OTel Trace 能从 Run 关联到 Task、Tool Invocation、CI Job 和 Artifact。
- 生产部署需有隔离测试、安全评审和环境验收报告。

### 6.4 当前不能直接完成的项目

P5 依赖用户的目标云、身份提供商、密钥管理服务、网络架构、数据库服务、制品库、监控平台、数据驻留要求和 RPO/RTO。没有这些环境和凭据，仓库只能完成部署模板、接口和本地模拟，不能声称已完成企业级生产部署。

## 7. 五阶段共用的数据契约

所有核心对象必须具备稳定身份与来源关联：

| 对象 | 必备关联 |
|---|---|
| Run | runId、tenantId、projectId、ontologySnapshotId/digest、workflowDigest、policyDigest、createdBy |
| Task | taskId、runId、roleId、skillDigests、idempotencyKey、attempt、lease、status |
| ToolInvocation | invocationId、runId、taskId、toolId/version、policyDecision、approvalRef、inputDigest、outputDigest、status |
| Evidence | evidenceId、runId、taskId、sourceDigest、toolVersion、reportDigest、exitCode、status、createdAt |
| OntologyCandidate | candidateId、sourceRefs、extractor/model version、evidence、evaluation、candidateDigest、review state |
| OntologySnapshot | snapshotId、ontologyVersion、schemaVersion、digest、actor、reason、createdAt |
| Artifact | artifactId、sourceDigest、buildId、manifestDigest、sbomDigest、signatureRef、gateEvidenceRefs |
| Release | releaseId、artifactRefs、approvalRefs、environment、state、deploymentEvidenceRefs |

数据契约演进必须有 schemaVersion；兼容性变更必须说明迁移策略。跨租户引用必须在服务端授权层拒绝，不能只依赖前端过滤或本体 tenantId 字段。

## 8. 本轮实施顺序和工程交付

五阶段不是五个并行项目。建议按以下顺序逐步提交，每阶段可独立验收：

| 批次 | 交付内容 | 必须更新 |
|---|---|---|
| 1 | P1 统一身份上下文、Harness 入口覆盖、运行契约锁一致性、生命周期事件和拒绝路径测试 | 核心代码、Schema、负向测试、Runtime 文档 |
| 2 | P2 Source Connector 统一、Evidence 证据状态、Ontology Registry、依赖索引和 Graph Workbench | 连接器、治理服务、图谱 UI、集成测试 |
| 3 | P3 统一运行对象 API、时间线/拓扑/Task Board、预算和人工命令接口 | Portal API、控制台、事件 Schema、隐私测试 |
| 4 | P4 Git/CI/Artifact Adapter、摘要绑定 Gate、签名与发布状态机、Staging 适配 | Provider Adapter、Runner、Gate、E2E 测试 |
| 5 | P5 IAM/PDP/Secret Broker、分布式存储/调度、OTel、备份恢复部署模板 | 部署包、IaC、运维手册、安全和恢复验收 |

每批交付都必须包含：
- 新增/修改文件清单；
- 架构与数据契约变化；
- 配置项和依赖变化；
- 安装/升级/回滚说明；
- 单元、契约、集成和 E2E 测试；
- 已通过测试的运行证据；
- 未完成能力与外部环境前置条件。

## 9. 本轮仓库核查结论（2026-10-31）

本轮通过仓库目录、README、核心 Python 模块和 2026-10-30 阶段计划文档核查，确认五阶段均有部分基础模块。当前主要短板不是缺少概念文档，而是统一接口覆盖、真实外部环境验收和生产级治理。

- P1：本地 Harness、Tool Registry、Runtime Contract Lock 和 SQLite Task/Workflow Store 已存在；需要验证所有执行路径覆盖率和事件/Evidence 关联完整性。
- P2：本体发现、连接器、候选治理、快照、图谱 UI 已有基础；需要补足统一 Registry、显式消费者索引、持久化和真实连接验收。
- P3：已有多控制台和 SQLite 只读投影；需要统一对象 API、真实事件时间线、人工控制命令和 Live/Fixture 清晰分层。
- P4：已有受控工作区、质量门禁和本地候选交付；需要 Git PR、真实 CI、制品库、签名、真实 Staging/Deployment 闭环。
- P5：仍以单机、本地存储和可选外部组件为主；生产级 IAM、PDP、Secret Broker、分布式调度、HA、OTel 和灾备均需部署级工程与外部验收。

### 9.1 验收命令

~~~bash
python -m pip install -e .
make validate
make test
~~~

按环境启用可选集成时，另行安装：
- Agent Runtime：python -m pip install -e '.[agent-runtime]'
- PostgreSQL：python -m pip install -e '.[postgres]'
- MySQL：python -m pip install -e '.[mysql]'

需要 Docker 的受控测试和扫描按 docs/controlled-workspace-execution.md 的环境变量及镜像要求执行。真实 Provider、数据库和 Git 服务必须用隔离测试账户单独验收。

**本文件是五阶段统一实施与验收基线，不是五阶段全部完成的证明。** 阶段完成必须以对应代码、测试运行记录和外部环境证据为准。
