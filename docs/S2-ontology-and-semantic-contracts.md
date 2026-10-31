# S2 本体与语义契约子系统说明

> 范围：设计原理、功能组成、关键代码、运行链路、测试方式和实现边界。  
> 适用对象：架构师、领域建模人员、后端工程师、Agent / Workflow 工程师。

## 1. 子系统定位

S2（Ontology & Semantic Contracts）是软件工厂的业务语义基础设施。它把需求、产品、组件、版本、构建、测试、漏洞、发布、部署，以及 Agent、Skill、Workflow 等概念组织成机器可读、可校验、可版本化的共同语言。

S2 不替代数据库、IAM、策略引擎、工作流引擎或 Agent 推理。它定义业务对象、关系、受控词汇和不变量，并为跨子系统数据交换提供结构契约和语义校验。

设计目标：

1. 统一 Agent、工具、目录和工作流使用的业务术语。
2. 对实体和消息进行结构校验。
3. 对跨实体引用、目标类型、租户标签和业务不变量进行语义校验。
4. 对本体候选、审批、快照和变更差异进行版本治理。
5. 让每个 Workflow Run 固定使用确定版本的本体、Role、Skill、Workflow 和工具策略。

当前正式本体是 JSON 业务词汇目录，不是完整 OWL 2 本体，也没有通用 OWL 推理器或 SHACL 执行引擎。

## 2. 架构分层

~~~text
Ontology Definition
  classes / relations / vocabularies / invariants
        |
        v
Semantic Contracts
  entity / Agent Task / Agent Result / Workflow schemas
        |
        v
Validation Runtime
  JSON Schema + cross-entity graph validation
        |
        v
Governance & Versioning
  candidate -> review -> snapshot -> diff -> promote
        |
        v
Runtime Binding
  Workflow Run pins ontology + Role + Skill + policy digests
        |
        +---- Agent Runtime
        +---- Workflow / Worker
        +---- Asset Catalog / Tools / Quality Gates
~~~

| 层次 | 主要文件 | 职责 |
|---|---|---|
| 本体定义 | ontology/software-factory-ontology.json | 核心类、关系、受控词汇和不变量 |
| 模块清单 | ontology/module-manifest.json | 逻辑模块分组和覆盖检查 |
| 候选契约 | ontology/schemas/ontology-candidate.schema.json | 自动发现候选结构 |
| 实体契约 | contracts/schemas/entities.schema.json | 领域实体结构 |
| Agent Task | contracts/schemas/agent-task.schema.json | Agent 任务输入 |
| Agent Result | contracts/schemas/agent-result.schema.json | Agent 结构化输出 |
| 结构校验 | src/ontology_software_factory/contracts.py | JSON Schema 验证 |
| 语义校验 | src/ontology_software_factory/semantics.py | 跨实体引用与不变量 |
| 运行时绑定 | src/ontology_software_factory/ontology_runtime.py | 快照、Role/Skill 校验和运行契约锁 |
| 版本治理 | src/ontology_software_factory/ontology_versioning.py | 摘要、快照、差异 |
| 发现与治理 | ontology_discovery.py / ontology_governance.py | 候选发现、评审和治理流程 |

## 3. 本体建模原理

### 3.1 类（Class）

当前软件交付生命周期的核心类包括：

| 类 | 含义 |
|---|---|
| Requirement | 需求或约束 |
| Product | 软件产品或交付产品族 |
| Component | 可复用软件组件 |
| Version | 组件版本 |
| Artifact | 交付或登记产物 |
| Build | 构建执行记录 |
| TestRun | 测试执行记录 |
| Vulnerability | 漏洞发现 |
| Release | 产品发布包 |
| Deployment | 部署尝试或结果 |
| Incident | 运行事件 |

operationalExtensions 还扩展 AgentTeam、AgentRole、Skill、AgentTask、AgentHandoff、AgentResult、OntologyCandidate、OntologyApproval、OntologyRevision、OntologySnapshot、WorkflowRun、Tool、Connector、SourceSystem、APIContract 和 EventSchema 等运行治理概念。

核心类描述软件交付业务；扩展类描述软件工厂如何组织 Agent、工具和本体治理。类定义存在不代表对应的数据库表、服务和 UI 已全部实现。

### 3.2 关系（Relation）

关系定义源类型、关系名称、目标类型及可选基数、字段和校验规则。例如：

- Product containsComponent Component
- Component currentVersion Version
- Build producesArtifact Artifact
- TestRun validatesBuild Build
- Release packagesProduct Product
- Deployment deploysRelease Release

例如 Build 的 versionId 不仅要是字符串，还必须引用真实 Version，并且该 Version 的 componentId 应与 Build 的 componentId 一致。

### 3.3 受控词汇和不变量

状态字段使用受控词汇，例如 Build 的 queued/running/succeeded/failed/cancelled，Release 的 draft/candidate/approved/published/withdrawn。跨对象不变量包括实体 ID 唯一、关系目标存在且类型匹配、Version 属于 Component、Build 与 Version 归属一致、成功 Build 具有 Artifact，以及 TestRun 统计值相互一致。

JSON Schema 负责字段类型、必填项、枚举、格式和嵌套结构；涉及多个实体的引用和关系规则由语义校验器执行。

### 3.4 ID 与元数据

稳定 ID 采用 sf:<entity-kebab-case>:<stable-key> 约定。schemaVersion 表示结构契约版本，ontologyVersion 表示业务语义版本，tenantId 是数据边界标签，source 表示来源信息。tenantId 不是授权机制，source 元数据也不能单独证明内容真实性。

## 4. 语义契约

### 4.1 JSON Schema

项目使用 JSON Schema Draft 2020-12 与 FormatChecker。典型流程是加载 Schema、检查 Schema 自身有效性、校验 payload、返回带路径的错误，再进入跨实体语义校验。

示例：

~~~python
from jsonschema import Draft202012Validator, FormatChecker

validator = Draft202012Validator(
    schema,
    format_checker=FormatChecker(),
)
errors = sorted(
    validator.iter_errors(payload),
    key=lambda error: list(error.absolute_path),
)
if errors:
    raise ValueError([
        {"path": list(error.absolute_path), "message": error.message}
        for error in errors
    ])
~~~

JSON Schema 不适合单独承担跨实体存在性和归属关系校验。

### 4.2 Agent Task 与 Agent Result

Agent Task 不应只是自然语言 Prompt。它还应携带任务 ID、项目和租户上下文、Role、输入实体类型、期望输出实体类型、验收标准、上下文引用、资源限制、幂等信息和本体绑定。

运行时绑定记录 ontologyVersion、ontologySnapshotId、ontologyDigest、ontologySchemaVersion、roleDigest 和 skillRefs（ID、版本、内容摘要）。

Agent Result 是结构化候选结果封套。必须区分模型生成、结构契约通过、领域校验通过、业务系统接受/持久化这几个阶段。封套有效不代表业务写入已完成。

## 5. 关键代码实现

### 5.1 跨实体语义校验：semantics.py

该模块以 SINGLE_REFS 和 ARRAY_REFS 描述单值和数组引用字段的目标类型。validate_entity_graph(entities) 建立实体 ID 索引，检查重复 ID、引用格式、目标存在性、目标 entityType、tenantId 一致性，并执行额外业务不变量。

核心逻辑示例：

~~~python
def check_ref(source, target_id, target_type, by_id, errors):
    if not isinstance(target_id, str):
        errors.append("reference must be an entity ID string")
        return
    target = by_id.get(target_id)
    if target is None:
        errors.append("referenced entity does not exist")
        return
    if target.get("entityType") != target_type:
        errors.append("referenced entity has the wrong type")
    source_tenant = source.get("tenantId")
    target_tenant = target.get("tenantId")
    if source_tenant is not None and target_tenant is not None:
        if source_tenant != target_tenant:
            errors.append("cross-tenant reference is not allowed")
~~~

当前关系规则仍有显式 Python 映射和分支逻辑；新增关系时需要同步检查本体 JSON、语义校验器、Schema、样例和测试，避免定义与执行规则漂移。

### 5.2 快照和摘要：ontology_versioning.py

本体快照使用规范化 JSON（键排序、紧凑序列化）计算 SHA-256。快照记录 ontology ID/version、schema version、完整 digest、创建时间、actor、reason 和快照内容。diff_snapshots 比较类、关系、受控词汇和不变量，输出新增、删除、修改及结构影响范围。

内容摘要证明内容一致性，不等于签名、可信时间戳或防篡改审计。

### 5.3 运行时绑定：ontology_runtime.py

validate_ontology_binding 重新计算快照摘要，并检查 snapshotId、ontologyId、ontologyVersion、schemaVersion 与内容元数据的一致性。失败时抛出 OntologyBindingError，拒绝执行。

load_active_ontology_binding 从本地 Portal 状态加载活动快照。validate_role_ontology_contract 检查 Role 输入输出类型是否存在、Skill 文件和版本是否有效、Skill 是否与 Role 兼容、Skill 引用的实体类型是否存在，以及 Skill 所需工具是否在 Role 工具集合中。

build_runtime_contract_lock 固定本体快照、Workflow 定义、Role、Skill 和工具策略的摘要；validate_runtime_contract_lock 在执行过程中重新计算并比对，检测配置漂移。

### 5.4 模块清单：ontology_modules.py

module-manifest.json 用于本体逻辑模块分组、依赖和覆盖检查；权威定义仍在 software-factory-ontology.json。当前逻辑模块不等于独立模块编译、依赖锁定和发布流水线。

### 5.5 发现与治理

发现流程为：

~~~text
Source -> Source Snapshot -> Extraction Run
       -> Ontology Candidate -> Evidence / Evaluation
       -> Human Review -> Ontology Revision
       -> Immutable Snapshot -> Governed Promotion
~~~

候选应携带来源身份、定位信息、内容摘要和采集时间。LLM 不直接覆盖正式本体。消费者依赖图主要基于 Role、Skill、Workflow、Tool 和 Contract 中显式的类型引用；未建立索引的隐式依赖不能被声称已完整发现。

## 6. Workflow Run 中的使用链路

1. Portal 选择活动本体快照。
2. 创建 Run 时加载完整快照并校验摘要。
3. 创建运行契约锁，固定 Workflow、Role、Skill 和工具策略。
4. Worker 派发 Task 时传递快照绑定信息。
5. Agent Handler 再次校验快照和契约锁。
6. 校验 Role 输入输出实体类型与 Skill 引用。
7. Agent 输出通过 Result Schema 和实体类型校验。
8. 结果与快照引用、运行 ID 和 Evidence 一起保存。
9. Run 后续阶段持续使用原快照，不因活动版本变更而漂移。

## 7. 对其他子系统的接口

| 子系统 | S2 提供的语义 |
|---|---|
| S1 需求入口 | Requirement、Product 和需求状态 |
| S3 产品与资产目录 | Product、Component、Version、Artifact |
| S4 Agent/Harness | AgentRole、Skill、AgentTask、AgentResult |
| S5 Workflow | WorkflowRun、任务状态和本体版本锁 |
| S6 工具连接 | Tool、Connector、APIContract、EventSchema |
| S8 质量安全 | Build、TestRun、Vulnerability |
| S9 交付发布 | Artifact、Release、Deployment |
| S10 监控审计 | Run、Task、ToolInvocation、Evidence |

## 8. 当前实现边界

已具备：机器可读本体、模块清单、JSON Schema、跨实体引用和部分不变量校验、SHA-256 快照和差异、候选发现与治理基础、Role/Skill 类型校验、Workflow Run 本体绑定和运行契约锁。

尚不能声称：完整 OWL 2 推理、SHACL 图约束执行、IAM 授权、签名本体注册中心、防篡改审计、完整的隐式消费者依赖发现、多租户生产级治理。当前 Portal 状态和快照存储仍是本地参考实现。

## 9. 开发与验证

在仓库根目录执行：

~~~bash
make ontology-modules
make validate
make test
~~~

新增领域对象或关系时，依次更新正式本体、模块清单（如需）、JSON Schema、semantics.py、Role/Skill/Workflow 引用、样例和测试，再生成快照并评审差异。只有通过独立审批后才提升为活动版本。

## 10. 设计结论

**本体定义共同的业务世界，语义契约定义交互边界，语义校验保证关系成立，版本治理保证定义可追溯，运行时绑定保证 Agent 在确定的语义版本下工作。**

S2 的价值不是让 Agent 更聪明，而是让多个 Agent 和工程系统能够以一致、可检查、可审计的方式协同。
