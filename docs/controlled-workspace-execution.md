# 受控工作区、测试执行与安全扫描

## 本阶段实现

真实 Agent Workflow 现在可以为每个 Workflow Run 创建一个独立的仓库副本，并向相应角色注册以下工具：

| Tool ID | 作用 | 写入/执行边界 |
|---|---|---|
| workspace.read | 读取当前运行工作区中的文件 | 只读；限定项目目录、拒绝隐藏路径、路径穿越和符号链接 |
| repository.branch.write | 写入代码/测试/文档候选文件 | 仅写入当前运行的仓库副本；不创建 Git 分支、不推送、不合并 |
| architecture.plan.write | 写入架构计划或 ADR 草案 | 仅允许 docs/agent-proposals/ 与 docs/adr-drafts/ |
| tests.run | 运行固定测试套件 | 只接受固定 suite ID，不接受 Shell 命令或任意参数 |
| security.scan | 运行 Semgrep、Gitleaks 或 Trivy | 只接受固定 scanner ID 和固定参数 |

每个运行工作区默认位于系统临时目录下的 ontology-software-factory-workspaces/<runId>/，与源代码 checkout 分离。它由仓库快照复制而来，忽略 Git 元数据、虚拟环境、缓存、本地运行数据库和交付目录。Agent 的候选写入不会修改主工作区。

## 首次运行与配置

不需要新增 Python 第三方依赖，工作区复制、路径校验、进程调用和 SHA-256 使用 Python 标准库。

    python -m pip install -e '.[agent-runtime]'
    export OPENAI_API_KEY='由密钥管理器注入'
    export OPENAI_MODEL='你的账户有权调用的模型 ID'
    export AGENT_TRACE_ENABLED=false
    make agent-workflow-console

先在 Portal 中建立并批准活动本体快照，再在 Agent Workflow Console 中创建运行。创建 Run 时会同时计算所有 Agent Role JSON、关联 Skill JSON 和 SKILL.md 的 SHA-256，并将 Workflow ID/版本、本体快照 ID/摘要及 Role/Skill 摘要写入 Run 的 runtimeContractLock。每个 Worker 步骤执行前重新核验；任一 Role/Skill 内容发生变化，当前 Run 会 fail closed，不会静默使用新版本。修改后需创建新 Run。该摘要是完整性校验，不是由外部 KMS 签名的供应链证明。

## 测试执行开关

**默认不执行 Agent 生成的代码。** 推荐使用 Docker 容器执行固定测试套件。先构建项目测试镜像：

    make docker-test-image

# 等价命令：docker build -f runners/container/Dockerfile.test-runner -t ontology-software-factory-test-runner:py311-v1 .

确认 Docker Engine 可用且本地已有该镜像后，在可信开发环境显式开启：

    export FACTORY_ENABLE_CONTAINER_EXECUTION=1

容器使用 `--network=none`、只读 rootfs、丢弃 Linux capabilities、`no-new-privileges`、PID/内存/CPU 限制、非 root 数字 UID/GID，并且只挂载当前 Run 工作区。镜像使用 `--pull=never`，运行时不会自动下载镜像。镜像构建阶段需要按企业镜像策略联网安装 Python 包；生产部署建议将基础镜像固定到 digest，并在 CI 构建、签名和扫描后推送到内部 Registry。

仅当 Docker 不可用、且确认代码完全可信时，才允许本地演示模式（不推荐）：

    export FACTORY_ENABLE_UNSANDBOXED_TEST_EXECUTION=1

如果同时设置了容器和宿主机开关，容器执行优先。

允许的 suite ID：

- kafka-profile-regression：运行 Kafka 配置验证回归测试。
- python-unit-tests：运行工作区中的完整 unittest 测试集。

执行器使用固定 argv、shell=False、无 stdin 和最长 120 秒超时；结果包含 suite ID、退出码、耗时、执行后端、日志与 JSON 报告 SHA-256。模型不能提交自定义 shell 字符串。Docker 镜像缺失时返回 incomplete，不会自动 pull，也不会回退到宿主机执行。

**重要：固定命令和独立目录并不等于 OS 沙箱。** 目前宿主机进程仍可访问该用户有权访问的文件和系统资源。不要在生产机或含敏感凭据的开发机上开启此开关执行不可信代码。生产执行必须先接入容器/微虚机沙箱、只读基础镜像、资源配额、网络隔离、短期凭据和审计。

## 安全扫描开关

推荐通过容器扫描器运行。运维方先将 Semgrep、Gitleaks、Trivy 镜像拉入受控本地 Registry/主机，并将每个镜像 digest 配置为完整的 repo@sha256:... 值：

    export FACTORY_ENABLE_CONTAINER_SECURITY_SCANS=1
    export FACTORY_SEMGREP_IMAGE='registry.example/semgrep@sha256:<64位digest>'
    export FACTORY_GITLEAKS_IMAGE='registry.example/gitleaks@sha256:<64位digest>'
    export FACTORY_TRIVY_IMAGE='registry.example/trivy@sha256:<64位digest>'
    export FACTORY_TRIVY_CACHE_DIR='/var/lib/factory/trivy-cache'

Trivy cache 必须由可信运维流程预先填充。容器扫描无网络、只读挂载源工作区、仅证据目录可写、只读 rootfs、capability drop、no-new-privileges 和资源限制。运行时只 inspect 本地镜像，不自动 pull。Semgrep 使用仓库内 runners/container/semgrep-rules.yml 离线规则集。

仅当容器扫描不可用、且可信操作员接受宿主机执行风险时，才使用本机 CLI 回退：

    export FACTORY_ENABLE_LOCAL_SECURITY_SCANS=1

扫描器 ID 固定为：

- semgrep
- gitleaks
- trivy

缺少可执行文件时返回 incomplete；超时、报告缺失或 JSON 无法解析也返回 incomplete；扫描器返回发现时返回 findings，不会伪装成通过。报告和日志保存在工作区的 .agent-evidence/security/，并记录摘要。Trivy 使用本地缓存数据库参数，不在该调用中主动更新数据库；如果本地数据库不可用，结果可能是不完整。

扫描范围是当前工作区快照，不自动证明部署镜像、外部依赖仓库、运行时环境或生产集群安全。Semgrep 自动规则配置可能需要网络访问，部署方应按企业规则源和网络策略进一步收紧。

## 证据位置

每个工作区内：

    .agent-evidence/
    ├── tests/
    │   ├── python-unit-tests.json
    │   └── python-unit-tests.log
    └── security/
        ├── semgrep.json
        ├── semgrep-report.json
        ├── gitleaks.json
        └── trivy.json

实际文件只在相应工具执行后产生。上面是目录示意，不表示每次运行都会有所有报告。JSON 报告和日志各自计算 SHA-256；报告中的 status 仅代表本地工具执行状态，不自动等同于质量门禁最终 PASS。

## Git Worktree 候选分支

默认仍使用独立仓库副本。若项目根目录是 Git 仓库且 Git CLI 已安装，可显式切换为真实本地 Worktree 和每 Run 本地分支：

    export FACTORY_WORKSPACE_BACKEND=git-worktree

创建前要求源仓库 Git 工作区干净；创建后会得到 `agent/run-<run-id>` 本地分支。Agent 的候选写入落在该 Worktree 中，Patch 仍会保存为可审查证据。该能力不 push、不创建 GitHub/GitLab PR、不 commit，也不 merge；运行时不暴露 Git 任意命令。若分支或 Worktree 已存在但与预期不一致，会拒绝复用。

## 当前未实现的边界

- Git Worktree 目前只创建本地分支；尚未实现受控 commit、远程 push、PR 创建和审批后合并。
- Docker 隔离已覆盖固定 Python 测试套件；Semgrep/Gitleaks/Trivy 仍是显式启用的本机 CLI 扫描器，不应把它们描述为容器内扫描。
- Agent Workflow 的 security-review 阶段已加入 fail-closed 证据门禁：要求 Docker Python 单元测试和 Semgrep/Gitleaks/Trivy 三份容器扫描报告都成功并具有报告摘要，发现项则阻断，缺失/不完整则保持不放行。
- Run 级 Role/Skill 锁定当前通过内容摘要检测漂移；不把 Skill 历史文件内容复制进 Run，也不提供外部签名或 KMS 证明。
- 尚未把扫描报告自动接入所有产品交付 Quality Gate；当前工具输出可作为证据输入，仍需策略层消费并判定。
- 工作区位于本机临时目录，不是多租户生产存储；清理和保留周期由本地操作员负责。

## 验证

    PYTHONPATH=src python -m unittest tests.test_workspace_execution tests.test_agent_runtime_policy -v
    make test

测试覆盖工作区复制、源仓库不变、文件读取/写入白名单、路径穿越、隐藏文件、符号链接、默认禁止宿主机测试执行、固定 suite ID 和真实运行证据摘要。测试中的 subprocess 使用 Mock，不会在 CI 中执行 Agent 生成的代码，也不会启动真实扫描器。
