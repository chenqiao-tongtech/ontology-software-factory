# MVP 验收清单（目标标准，不代表已实现）

> 状态规则：`PLANNED` = 端到端生产能力的设计目标；只有附有可重复执行的工具输出、日志或审计证据后才能标为 `PASS`。第 16 篇已实现领域词汇、样例对象和契约校验子集，但这不代表构建、真实测试、安全扫描或部署等端到端 MVP 已完成。

| ID | 验收标准 | 必需证据 | 当前状态 |
|---|---|---|---|
| MVP-01 | 需求可结构化记录，并保留稳定 ID、来源、目标环境和范围。 | 输入样例、Schema 校验结果、需求记录 | PLANNED |
| MVP-02 | 生产流程只能引用资产目录中已批准且版本明确的组件。 | 资产记录、审批状态、选择日志；未批准资产负向测试 | PLANNED |
| MVP-03 | 客户化配置进入构建前通过机器可执行的 Schema / 规则校验。 | 通过和拒绝两类配置样例及校验输出 | PLANNED |
| MVP-04 | 构建与测试由隔离执行器真实运行，保存退出码、日志和运行标识。 | runner 任务 ID、命令白名单、退出码、日志引用 | PLANNED |
| MVP-05 | 测试结果绑定到具体提交、构建记录和候选制品。 | commit SHA、build ID、test run ID、artifact digest 的关联记录 | PLANNED |
| MVP-06 | 质量或安全门禁失败时，候选制品不能进入发布状态。 | 人为引入失败测试/高危发现，证明发布状态被阻断 | PLANNED |
| MVP-07 | 交付记录可追溯源代码版本、依赖、构建、测试与制品摘要。 | 可导出的交付证据包 / 元数据清单 | PLANNED |
| MVP-08 | 生产部署需要授权和人工审批，并有部署前检查与回退预案。 | 审批人、策略判定、变更窗口、验证和回退步骤记录 | PLANNED |

## 验收反模式

以下材料不能单独作为验收通过证据：

- Agent 生成的“所有测试已通过”文字；
- 没有执行器日志的测试摘要；
- 无法绑定到 commit / artifact digest 的安全报告；
- 只有架构图，没有可运行的负向测试；
- 手工修改状态为 `released`，却没有策略与审批记录。


## 第 16 篇：领域本体与契约校验子集

以下是已经纳入代码库、可以在本地重复验证的工程项。它们是增量验收，不会自动把上表的端到端 MVP 项标为完成。

| ID | 验收标准 | 必需证据 | 当前状态 |
|---|---|---|---|
| SEM-01 | 机器可读词汇表包含唯一类名，关系源和目标都指向已定义类。 | `python scripts/validate_domain_model.py` 的成功输出 | PASS |
| SEM-02 | 11 类核心对象通过 JSON Schema Draft 2020-12 结构校验。 | `contracts/schemas/entities.schema.json` 与结构测试 | PASS |
| SEM-03 | 关联对象 ID 必须存在且类型正确；禁止重复 ID 和跨租户引用。 | `tests/test_semantics.py` 正向与负向测试 | PASS |
| SEM-04 | 组件、版本、构建、发布与漏洞之间的关键引用必须保持一致。 | 组件/版本错配与发布版本归属的负向测试 | PASS |
| SEM-05 | 构建、测试、发布和生产部署满足当前 MVP 定义的不变量。 | 状态组合负向测试与校验器输出 | PASS |
| SEM-06 | 范围检查、示例语义校验和全套回归测试可以在本地执行。 | `make validate` 与 `make test` 输出 | PASS |


## Article 17 — Asset catalogue acceptance

- [ ] **CAT-01** 产品引用的所有组件都存在，且目录对象 ID 唯一。
- [ ] **CAT-02** 每个组件的默认版本属于该组件，依赖解析版本属于声明的依赖组件。
- [ ] **CAT-03** 已解析依赖满足声明的 SemVer 约束，且依赖图无环。
- [ ] **CAT-04** 兼容性结论必须具有已验证的证据引用；未测试不表示兼容。
- [ ] **CAT-05** 客户化配置与标准资产分离，密钥只能通过 secretRefs 引用。
- [ ] **CAT-06** 客户补丁限定租户、绑定基础版本，并在批准前具备测试和安全审核结果。
- [ ] **CAT-07** 资产目录元数据校验与版本发布就绪度检查可在本地重复执行。

> CAT checks validate declared metadata and references. They do not verify remote artifact bytes, signatures, SBOM contents, or real-world compatibility.
