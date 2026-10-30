# 依赖工具与组件清单

本文区分**基础必需依赖、按功能安装的 Python extras、外部可执行工具、外部服务和可选适配器**。未安装的可选组件不会被项目自动下载或启动。

## 1. Python 依赖

以仓库根目录 `pyproject.toml` 为准：

| 依赖组 | 包 | 用途 | 安装命令 |
|---|---|---|---|
| 构建 | `setuptools>=68` | PEP 517 / setuptools 构建后端；pip 安装时自动处理 | `pip install -e .` |
| 基础 | `jsonschema[format]>=4.21,<5` | JSON Schema / Format 校验 | `pip install -e .` |
| `llm` | `openai>=1.99,<4` | OpenAI Responses API Provider、本体发现 | `pip install -e '.[llm]'` |
| `agent-runtime` | `openai>=1.99,<4` | OpenAI API 客户端 | `pip install -e '.[agent-runtime]'` |
| `agent-runtime` | `openai-agents>=0.4,<1` | Agent、Runner、Function Tool、结构化输出 | 同上 |
| `postgres` | `psycopg[binary]>=3.2,<4` | PostgreSQL Schema 只读连接器 | `pip install -e '.[postgres]'` |
| `mysql` | `PyMySQL>=1.1,<2` | MySQL Schema 只读连接器 | `pip install -e '.[mysql]'` |

Pydantic 等 Agent SDK 传递依赖由 pip 根据包元数据安装，不要手工固定与 Agent SDK 不兼容的版本。Python 版本要求为 3.11+。

项目在 pyproject.toml 中提供 Ruff 配置（行宽 100、Python 3.11 目标），但 Ruff 当前不是项目安装依赖，也不在现有 GitHub CI 必跑步骤中。如需本地 lint，可自行安装 `python -m pip install ruff` 并执行 `ruff check .`。

## 2. Python 标准库能力

下列功能不需要额外 pip 包：

- HTTP 服务：`http.server`、`urllib`
- SQLite Workflow / Worker / Portal：`sqlite3`
- 文件与路径：`pathlib`、`os`、`shutil`
- 进程调用：`subprocess`
- 哈希与摘要：`hashlib`
- JSON、时间、并发和队列：`json`、`datetime`、`threading`、`queue`
- MCP stdio JSON-RPC 传输：项目自带的标准库实现，不需要额外 MCP Python 包

## 3. 外部 CLI 工具

| 程序 | 调用位置 / 功能 | 安装时机 | 缺失时的处理 |
|---|---|---|---|
| `semgrep` | 安全扫描适配器 | 需要 SAST 时 | 对应扫描状态不可标记 PASS |
| `gitleaks` | 秘密扫描 | 需要秘密检测时 | 若质量策略要求则 Gate incomplete / blocked |
| `trivy` | 漏洞与依赖扫描 | 需要 SCA / 镜像扫描时 | 若质量策略要求则 Gate incomplete / blocked |
| `git` | 本地仓库分支、提交和工作区元数据 | 需要本地 Git 元数据时 | 相关 Git 元数据显示 unavailable |

安装上述工具后，确认命令可从启动 Portal / 执行质量 Gate 的同一用户环境的 PATH 中找到。项目不负责管理外部 CLI 的升级、许可或供应链风险。

官方安装入口：
- Git：<https://git-scm.com/downloads>
- GNU Make：<https://www.gnu.org/software/make/>
- Semgrep：<https://semgrep.dev/docs/getting-started/>
- Gitleaks：<https://github.com/gitleaks/gitleaks#installing>
- Trivy：<https://trivy.dev/latest/getting-started/installation/>

安装后可检查：

```bash
command -v git
command -v semgrep
command -v gitleaks
command -v trivy
```

某个可选工具未安装不影响基础 Portal 启动；如果质量策略将其列为必需检查，则对应 Gate 必须保持 incomplete / blocked，不能用模拟报告代替。

## 4. 外部服务与连接配置

| 服务 / 组件 | 连接方式 | 配置 / 凭据 | 边界 |
|---|---|---|---|
| OpenAI API | HTTPS | `OPENAI_API_KEY`、`OPENAI_MODEL` | 真实模型调用；任务内容会发送到配置的模型服务 |
| GitHub.com | HTTPS API | 可选 `GITHUB_TOKEN` | 只读仓库树 / 文件元数据；不下载文件正文 |
| GitLab.com | HTTPS API | 可选 `GITLAB_TOKEN` | 当前只支持 GitLab.com 元数据路径 |
| PostgreSQL | psycopg + TLS | 由 source 的 `connectionEnv` 指定 DSN 环境变量；`allowedHosts` | 只读 `information_schema`，不读取业务行 |
| MySQL | PyMySQL + TLS hostname verification | 由 source 的 `connectionEnv` 指定 DSN 环境变量；`allowedHosts` | 只读 Schema 元数据，不读取业务行 |
| NVIDIA Auto Ontology | HTTPS API | `NVIDIA_AUTO_ONTOLOGY_URL`、可选 `NVIDIA_AUTO_ONTOLOGY_API_TOKEN` | 只读术语 / acronym 目录导入 |
| Cognee | 调用方注入 Cognee client / graph model | 由部署集成方管理 | 只允许候选 review dataset；生产晋级未实现 |
| MCP Server | 本地 stdio 子进程 | 管理员配置命令数组、工作目录和环境变量 allow-list | 项目适配器不是沙箱；必须只信任管理员配置的 Server |

数据库 DSN 值、OpenAI Key、Git Token 和 NVIDIA Token 不应保存在 `sources.json`、Workflow JSON 或 Agent prompt 中。数据库 `allowedHosts` 不是网络出口防火墙，仍需部署层 egress policy。

## 5. 开发 / 运维工具

| 工具 | 用途 | 是否为运行依赖 |
|---|---|---|
| Git | 克隆、分支和源码管理 | 推荐；非 Python 模块硬依赖 |
| Make | `make portal`、`make validate` 等快捷命令 | 推荐；可直接调用 Python 脚本替代 |
| 浏览器 | 静态 Portal / Console | 使用 UI 时需要 |
| Node.js / npm | 本项目当前静态 HTML UI | **不需要** |
| Docker Engine / Docker Desktop | 固定测试套件的隔离执行（可选） | 构建 `ontology-software-factory-test-runner:py311-v1` 镜像并设置 `FACTORY_ENABLE_CONTAINER_EXECUTION=1`；运行时不自动 pull |
| Git CLI | 本地仓库元数据与可选 per-Run Git Worktree | 设置 `FACTORY_WORKSPACE_BACKEND=git-worktree` 时必需；需项目根目录为 Git 仓库 |
| Kubernetes / 微虚机运行时 | 多租户生产隔离执行与部署 | 当前没有生产级执行编排；需后续建设 |

## 6. 可选依赖安装组合

```bash
# 离线校验、测试和 Portal
python -m pip install -e .

# 真实 Agent Workflow
python -m pip install -e '.[agent-runtime]'

# LLM 本体发现 + 真实 Agent
python -m pip install -e '.[llm,agent-runtime]'

# 加上 PostgreSQL 和 MySQL Schema 连接器
python -m pip install -e '.[llm,agent-runtime,postgres,mysql]'
```

## 7. 依赖验收

```bash
make validate
make test
python scripts/check_llm_connection.py
```

- 前两项验证仓库定义、契约和本地测试。
- 第三项需要真实 Key、网络和可用模型，仅验证 Responses API 连接。
- 真实 PostgreSQL / MySQL 测试仅在设置专用测试 DSN 后执行。
- MCP、Cognee、NVIDIA 和 GitHub/GitLab 连接仍需针对实际服务单独联调；fixture 测试不代表外部服务已经连接。


## 8. Agent Workspace 执行开关与外部依赖

工作区副本、路径控制、固定 argv、证据摘要和日志由 Python 标准库实现，不新增 pip extras。真实测试执行与安全扫描的外部程序如下：

| 功能 | 外部依赖 | 默认状态 | 显式启用变量 |
|---|---|---|---|
| Agent 候选文件读写 | 无额外依赖 | 可用（只在临时工作区） | 无 |
| 固定测试套件（推荐） | Docker Engine + 本地测试镜像 | blocked | FACTORY_ENABLE_CONTAINER_EXECUTION=1 |
| SAST | Semgrep CLI | blocked，不启动 | FACTORY_ENABLE_LOCAL_SECURITY_SCANS=1 |
| 秘密扫描 | Gitleaks CLI | blocked，不启动 | FACTORY_ENABLE_LOCAL_SECURITY_SCANS=1 |
| 文件系统漏洞/配置扫描 | Trivy CLI 与本地数据库 | blocked，不启动 | FACTORY_ENABLE_LOCAL_SECURITY_SCANS=1 |

注意：Docker 测试镜像由 `runners/container/Dockerfile.test-runner` 构建，执行使用无网络、只读 rootfs、capability drop、no-new-privileges、PID/内存/CPU 限制。`FACTORY_ENABLE_UNSANDBOXED_TEST_EXECUTION=1` 仍是危险的宿主机演示回退开关。Semgrep/Gitleaks/Trivy 当前仍使用本机 CLI，尚未容器化。缺少工具、超时或缺失报告都不能标记为 PASS。


## 9. 容器扫描器镜像（可选，生产建议）

| 扫描器 | 容器入口 | 配置变量 | 运行要求 |
|---|---|---|---|
| Semgrep | digest 固定的 Semgrep 镜像 | FACTORY_SEMGREP_IMAGE | 使用 runners/container/semgrep-rules.yml 离线规则 |
| Gitleaks | digest 固定的 Gitleaks 镜像 | FACTORY_GITLEAKS_IMAGE | 工作区只读、报告目录可写 |
| Trivy | digest 固定的 Trivy 镜像 | FACTORY_TRIVY_IMAGE、FACTORY_TRIVY_CACHE_DIR | 需预先填充漏洞数据库缓存，运行时禁网且跳过 DB 更新 |

启用容器扫描需 Docker Engine、FACTORY_ENABLE_CONTAINER_SECURITY_SCANS=1 和三个不可变 image digest。镜像必须预先拉取，运行时不 pull。容器扫描不共享 Docker socket，不挂载宿主机根目录；源工作区只读，证据目录单独可写。Semgrep 使用项目本地规则文件，不依赖运行时访问在线规则仓库。
