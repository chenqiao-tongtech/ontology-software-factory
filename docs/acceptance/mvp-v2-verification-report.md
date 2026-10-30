# v2.0 软件工厂第 15–24 篇累计工程验收报告

**核验日期：2026-10-28**  
**对象：** `ontology-software-factory` 累计参考工程（第 15–24 篇正式目录 + A–E 工程补充篇）  
**目的：** 区分文章/代码存在、自动化测试通过与生产外部能力已经验证这三种不同状态。

## 1. 本轮复现结果

| 验收命令 / 场景 | 结果 | 观察到的事实 |
|---|---|---|
| `make validate` | PASS | MVP 范围、13 个领域实体、资产目录、7 个 Agent 角色 / 7 个 Skills / 22 个工具定义、软件交付 DAG 与 Agent 提案工作流定义均通过校验。 |
| `PYTHONPATH=src python -m unittest discover -s tests -v` | PASS | 149 项测试通过，运行时间约 24.7 秒。 |
| 开发配置端到端：需求 → 配置生成 → 实际配置校验子进程 → 候选测试 → 打包 → Gate → release candidate | PASS（配置包范围） | E2E 返回 `release_candidate_ready`；Gate 为 `passed`；生成了版本化配置包和交付记录。 |
| 生产配置端到端（当前环境） | 正确阻断 | E2E 返回 `blocked`，Gate 为 `incomplete`，`releaseAllowed=false`，没有创建 release。原因是本执行环境没有安装 Trivy/Gitleaks。 |
| 本地观测汇总 | PASS（本地报告） | 报告覆盖 run 汇总、LLM Usage Ledger 与追溯信息；未配置模型价格时，费用保留为未知值，不臆造金额。 |
| MCP 工具适配 | PASS（fixture） | 使用本地测试 MCP server 验证 initialize/list/call 和白名单行为，没有连接真实企业 MCP 服务。 |

## 2. 第 15–24 篇正式目录对齐情况

| 正式篇目 | 对应能力 | 状态 | 仍需补齐的关键内容 |
|---|---|---|---|
| 15 | 工厂边界、架构和 MVP | 设计基本完成 | 真实生产用例的业务验收和量化基线。 |
| 16 | 本体与机器契约 | 本地验证 PASS | 更丰富的真实业务数据、跨服务映射及变更迁移测试。 |
| 17 | 资产目录与客户配置 | 元数据验证 PASS | 真实 Kafka 版本、上游下载、签名/摘要核验和真实 SBOM。 |
| 18 | Agent/Skill/Context 契约 | 契约验证 PASS | 生产 IAM、租户隔离和运行时凭据策略。 |
| 19 | 工作流和状态机 | 本地验证 PASS | 在真实执行器、Git/CI 结果上完成状态转换和恢复演练。 |
| 20 | API/MCP 工具、权限和受控执行 | 本地适配 PASS / 外部集成 PARTIAL | 真实 MCP server/API 连接、容器/微虚机沙箱、短期身份凭据和受控网络。 |
| 21 | 第一条可运行生产流水线 | 配置交付流水线 PASS | 真实 Git 分支/提交、Kafka 二进制、真实构建、集成测试和制品来源证明。 |
| 22 | 质量和安全门禁 | 配置级 Gate PASS / 生产扫描 BLOCKED_EXTERNAL | 安装扫描器后实际执行并检查 Trivy/Gitleaks 报告；接入源代码 SAST/SCA、真实依赖与容器扫描。 |
| 23 | 版本化交付与升级回滚 | 配置包发布 PASS / 生产部署 PARTIAL | 目标环境适配器、部署前检查、健康检查、灰度、真实回滚与不可逆迁移预案。 |
| 24 | 观测、成本、审计与本体生命周期 | 本地观测 PASS / 运营 PARTIAL | 真实模型调用账单、分布式 traces、多租户指标、审批系统与自动回归流水线。 |

## 3. 本次实际执行的质量门禁

Gate 现在对生产 profile 使用固定命令和 `shell=False` 调用 Trivy 与 Gitleaks（如果命令可用），设置超时并保存报告、日志和摘要。若扫描器缺失、超时或无法产生可解析报告，结果为 `incomplete`，不得发布；发现高严重度问题时为 `blocked`。

本次执行环境缺少这两个外部扫描器，因此**没有真实扫描报告**。测试中通过 Mock 的报告和返回码测试了“扫描通过”“高危发现阻断”“扫描器缺失阻断”三条分支。测试 Mock 不等于扫描器实际执行。

即使扫描器被执行，目前扫描范围也只覆盖候选配置目录；没有真实 Kafka binary/container，也没有完整源代码/依赖树可供扫描。因此不得将它表述为 Kafka 生产级安全认证。

## 4. 真实 LLM 与 Agent Runtime

累计代码保留了可选的 OpenAI Responses API Provider、Agents SDK Runtime 和多 Agent 提案工作流，并提供 Fake Client/Runtime 测试。但当前环境未配置 `OPENAI_API_KEY`，没有通过真实外部模型请求进行本轮端到端验收。该项状态应记录为 `BLOCKED_EXTERNAL`，不能依据 Fake Client 测试宣称真实模型已连通。

## 5. 可复制的验收命令

```bash
python -m pip install -e . --no-build-isolation --no-deps
make validate
make test
make demo-e2e
make observability
```

本地演示会写入 `.local-runs/`、`deliverables/` 和 `observability/reports/`，这些运行时输出被 `.gitignore` 排除，不应随源代码包提交。生产配置在当前缺少外部扫描器的环境下应被拒绝发布，这是预期的 fail-closed 行为。

## 6. 最终结论

本轮完成了 v2.0 正式第 20–24 篇的主题对齐、累计工程整合、回归测试提速、条件式外部扫描器执行和第 15–24 篇文章归档。当前工程可以重复生成和验证 Kafka 风格的**配置交付包**，可以生成本地交付记录和配置包 SBOM，并可正确阻断缺失生产扫描证据的发布路径。

它仍然是一个可运行的参考 MVP，不是已上线的生产软件工厂。最重要的未完成事项是：容器级隔离、真实 Git 变更、真实 Kafka 制品与集群验证、生产级 IAM、外部扫描器运行、真实部署/回滚，以及模型 API 的有凭据验收。
