# 本体自动发现集成补丁说明

该补丁在现有 `ontology-software-factory` 项目内增加 LLM 辅助本体发现与审核能力，并对第 15 篇设计基线和第 16–24 篇文章进行同步补充。

## 主要变更

- 新增 `src/ontology_software_factory/ontology_discovery.py`：四阶段结构化候选流水线、来源核验、候选摘要、人工审批绑定、Benchmark 指标。
- 新增 `src/ontology_software_factory/ontology_discovery_worker.py`：接入既有 Worker，任务只携带经过授权的 source references，结果回传候选/评测证据。
- 新增 `src/ontology_software_factory/adapters/nvidia_auto_ontology.py`（只读元数据）和 `adapters/cognee_ontology.py`（仅审查数据集暂存）。
- 新增 `scripts/run_ontology_discovery.py`、`scripts/run_ontology_discovery_worker_demo.py`、`scripts/evaluate_ontology_candidate.py`、`scripts/validate_ontology_candidate.py`、`scripts/approve_ontology_candidate.py` 和校验脚本。
- 新增 discovery team、role/Skill、workflow、候选 Schema、政策文件、合成 Fixture/Benchmark、文档、ADR 和测试。
- 更新领域本体 operational extensions、Agent/Skill Schema、角色/工具目录、权限策略、架构基线、Makefile、README，以及第 15–24 篇正式文章。

## 应用

1. 在应用前备份并提交当前分支。
2. 将补丁中的文件解压至仓库根目录；不要覆盖你的本地定制后再不检查就提交。
3. 安装已有项目依赖（至少需要 `jsonschema`；真实模型需安装项目的 `llm` extra）。
4. 运行：

```bash
make validate
make test
make demo-ontology-discovery
make demo-ontology-discovery-worker
```

5. 如需真实模型调用，先设置 `OPENAI_API_KEY`、`OPENAI_MODEL`，检查数据处理和模型可用性后再用非敏感测试资料执行 `scripts/run_ontology_discovery.py`。

## 注意

- 不会自动修改正式本体；候选保持 `review_required`。
- NVIDIA Auto Ontology 连接器只读元数据；Cognee 仅写入 `ontology-candidate-review-*` 数据集。
- 当前没有完成真实外部模型、NVIDIA 或 Cognee 的在线连通验收。
- JSON Schema/本地测试通过不等于本体语义已经被领域专家认可。
- 正式人工批准命令生成的是版本化 change proposal，不会自动 merge 或发布。
