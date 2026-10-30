# LLM 辅助本体发现与定义

## 1. 目标与边界

本模块将大模型用于术语发现、定义草拟、关系抽取、约束候选、Competency Questions 生成、概念去重建议和独立 Critic。它输出的是 `OntologyCandidate`，不是正式本体；LLM 不得修改 `ontology/software-factory-ontology.json`、JSON Schema、工作流、IAM 或发布策略。

采用“LLM 发散提出候选、确定性工具验证、领域专家收敛批准”的模式。模型置信度只是模型自评，不是事实概率、来源真实性或发布授权。

## 2. 四阶段结构化流水线

1. **Term discovery**：发现类、属性、事件、动作、状态、指标、关系概念，生成定义与别名。
2. **Relation discovery**：发现有向、带类型的关系，给出主体、谓词、客体和逐条来源证据。
3. **Constraint + Competency Questions**：提出结构、引用、状态、不变量、时间、质量、兼容性约束，并生成可评审的能力问题。
4. **Independent critic**：从重复/重叠、无证据关系、歧义、缺少能力问题、将业务约束误当权限规则等方面提出反例。

后续由确定性程序执行 JSON Schema 校验、来源引用核对、关系端点检查、重复项检测、Benchmark 对比和摘要计算。Critic 不修改候选；不论自动评测分数多高，状态仍为 `review_required`，只有独立人类审批且审批绑定候选 digest 后，才能生成版本化变更提案。

## 3. 输入源和来源证据

支持把 Markdown、业务词汇表、DDL/Schema、API 描述、事件定义、资产目录导出等转换为 `SourceMaterial`。每个源包含 `sourceId`、`sourceType`、`locator`、文本内容和 SHA-256。当前 MVP 单源不超过 18,000 字符、总输入不超过 48,000 字符；超出时先按有边界的业务单元拆批，后续再引入重叠窗口与跨批次合并。

每个术语和关系须有一条或多条 `{sourceId, locator, quote}` 引用。当前实现对 quote 做空白规范化后与原文匹配；不可核验引用会成为错误并阻止候选通过本地校验。对复杂表格、SQL AST 或二进制来源，应由适配器先生成可定位的文本片段，不要让模型伪造行号或字段位置。

输入材料视为不可信数据而非系统指令。源码和配置中的潜在密钥在发往模型前应脱敏；示例实现对常见 API key / 私钥模式做阻断，但这不能替代企业级 DLP/Secret Scanner。

## 4. 多模型策略与成本控制

可以为四阶段配置独立模型：

- `ONTOLOGY_TERM_MODEL`：术语/定义提取，优先结构化能力与成本效率。
- `ONTOLOGY_RELATION_MODEL`：关系和端点推断。
- `ONTOLOGY_CONSTRAINT_MODEL`：约束与能力问题。
- `ONTOLOGY_CRITIC_MODEL`：独立批判评审，建议使用独立部署或不同模型系列作为交叉检查。

未设置时回退到 `OPENAI_MODEL`。所有调用复用 `llm_provider` 的 Structured Output、有限重试、超时和脱敏 usage ledger。不同模型的差异必须留在 Trace 中，不允许仅凭“用了不同模型”宣称独立性；最终仍以确定性校验、领域评测集与人工复核为准。

## 5. 开源组件的选型边界

### NVIDIA Auto Ontology（可选外部语义目录）

官方项目侧重从企业元数据生成语义目录/本体、协调跨系统定义并通过 MCP、CLI、API 向 Agent 暴露语义上下文；其 Apache-2.0 开源仓库同时包含 Web UI、FastAPI 后端、Postgres/pgvector、数据摄取及 NVIDIA NIM 模型配置。它不是一个可以无条件直接嵌入本项目的单文件抽取库。当前适配器是**只读目录导入**，读取部署实例文档化的 `/api/terms` 与 `/api/acronyms`，把记录转成来源材料供本项目自己的发现流程引用；不直接写入外部实例，也不把它的目录直接视为本项目的正式本体。

- Repo: https://github.com/NVIDIA/auto-ontology
- API reference: https://nvidia.github.io/auto-ontology/

### Cognee（可选图抽取与语义 grounding）

Cognee 支持用自定义 Pydantic `DataPoint`/`graph_model` 约束图提取，并可用现有 OWL 本体对抽取到的实体进行 grounding。它适合作为文本→结构化图的补充组件，而不是替代本项目的版本化领域本体、质量门禁和审批流程。当前适配器输出显式 graph schema，并仅允许写入 `ontology-candidate-review-*` 暂存数据集；生产 promotion 不在该适配器范围内。

- Custom graph models: https://github.com/topoteretes/cognee/blob/main/.agents/skills/cognee-custom-graph-models/SKILL.md
- Ontology grounding overview: https://github.com/topoteretes/cognee/blob/main/CLAUDE.md

### LLMs4OL / OLLM（评测/研究参考）

可以借鉴 ontology learning from text 的术语分类、taxonomy discovery、ontology extension 任务作为评测基线；它们目前不属于运行时必需依赖。应优先使用自己的领域专家标注 Benchmark，而不是直接把公开任务分数外推为企业业务本体质量。

## 6. 运行示例

离线验证（不会发网络请求）：

```bash
python scripts/validate_ontology_discovery_config.py
python scripts/run_ontology_discovery.py --demo --overwrite
python scripts/validate_ontology_candidate.py .local-runs/ontology-candidates/<candidate-id>.json
python scripts/evaluate_ontology_candidate.py \
  --candidate .local-runs/ontology-candidates/<candidate-id>.json \
  --benchmark examples/ontology-discovery/benchmarks/software-factory-benchmark.json
```

真实 LLM 调用：

```bash
export OPENAI_API_KEY='...'
export OPENAI_MODEL='账户可用的模型 ID'
# 可按阶段覆盖，若不指定则都用 OPENAI_MODEL
export ONTOLOGY_CRITIC_MODEL='账户可用的独立评审模型 ID'
python scripts/run_ontology_discovery.py \
  --domain software-factory \
  --source docs/architecture.md \
  --source docs/domain-model.md \
  --output-root .local-runs/ontology-candidates
```

真实调用会将指定源文本发给配置的模型服务。不要提交 API Key；处理客户材料前确认数据处理协议、允许的区域和敏感内容策略。若候选文件已存在，命令默认拒绝覆盖；需要显式 `--overwrite`。

可选 NVIDIA Auto Ontology 目录导入：设置 `NVIDIA_AUTO_ONTOLOGY_URL` 与 `NVIDIA_AUTO_ONTOLOGY_API_TOKEN` 后，在可信服务端调用 `NvidiaAutoOntologyAdapter.fetch_catalog_sources()`；此端点连接在当前环境只经过 Mock transport 测试，没有进行外部实例连通性验收。

可选 Cognee：安装并配置 Cognee 后，将候选先暂存到独立 review dataset。即使候选已获批准，本适配器也不把数据写入生产数据集；正式 promotion 仍需单独的版本化变更流程。

## 7. 将发现任务接入 Worker 与审批提案

`src/ontology_software_factory/ontology_discovery_worker.py` 提供 `make_ontology_discovery_handler(...)`，可注册为 `TaskWorker` 的 `ontology.discovery.run` 处理器。队列载荷只携带经授权的 `sourceRefs`；由可信 `source_resolver` 检查租户/访问权限并返回 `SourceMaterial`。不要将客户原文或密钥直接放入持久化 SQLite 任务载荷。

离线演示：

```bash
make demo-ontology-discovery-worker
```

此命令通过 Worker 队列完成发现、保存候选和评测证据，并验证任务输出契约。演示使用 Fixture Provider，不访问外部 LLM。生产环境须注入真实 provider、受控 source resolver、持久化候选存储、调用预算与审批服务，并配置大于各阶段总超时的 Worker 截止时间。

人工审批采用候选摘要绑定；示例审批 CLI 仅记录带审批引用的本地变更提案，不会修改正式本体：

```bash
python scripts/approve_ontology_candidate.py \
  --candidate .local-runs/ontology-candidates/<candidate-id>.json \
  --reviewer-id <human-reviewer-id> \
  --approval-ref <approval-ticket> \
  --expected-digest <reviewed-candidate-digest>
```

该 CLI 不能取代企业 IAM 身份认证或审批系统；调用者必须确保 reviewer 身份来自可信授权边界。

## 8. 验收与非目标

- 必须验证候选结构、来源引用、关系端点与重复项。
- 使用领域专家复核的 gold benchmark 计算 term / relation precision、recall、F1 和 provenance coverage。
- Benchmark 分数只是一项门禁信号，不可自动批准。
- 未解决的证据冲突、阻断级 Critic 发现、无来源的核心概念或未覆盖的关键 Competency Questions 应转人工处理。
- 不直接生成或发布 OWL/SHACL 到生产；若需要 RDF/OWL，应在批准候选上进行独立导出和本体一致性/SHACL 回归。
- 该模块当前是可运行的离线参考流水线、Worker 任务处理器和可选适配器；发现审查工作流仍未完整接入生产级分布式状态引擎/候选数据库，也未在本环境进行真实模型 API 或 NVIDIA/Cognee 外部连接验收。
