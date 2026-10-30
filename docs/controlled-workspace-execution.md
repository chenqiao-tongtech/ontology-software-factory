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

先在 Portal 中建立并批准活动本体快照，再在 Agent Workflow Console 中创建运行。工作区会在第一次 Agent 步骤执行时按 run ID 创建，并在同一 Workflow Run 后续步骤中复用。

## 测试执行开关

**默认不在宿主机执行 Agent 生成的代码。** tests.run 在未显式开启时返回 blocked，不会启动子进程。

只有在可信本地演示环境中、理解代码执行风险后，才可显式开启：

    export FACTORY_ENABLE_UNSANDBOXED_TEST_EXECUTION=1

允许的 suite ID：

- kafka-profile-regression：运行 Kafka 配置验证回归测试。
- python-unit-tests：运行工作区中的完整 unittest 测试集。

执行器使用固定 argv、shell=False、最小化环境变量、无 stdin 和最长 120 秒超时；结果包含 suite ID、退出码、耗时、命令标识、日志与 JSON 报告 SHA-256。模型不能提交自定义 shell 字符串。

**重要：固定命令和独立目录并不等于 OS 沙箱。** 目前宿主机进程仍可访问该用户有权访问的文件和系统资源。不要在生产机或含敏感凭据的开发机上开启此开关执行不可信代码。生产执行必须先接入容器/微虚机沙箱、只读基础镜像、资源配额、网络隔离、短期凭据和审计。

## 安全扫描开关

默认不启动外部扫描器。确认安装工具并评估其运行边界后，显式开启：

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

## 当前未实现的边界

- 尚未创建真实 Git worktree/分支，也没有 push、PR 或 merge 能力；repository.branch.write 是隔离副本内的候选文件写入工具。
- 尚未把测试和扫描进程放入容器/微虚机；默认关闭宿主机执行。
- 尚未实现 run 级 Skill 文件锁；Ontology Snapshot 已在 Run 级固定，Skill digest 仍按 Task/Result 记录。
- 尚未把扫描报告自动接入所有产品交付 Quality Gate；当前工具输出可作为证据输入，仍需策略层消费并判定。
- 工作区位于本机临时目录，不是多租户生产存储；清理和保留周期由本地操作员负责。

## 验证

    PYTHONPATH=src python -m unittest tests.test_workspace_execution tests.test_agent_runtime_policy -v
    make test

测试覆盖工作区复制、源仓库不变、文件读取/写入白名单、路径穿越、隐藏文件、符号链接、默认禁止宿主机测试执行、固定 suite ID 和真实运行证据摘要。测试中的 subprocess 使用 Mock，不会在 CI 中执行 Agent 生成的代码，也不会启动真实扫描器。
