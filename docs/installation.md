# 安装指南

本文覆盖本地开发、Portal、本体治理、真实 LLM 与多 Agent Runtime 的安装。项目当前定位为 Python 本地参考实现，不是生产部署包。

## 1. 系统要求

| 项目 | 要求 | 用途 |
|---|---|---|
| Python | 3.11 或更新版本 | 全部 Python 模块和脚本 |
| pip | 随 Python 提供的现代 pip | 安装项目及可选依赖 |
| Git | 推荐安装 | 获取仓库；本地仓库元数据扫描 |
| GNU Make | 推荐安装，非强制 | 使用 Makefile 快捷命令 |
| 浏览器 | 现代 Chromium / Firefox / Safari | Portal 和 Runtime Console |
| 网络 | 仅真实 LLM、远端 Git、外部服务需要 | API 请求和服务连接 |

Portal、Workflow Console 和 Agent Workflow Console 的前端是静态 HTML/JavaScript，不需要 Node.js、npm、Vite 或前端构建步骤。SQLite 由 Python 标准库提供，不需要单独安装 SQLite Python 包。

## 2. 获取源码并创建虚拟环境

```bash
git clone https://github.com/chenqiao-tongtech/ontology-software-factory.git
cd ontology-software-factory

python3.11 -m venv .venv
source .venv/bin/activate

python -m pip install --upgrade pip
```

Windows PowerShell：

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
```

## 3. 按使用场景安装依赖

### 3.1 只运行离线校验、测试和 Portal

```bash
python -m pip install -e .
```

基础运行时依赖由 `pyproject.toml` 声明，当前核心第三方包是 `jsonschema[format]`。HTTP 服务、SQLite、文件操作、哈希、进程调用等使用 Python 标准库。

### 3.2 真实 LLM 本体发现

```bash
python -m pip install -e '.[llm]'
```

此 extra 安装 OpenAI Python SDK，供 Responses API Provider 使用。

### 3.3 真实多 Agent Runtime（本阶段）

```bash
python -m pip install -e '.[agent-runtime]'
```

此 extra 安装 OpenAI Python SDK 和 OpenAI Agents SDK。Pydantic 由 Agent SDK 的依赖关系提供，项目的结构化输出模型位于 `src/ontology_software_factory/agent_models.py`。

如需同时使用 LLM Provider 和 Agent Runtime：

```bash
python -m pip install -e '.[llm,agent-runtime]'
```

### 3.4 PostgreSQL / MySQL Schema 连接器

```bash
python -m pip install -e '.[postgres]'
python -m pip install -e '.[mysql]'
```

也可一次安装全部可选 Python extras：

```bash
python -m pip install -e '.[llm,agent-runtime,postgres,mysql]'
```

不要为了只运行 Portal 而安装全部 extras；按实际连接的系统选择即可。

## 4. 验证安装

```bash
make validate
make test
```

没有 Make 时可直接执行：

```bash
PYTHONPATH=src python scripts/validate_architecture_baseline.py
PYTHONPATH=src python scripts/validate_ontology_consumers.py
PYTHONPATH=src python -m unittest discover -s tests -v
```

`make validate` 会执行架构基线、MVP 范围、本体、资产目录、Agent 契约、多 Agent 拓扑、Workflow、本体发现和消费者引用检查。完整测试命令是 `make test`。

## 5. 可选外部工具

以下不是基础 Python 安装依赖，但启用对应功能时需要在操作系统 PATH 中安装：

| 可执行程序 / 服务 | 用途 | 是否必需 |
|---|---|---|
| Semgrep CLI（`semgrep`） | 静态分析 | 可选；按质量策略启用 |
| Gitleaks CLI（`gitleaks`） | 秘密扫描 | 可选；生产策略可能要求 |
| Trivy CLI（`trivy`） | 漏洞 / 配置 / 依赖扫描 | 可选；生产策略可能要求 |
| Git CLI（`git`） | 本地仓库元数据 | 可选 |
| PostgreSQL 服务 | 读取数据库 Schema | 仅连接 PostgreSQL 时需要 |
| MySQL 服务 | 读取数据库 Schema | 仅连接 MySQL 时需要 |
| MCP Server 进程 | MCP stdio 工具适配 | 仅配置 MCP 工具时需要 |
| NVIDIA Auto Ontology 服务 | 只读语义目录导入 | 仅使用该适配器时需要 |
| Cognee 服务 / 客户端 | 候选知识图暂存 | 仅显式集成时需要 |

外部 CLI 请按各自官方安装文档安装；本仓库不下载或自动升级这些程序。扫描器未安装、未执行或没有真实报告时，不能把扫描结果标记为通过。

## 6. 首次启动 Portal

```bash
make portal
```

浏览器打开：

`http://127.0.0.1:8770`

首次运行会创建本地目录：

- `.local-portal/state.json`：Portal 本地状态、候选、版本快照和治理记录。
- `.local-portal/demo-catalog.sqlite3`：本地合成数据的 SQLite 示例库。
- `config/integrations/sources.json`：数据源配置（如果尚不存在）。

这些均为本地运行数据，不应提交到 Git。不要把 Portal 暴露到公网或未经保护的局域网。

## 7. 安装真实 Agent Runtime 的凭据

在运行 Agent 的同一个 shell 中设置：

```bash
export OPENAI_API_KEY='由密钥管理器注入的 API Key'
export OPENAI_MODEL='你的账户有权调用的模型 ID'
export AGENT_TRACE_ENABLED=false
```

Windows PowerShell：

```powershell
$env:OPENAI_API_KEY = '由密钥管理器注入的 API Key'
$env:OPENAI_MODEL = '你的账户有权调用的模型 ID'
$env:AGENT_TRACE_ENABLED = 'false'
```

不要把密钥写入源代码、JSON 配置、任务载荷、文档或 Git。项目不会自动加载 `.env` 文件。Agents SDK tracing 默认关闭；只有完成数据留存和隐私评估后才考虑启用。

检查基础 API 连通性：

```bash
make llm-check
```

这只验证 Responses API 可用，不代表 Agent 工作流、任务契约和本体版本绑定全部通过。

## 8. 可选数据库集成测试

真实数据库集成测试默认跳过。只有准备好专用、非生产测试数据库后，才设置：

- `FACTORY_TEST_POSTGRES_DSN`
- `FACTORY_TEST_MYSQL_DSN`

再执行：

```bash
make test
```

测试只读取 Schema 元数据；请勿将生产凭据用于测试。PostgreSQL 连接需要合规 TLS 配置，MySQL 连接启用主机名校验。细节见 `docs/2026-10-30-evidence-lifecycle-and-live-db-checks.md`。


## 9. Agent 工作区执行配置（新增）

真实 Agent Workflow 会在系统临时目录创建每个 run 独立的仓库副本，不需要额外 Python 包。工作区文件读写、测试和扫描的工具边界与证据格式见 docs/controlled-workspace-execution.md。

默认情况下，tests.run 不会在宿主机执行 Agent 生成的代码。只有可信本地演示才可显式设置：

    export FACTORY_ENABLE_UNSANDBOXED_TEST_EXECUTION=1

安全扫描工具默认不启动；安装 Semgrep、Gitleaks 或 Trivy 并评估扫描边界后，才设置：

    export FACTORY_ENABLE_LOCAL_SECURITY_SCANS=1

这两个开关都不是生产沙箱的替代品。固定命令和超时不能阻止不可信代码访问宿主机文件或资源；生产使用前必须接入容器/微虚机、网络隔离、资源配额和短期凭据。未设置开关时，工具应返回 blocked，而不是伪造通过状态。


## 10. 受控 Agent 执行后端（新增）

### Docker 测试执行器

需要安装并启动 Docker Engine / Docker Desktop。构建本项目测试镜像：

    make docker-test-image

# 等价命令：docker build -f runners/container/Dockerfile.test-runner -t ontology-software-factory-test-runner:py311-v1 .

在 Agent Workflow Console 启动前设置：

    export FACTORY_ENABLE_CONTAINER_EXECUTION=1

执行器只使用本地镜像（不自动 pull），无网络、只读 rootfs、丢弃 Linux capabilities、非 root 数字 UID/GID，并限制 PID、内存和 CPU。若镜像不存在，测试结果为 incomplete，不会回退到宿主机。

### Git Worktree

若希望每个 Run 使用真实本地 Git 分支，而非仓库副本：

    export FACTORY_WORKSPACE_BACKEND=git-worktree

要求项目根目录本身是 Git 仓库且安装 Git CLI。创建分支形如 agent/run-run-xxxxxx。该功能不会 commit、push、创建 PR 或 merge。

### Run 级 Skill 锁

Agent Workflow Console 在创建 Run 时自动锁定该 Workflow 中所有 Agent Role 和 Skill 的版本/内容摘要。运行期间修改对应 JSON 或 SKILL.md 会导致该 Run fail closed；请发布新的 Role/Skill 版本并创建新 Run，而不要修改正在执行的 Run。

### 安全扫描边界

Semgrep、Gitleaks、Trivy 目前仍通过本机 CLI 显式调用：

    export FACTORY_ENABLE_LOCAL_SECURITY_SCANS=1

它们尚未迁入 Docker 扫描容器；生产环境应由部署方通过独立隔离扫描服务执行。不要把 Docker 测试执行器误认为扫描器也已容器化。


## 11. 容器安全扫描与 Agent 放行门禁

容器扫描模式需要 Docker Engine 和三个预先拉取的 scanner 镜像。生产环境必须使用不可变 digest，不得配置 latest：

    export FACTORY_ENABLE_CONTAINER_SECURITY_SCANS=1
    export FACTORY_SEMGREP_IMAGE='registry.example/semgrep@sha256:<64位digest>'
    export FACTORY_GITLEAKS_IMAGE='registry.example/gitleaks@sha256:<64位digest>'
    export FACTORY_TRIVY_IMAGE='registry.example/trivy@sha256:<64位digest>'
    export FACTORY_TRIVY_CACHE_DIR='/var/lib/factory/trivy-cache'

镜像需由运维方提前拉取到本机 Docker Engine；运行时不自动 pull。Trivy cache 必须提前填充。Semgrep 使用仓库内 runners/container/semgrep-rules.yml 的离线基础规则。容器扫描对工作区只读、证据目录可写、无网络，并使用资源与权限限制。

如果设置 FACTORY_ENABLE_CONTAINER_SECURITY_SCANS，容器扫描优先于本机 CLI。FACTORY_ENABLE_LOCAL_SECURITY_SCANS 是宿主机扫描回退，不建议用于不可信候选代码。

真实 Agent Workflow 的 security-review 阶段会执行放行门禁：必须同时具备 Docker python-unit-tests、Semgrep、Gitleaks、Trivy 的成功报告和 SHA-256。任一扫描发现会阻断；缺少工具、镜像、Trivy cache 或报告会标记 incomplete，并且不会进入可放行状态。该门禁目前只对 Agent Workflow 的 workspace 证据生效，不替代既有 Kafka 配置包质量门禁。
