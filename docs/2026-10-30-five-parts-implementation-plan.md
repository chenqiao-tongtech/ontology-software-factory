# 五个重点功能的仓库审查与实施计划（2026-10-30）

> 本文基于 GitHub `main` 分支在 2026-10-30 的实际目录树、文件内容与最近提交进行审查。它记录的是代码仓库可见事实，不把此前会话中的测试结果自动视为当前分支的验收结果。

## 1. 本次审查基线

- 仓库：`chenqiao-tongtech/ontology-software-factory`
- 审查分支：`main`
- 审查提交：`09a62860de5f540fb73259156271a0bfafd44f52`
- 新工作分支：`work/five-parts-implementation`
- 当前项目定位仍应是本体驱动的软件工厂参考实现 / 本地 MVP；不能宣称已具备生产级企业接入、真实 Agent 执行沙箱或生产部署能力。

### 1.1 基线核查与后续修复

初次审查时，`main` 提交 `09a62860de5f540fb73259156271a0bfafd44f52` 缺少若干 Makefile / README / 测试引用的 CLI 与 Portal 入口。审查期间，仓库所有者又于 2026-10-30 上传了提交 `fc4c79a9465e3e4665eb5aaca5f7f702fbca9858`，新增了以下入口：

- `scripts/run_factory_portal.py`
- `scripts/check_mvp_scope.py`
- `scripts/validate_asset_catalog.py`
- `scripts/validate_domain_model.py`
- `scripts/validate_multi_agent_architecture.py`
- `scripts/validate_ontology_discovery_workflow.py`
- 以及 Agent / Worker / Workflow 控制台和若干演示 CLI。

因此，初次审查中“当前 main 缺少这些文件”的结论只适用于提交 `09a6286`，**不适用于现在的 main**。当前 main 已包含这些入口。新增文件已被确认存在，但本次尚未在 Python Runner 中执行 `make validate`、`make test` 或实际启动 Portal；是否全部运行通过仍待实测。

README 当前记录的测试基线为 188 项；此前补强报告记录为 214 项。两者存在差异，需在当前 main 上重新执行完整测试并更新验收记录。

### 1.2 当前仍可确认存在的核心资产

- 本体发现与模型：`src/ontology_software_factory/ontology_discovery.py`、`ontology_discovery_worker.py`、`ontology/software-factory-ontology.json`。
- 适配器：`src/ontology_software_factory/adapters/cognee_ontology.py`、`nvidia_auto_ontology.py`、HTTP JSON、MCP stdio。
- Agent / Workflow：`agent_runtime.py`、`agent_workflow.py`、`multi_agent_architecture.py`、`workflow_engine.py`、`workflow_store.py`、`task_runtime.py`。
- 质量与交付：`quality_gate.py`、`release_manager.py`、`e2e_delivery.py`。
- 观测：`observability.py`。
- 前端原型：`apps/factory-portal/index.html`、`apps/agent-workflow-console/index.html`、`apps/ai-runtime-console/index.html`、`apps/integrated-console/index.html`、`apps/worker-console/index.html`、`apps/workflow-console/index.html`。
- 当前仓库包含第 15–24 篇文章、工程补充篇 A–E、ADR、验收清单和架构文档。

注意：模块文件存在只说明源码资产存在，不等于它们已通过当前分支测试、已连接真实服务或已在统一 Portal 中运行。

## 2. 五部分现状与目标

### Part 1：企业 IT 资产接入、本体发现与维护

**现有基础**：本地目录 / SQLite / GitHub / GitLab 只读接入逻辑曾在 Portal 服务测试中定义；当前树中保留了集成配置样例、发现模块及 Cognee / NVIDIA 适配器。但 Portal 后端入口缺失，不能把既有 UI 的表单当作可用接入能力。

**下一步**：
1. 恢复并测试 Portal API 服务，先实现本地目录、SQLite 只读、GitHub/GitLab 只读元数据连接器。
2. 统一 Source Connector 契约：连接配置、凭据引用、同步游标、增量扫描、资产摘要、错误状态、租户归属。
3. 加入文档库、关系型数据库元数据适配器；先只读，不同步业务数据行。
4. 将发现结果统一写入候选区，保留来源 URI、文件路径、行号/字段、内容摘要和采集时间。
5. 建立候选版本、Diff、审批人/发布人分离、回滚与影响分析。
6. 生产接入前补充 OIDC/JWKS、密钥管理、租户授权、审计保留和 SSRF 防护验收。

**验收证据**：连接器契约测试、凭据不回显测试、只读权限测试、增量同步测试、来源证据可追溯测试、跨租户拒绝测试。

### Part 2：知识图谱与本体治理工作台

**现有基础**：正式本体 JSON、发现候选 Schema、候选生成与评测模块存在；`factory-portal` 前端包含图谱与候选审查 UI，但当前 API 服务缺失。

**下一步**：
1. 将本体图谱数据接口与正式本体版本、候选版本、来源证据绑定。
2. 图谱采用分层 2D 视图作为默认，提供关系方向、类型、来源、置信/评审状态过滤；大图再按需加载。
3. 支持节点/边详情侧栏、来源定位、版本 Diff、影响对象、候选合并/拆分和审批。
4. 3D/力导向动画仅作为可选探索视图，不以炫酷效果牺牲可读性、可访问性和大图性能。
5. 任何 UI 编辑先形成候选变更，不直接覆盖正式本体。

**验收证据**：节点与关系端点一致性、来源定位、版本 Diff、审批分离、租户隔离、图谱性能基准和键盘可访问性测试。

### Part 3：多智能体运行监控台

**现有基础**：Agent Runtime、Agent Workflow、团队拓扑、交接契约、运行观测模块与多个控制台页面存在；README 明确真实 LLM / Agents SDK 需要额外依赖、密钥和模型访问。

**下一步**：
1. 将 Agent Run、Workflow Run、Task、Handoff、Tool Call、Evidence 统一为可查询运行对象。
2. 监控台提供拓扑视图、阶段时间线、任务分配/交接、重试、人工审批、失败原因和证据链。
3. 展示模型名、Provider、Token 用量、延迟、工具调用 ID、费用（费率未知时显示未知）。
4. 不采集或展示隐藏思维链；仅保留结构化输入输出摘要、工具调用元数据、错误和可审计证据。
5. Fixture 与真实 Runtime 必须明确标识，避免演示数据与真实调用混淆。
6. 后续再接 OpenTelemetry、集中日志、告警和多租户用量汇总。

**验收证据**：运行状态机测试、重复事件/幂等测试、取消/超时/重试测试、权限测试、真实 Provider smoke test（单独标记环境与模型）。

### Part 4：测试床、质量与安全扫描中心

**现有基础**：`quality_gate.py`、质量策略和受限 Runner 存在；但源码树中没有对应的质量门禁 CLI 脚本，且不能据此推断当前环境已经执行过 Docker/Podman、Semgrep、Gitleaks、Trivy。

**下一步**：
1. 修复质量门禁 CLI 与 Portal API 的调用链。
2. 将检查结果统一为带有 runId、sourceTreeDigest、工具版本、执行时间、退出码、报告摘要的 Evidence。
3. 测试分层：单元/契约 → 集成 → E2E → 隔离测试床。
4. 安全扫描分层：秘密扫描、SAST、SCA/许可证、容器镜像、IaC；缺少工具或报告时标记 incomplete/block，不默认为通过。
5. 测试床优先容器隔离；对不可信客户代码和高风险执行再评估 VM/microVM。不得把受限子进程等同于强隔离沙箱。
6. 质量门禁必须绑定待交付源码/制品摘要，禁止拿其他运行的旧报告放行。

**验收证据**：故意引入漏洞/秘密/依赖风险时门禁阻断；报告摘要与源代码摘要一致；工具缺失时 fail-closed；隔离逃逸和资源限制测试。

### Part 5：制品发布、交付与生命周期

**现有基础**：`release_manager.py` 支持本地候选包、Manifest、SHA-256、配置范围 SBOM 和本地升级/回滚演练；明确不等于真实部署或完整上游依赖 SBOM。

**下一步**：
1. 抽象 Artifact Store 接口，先本地文件系统，再支持 OCI Registry / Nexus / Artifactory / 云对象存储。
2. 制品元数据包括来源提交、构建器、构建参数、依赖锁定、SBOM、质量报告、签名、审批和租户。
3. 接入 Git 分支/PR、CI Pipeline；由策略决定是否允许创建分支、提交变更或触发构建。
4. 发布分为 candidate、approved、staged、deployed、verified、rolled_back 等显式状态。
5. 部署适配器按环境启用；默认禁止生产写操作，生产发布必须二次审批、变更窗口、健康检查和回滚策略。
6. 建立交付后的版本追踪、客户反馈、缺陷回流与本体/资产目录更新。

**验收证据**：制品哈希复验、签名验证、SBOM 完整性、审批身份分离、CI 状态绑定、部署前策略检查、失败回滚演练与审计记录。

## 3. 实施顺序（先恢复可运行，再做功能）

| 顺序 | 工作包 | 主要交付 |
|---|---|---|
| 0 | 仓库完整性修复 | 恢复缺失的 Portal API / CLI / Validator 入口；修正 Makefile、README、测试引用；形成可复现的当前测试基线 |
| 1 | Portal API 与 Source Connector | 统一 API 服务、数据源连接器契约、只读同步、凭据引用与来源证据 |
| 2 | Ontology Workbench | 图谱查询、来源定位、候选治理、版本 Diff、审批和回滚 |
| 3 | Agent Command Center | 统一运行对象、时间线、拓扑、工具调用与成本/延迟展示 |
| 4 | Quality & Security Center | 测试床调度、扫描器适配、Evidence 绑定、Fail-closed Gate |
| 5 | Artifact & Release Center | 制品存储抽象、签名/SBOM、CI/CD 连接器、审批发布与回滚 |
| 6 | 企业级治理 | OIDC、租户隔离、审计、OpenTelemetry、告警、备份与灾备 |

## 4. 工程约束

- 保留现有 Python 核心库与 JSON Schema 契约，不以重写替代增量演进。
- 所有外部连接器默认只读；写权限按工具、对象、租户、环境和审批逐层授权。
- 所有 Agent 输出均为候选或提案；权威状态由确定性 Workflow / Policy 决定。
- 所有 Gate 报告必须绑定输入摘要与运行 ID；旧报告不可复用为新制品背书。
- Fixture、Mock、真实服务分别标识，不能混报。
- 不记录隐藏思维链，不将 LLM 自评置信度作为发布授权。
- 不虚构测试数量、扫描结果、性能指标或真实部署能力。

## 5. 本轮变更说明

本分支首先记录审查基线和实施顺序。由于当前 `main` 缺少 Portal API 主入口及多项 Makefile 引用的 CLI/Validator，必须先恢复这些缺失的工程入口并重新跑测试；在此之前，不应把五个 UI 工作区标记为端到端可用。


## 6. 已提交的第一批代码（Source Connector Foundation）

本工作分支已新增：

- `src/ontology_software_factory/source_connectors.py`
  - `SourceConnector` 协议与显式注册表；
  - 本地代码/文档目录只读清点；
  - SQLite 只读 Schema 清点（表、视图、列、DDL 元数据，不读取业务行）；
  - 文件类型白名单、隐藏/秘密文件过滤、依赖目录排除；
  - 符号链接拒绝、允许根目录限制、单文件大小与最大文件数限制；
  - 文件内容只在内存中计算 SHA-256，不将文件正文写入扫描结果；
  - 超出文件数时返回 `partial`，不伪装成完整扫描。
- `tests/test_source_connectors.py`
  - 覆盖目录过滤、允许根目录、符号链接、扫描上限、SQLite 只读 Schema、文档/代码源类型注册和未知连接器拒绝。

### 当前边界

这是 Part 1 的连接器基础层，不是完整企业接入。它尚未接入当前 Portal API，也没有实现 GitHub/GitLab 远程适配器、企业文档平台、PostgreSQL/MySQL、OIDC、凭据保险库、增量游标或租户级授权。文件正文不会被交给 LLM；如需用于本体发现，应增加单独的内容读取接口、脱敏策略和明确的外发授权，而不是扩大清点接口的权限。

### 验收状态

代码和测试已提交到 `work/five-parts-implementation` 分支，但本次会话没有可执行该 GitHub 工作区代码的 Python Runner，因此**尚未声称这些新增测试已运行通过**。合并前应在项目 Python 3.11+ 环境运行：

```bash
PYTHONPATH=src python -m unittest discover -s tests -p 'test_source_connectors.py' -v
```

随后再恢复当前 `main` 缺失的 Portal API / CLI 入口，运行全量 `make validate` 和 `make test`，重新记录真实基线。


## 7. 已提交的第二批代码：质量扫描报告 fail-closed

对当前 Portal 的质量扫描实现进行复核后，发现原逻辑主要依据扫描器进程退出码判定结果；例如 Trivy 在默认配置下可能以 0 退出码返回包含发现项的 JSON 报告。仅判断退出码可能把“扫描执行完成”误认为“扫描无发现”。

本分支已调整 `scripts/run_factory_portal.py`：

- 增加 `scanner_report_status`，分别解析 Semgrep 的 `results/errors`、Gitleaks JSON 数组、Trivy 的 `Vulnerabilities/Misconfigurations/Secrets`。
- 报告缺失、无法解析或结构不符合预期时标记 `incomplete`。
- 报告包含发现项时标记 `findings`，即使扫描器退出码为 0 也将总体质量运行置为 `failed`。
- 只有报告存在、可解析且发现项为 0 时，扫描结果才标记为 `completed`。
- 汇总报告单独统计 `incomplete`，不再把工具未安装/报告不可用默认为通过。

新增 `tests/test_quality_scan_reports.py`，覆盖三类扫描报告解析、错误报告和“Trivy 退出码为 0 但报告包含漏洞时必须失败”的集成场景。

**验收限制**：代码与测试已提交到本工作分支；本次未实际执行 Python 测试。合并前需运行：

```bash
PYTHONPATH=src python -m unittest discover -s tests -p 'test_source_connectors.py' -v
PYTHONPATH=src python -m unittest discover -s tests -p 'test_quality_scan_reports.py' -v
make validate
make test
```
