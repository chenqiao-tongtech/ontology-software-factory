# v2.0 正式第 20–24 篇：增量补丁合并说明

此补丁序列将之前的工程补充文章与正式目录编号分离，并为 v2.0 正式目标补上工具接入、配置交付流水线、质量门禁、版本化交付和本地观测能力。

## 基线与顺序

1. 以已具备第 15 篇 starter、16–19 篇正式能力的 `ontology-software-factory` 为基线。
2. 依序应用 `article20` → `article21` → `article22` → `article23` → `article24`。
3. 最后应用 `project-integration`，更新根 README、Makefile、pyproject、范围清单、验收矩阵和正式文章编号。
4. 运行 `make validate` 与 `make test`；完整复现与边界见 `docs/acceptance/mvp-v2-verification-report.md`。

每个单篇补丁 ZIP 中的路径均相对于仓库根目录。不要把 ZIP 文件本身放入 Python 包目录。若只下载“正式覆盖包”，其中文件路径已经相对于仓库根目录，可以在已备份/已提交变更的前提下解压覆盖。

## 正式编号纠偏

v2.0 正式第 20–24 篇依次为：

- 20：工具适配、MCP/API、权限和安全执行环境；
- 21：第一条可运行的软件生产流水线；
- 22：质量与安全门禁；
- 23：版本化交付、升级与回滚；
- 24：运行观测、成本、审计与本体生命周期。

此前编号为“软件工厂工程实现线 20–24”的 Worker/Outbox/LLM/Agent Runtime/多 Agent 提案文章，已转为 `article/supplementary/` 的工程补充篇 A–E。正式文章 15–24 已放在 `article/` 和仓库根目录，各有一份独立 Markdown 副本。

## 关键边界

- 配置生产流水线真实运行固定的 Kafka 配置校验和候选配置测试，打包的只是 `server.properties` 配置，不下载/构建 Kafka 二进制。
- MCP 适配通过本地 fixture 测试；示例并未连接真实企业 MCP 服务。
- 命令注册表与 HTTP/MCP 适配不是生产 IAM；Runner 不是容器/微虚机隔离沙箱。
- Trivy/Gitleaks 如果在运行环境安装，会被以固定命令、无 shell、有限超时调用并保存报告。缺失、超时或证据不可解析时，生产 Gate fail closed。它们只扫描候选配置目录，不等于对源码、完整依赖树或 Kafka runtime 做全量 SAST/SCA/镜像扫描。
- 发布包及 CycloneDX SBOM 仅描述配置包；升级/回滚仅是本地模拟状态演练，没有触达真实环境。
- 真实 LLM API/Agents SDK 仍需用户提供可用凭据、安装可选依赖并在有网络/模型权限的环境进行端到端验证。

## 归档与删除提醒

合并后，若仓库仍存在旧路径 `article/通往AI之桥_软件工厂工程实现线20_公众号发布稿.md` 至 `...24...`，请确认它们已被 `article/supplementary/` 中 A–E 补充篇完整保留后，再将旧副本移入历史归档或删除。不要删除 `article/supplementary/` 中的内容。
