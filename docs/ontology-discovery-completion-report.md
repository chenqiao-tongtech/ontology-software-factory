# LLM 辅助本体发现：本轮集成与验收记录

日期：2026-10-29

## 本轮交付

- 四阶段结构化候选发现：术语、关系、约束/能力问题、独立 Critic。
- 源材料 SHA-256 清单、原文 quote 核验、关系端点校验、重复项与 Critic 阻断检查。
- 可配置分阶段 LLM Provider；候选状态、调用 trace、模型 usage 和评测结果随候选保存。
- NVIDIA Auto Ontology 只读语义目录适配器；Cognee 只允许候选 Review Dataset 的图暂存适配器。
- `OntologyDiscoveryTaskHandler` 可作为 `TaskWorker` 的 `ontology.discovery.run` handler；任务只携带经授权的 source references，原文通过可信 resolver 获取。
- 候选评测 CLI 和 digest-bound 人工审批提案 CLI。审批提案不修改正式本体。
- 第 15 篇设计基线将本体发现列为 S2 语义核心的正式能力；第 16–24 篇分别增加对应的工程补充章节；README、设计文档、ADR、流程定义和验收文档同步更新。

## 本地验证结果

| 项目 | 结果 |
|---|---|
| 全量单元测试 | 188 项通过 |
| `make validate` | 通过（架构基线、范围、领域、目录、Agent 契约、多智能体、工作流、发现配置与发现工作流） |
| `make demo-e2e` | 通过，生成配置候选交付包；不是 Kafka 二进制/实时集群交付 |
| `make demo-ontology-discovery` | 通过，4 个 Fixture 阶段调用 |
| `make demo-ontology-discovery-worker` | 通过，Worker 任务完成并返回候选与评测证据 |
| 候选局部校验 | 通过，17/17 条来源引用可核实，provenance coverage 1.0 |
| 合成 Benchmark | 术语 F1=1.0、关系 F1=1.0；仅为固定 Fixture 与合成标注集一致性的烟测，不代表真实模型质量 |
| 外部模型/API | 未在当前环境执行真实调用；需要 API Key、模型权限和网络 |
| NVIDIA Auto Ontology / Cognee | Adapter 使用 mock/fake transport 测试；未连接真实外部实例 |

## 关键约束

1. 所有模型输出都仅是 `OntologyCandidate`，默认 `review_required`。
2. Critic 和评测器不能批准或发布候选；审批记录绑定 `candidateDigest`。
3. 正式本体文件、IAM、Workflow 权威状态、工具授权和安全策略不能由 LLM 直接修改。
4. 外部目录/图组件是可选适配器，不是本项目唯一权威，也不自动证明资产或事实真实。
5. 持久化 Worker 任务只接受 source references；`source_resolver` 必须执行身份、租户和访问权限检查，不要把客户原文放入普通队列载荷。
6. 生产质量需要领域专家标注集、真实模型、多来源/困难负例和分领域指标，不能以合成 smoke test 代替。

## 未完成/待环境验收

- 真实 OpenAI Responses API 调用与成本/延迟基线。
- NVIDIA Auto Ontology 与 Cognee 的真实部署连通、数据协议、网络/身份及许可审查。
- 将 9 步 discovery review workflow 接到生产级持久化状态引擎与候选版本仓库。
- 多租户 source resolver、企业 IAM/DLP、密钥服务及数据保留策略。
- 领域专家标注集、人工评审 UI、正式 ontology registry/PR 流程与下游迁移回归。
