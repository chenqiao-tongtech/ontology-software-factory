# v2.0 软件工厂 MVP 验收矩阵（截至 2026-10-28）

> 状态定义：`PASS` = 此范围有可重复执行的本地证据；`PARTIAL` = 有实现或负向测试，但未达到原目录的完整生产条件；`BLOCKED_EXTERNAL` = 需要未接入的外部工具/凭据/环境；`PLANNED` = 尚未实现。不能用 Agent 的文字陈述替代真实执行证据。

| ID | 原目录目标 | 当前状态 | 证据与边界 |
|---|---|---|---|
| MVP-01 | 结构化需求、稳定 ID、来源与范围 | PASS（示例范围） | `contracts/schemas/production-request.schema.json`；`examples/requests/*.json`；非法输入负向测试 |
| MVP-02 | 只引用已批准、版本明确的资产 | PASS（目录元数据范围） | `production_pipeline.py` 选择 active 示例组件/默认版本并检查 license review metadata；目录来源和摘要仍是合成示例 |
| MVP-03 | 客户化配置生成前机器校验 | PASS（配置模板范围） | `scripts/validate_kafka_profile.py`；schema 和 profile 规则测试 |
| MVP-04 | 隔离执行器真实运行构建与测试 | PARTIAL | 固定 argv、`shell=False`、有限超时、stdout/exit code/hash 已记录；未接入 OS/容器级沙箱，故不宣称完成原始“隔离执行器”目标 |
| MVP-05 | 测试结果绑定 commit、build 和制品 | PARTIAL | build ID/run ID、配置 SHA-256、包 SHA-256、日志 hash、回归测试结果已关联；无 `.git` 时 source commit 为 null，尚未创建真实 Git 分支/commit |
| MVP-06 | Gate 失败时禁止发布 | PASS（当前 Gate 策略范围） | 秘密模式、文件 hash、配置规则负向测试；生产 profile 无 Trivy/Gitleaks 执行证据时 releaseAllowed=false；还未覆盖全源代码 SAST/SCA |
| MVP-07 | 源版本、依赖、构建、测试、制品摘要可追溯 | PARTIAL | 配置包 manifest 与 config-only CycloneDX SBOM 已产出；没有真实 Kafka binary/SBOM，且 git revision 需在真实 clone 中验证 |
| MVP-08 | 生产部署需授权、前检和回退预案 | PARTIAL | 独立审批人、模拟升级与失败回滚可测试；没有生产部署适配器，因此没有生产变更能力 |
| SEM-01～06 | 核心实体、Schema、交叉引用与负向测试 | PASS | `scripts/validate_domain_model.py`、`tests/test_contracts.py`、`tests/test_semantics.py` |
| CAT-01～07 | 目录引用、版本、依赖、兼容性与租户边界 | PASS（元数据范围） | `scripts/validate_asset_catalog.py` 与 `tests/test_catalog.py`；不验证远端 artifact bytes、签名或真实兼容性 |
| AGENT-01 | Role/Skill/权限契约和输入输出 | PASS（声明/运行策略范围） | `scripts/validate_agent_contracts.py` 与 Runtime Policy 测试；不等同生产 IAM |
| TOOL-01 | Tool Registry default-deny、Schema 与审批 | PASS（本地处理器） | `tests/test_tool_registry.py`；高影响操作仅绑定模拟 release action |
| MCP-01 | MCP stdio 传输与工具白名单 | PASS（fixture） | `tests/test_mcp_stdio.py` 使用本地 fixture；真实 MCP server 未接入 |
| PIPE-01 | 可运行的配置交付流水线 | PASS（配置包） | `scripts/run_software_factory_pipeline.py`；真实运行配置校验器和候选配置测试工具，生成包与 build record（完整回归由 `make test` 执行）；不构建 Kafka 二进制 |
| SEC-01 | 生产安全扫描器证据 | BLOCKED_EXTERNAL | Gate 在扫描器已安装时会以固定 argv、shell=False 和超时限制真实调用 Trivy/Gitleaks 并保存报告与日志；本次环境未安装扫描器，因此生产 profile 的 Gate 状态为 incomplete 且不可放行。扫描范围限于候选配置目录，不覆盖源码 SAST/SCA 或 Kafka runtime |
| REL-01 | 版本清单、文件 hash、SBOM | PASS（配置包） | `scripts/create_release.py`；SBOM 仅描述被打包的配置文件 |
| REL-02 | 升级/回滚 | PARTIAL | `scripts/rehearse_upgrade.py` 只模拟本地状态；无真实集群部署与健康检查 |
| OBS-01 | 本地运行与 Gate 指标报告 | PASS（本地报告） | `scripts/report_factory_observability.py`；不代表生产遥测服务已部署 |
| OBS-02 | 按价格核算 LLM 成本 | PARTIAL | LLM Adapter 可向 JSONL Usage Ledger 提供 token 事件；没有价格配置时成本正确保留 null；Agents SDK 事件仍需接入实际运行钩子 |
| LIFE-01 | 本体生命周期反馈与治理 | PARTIAL | `propose_ontology_change.py` 生成需审批变更提案，不自动改写本体；尚缺审批系统与回归自动化闭环 |

## 一次性复现命令

```bash
make validate
make test
make demo-e2e
make observability
```

建议额外生成 Gate 负向结果：

```bash
PYTHONPATH=src python scripts/run_software_factory_pipeline.py --request examples/requests/kafka-production.json --output-root .local-runs --run-id gate-prod-audit
PYTHONPATH=src python scripts/run_quality_gate.py --run-dir .local-runs/gate-prod-audit
```

未安装/未运行生产要求的外部扫描器时，预期结果是非零退出且 `releaseAllowed=false`，这是预期的 fail-closed 行为。
