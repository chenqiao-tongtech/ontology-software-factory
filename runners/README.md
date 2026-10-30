# runners/

## 运行时组件

- `runners/restricted_runner.py`：固定命令、参数白名单、超时和无 shell 调用；不是 OS 沙箱。
- `runners/container/Dockerfile.test-runner`：构建固定 Python 测试镜像。
- `src/ontology_software_factory/workspace_execution.py`：Run 级仓库副本 / Git Worktree、路径白名单、候选写入、测试与扫描证据。

## Docker 测试执行

    docker build -f runners/container/Dockerfile.test-runner -t ontology-software-factory-test-runner:py311-v1 .
    export FACTORY_ENABLE_CONTAINER_EXECUTION=1

容器无网络、只读 rootfs、丢弃 Linux capabilities、no-new-privileges、限制 PID/内存/CPU，只挂载当前 Run 工作区，且不自动拉取镜像。建议生产构建时固定基础镜像 digest、扫描并签名最终镜像。

## Git Worktree

    export FACTORY_WORKSPACE_BACKEND=git-worktree

要求项目根目录是 Git 仓库。每个 Run 创建 `agent/run-<run-id>` 本地分支；不会 commit、push、创建 PR 或 merge。

## 安全扫描

Semgrep/Gitleaks/Trivy 仍是显式启用的本机 CLI：

    export FACTORY_ENABLE_LOCAL_SECURITY_SCANS=1

不要把它们描述为容器扫描。宿主机测试回退开关 `FACTORY_ENABLE_UNSANDBOXED_TEST_EXECUTION=1` 仅供可信代码本地演示，不得用于不可信 Agent 输出。

更多说明：`docs/controlled-workspace-execution.md`。


## 容器安全扫描

操作员需预先拉取并按 digest 固定三类镜像，然后设置：

    export FACTORY_ENABLE_CONTAINER_SECURITY_SCANS=1
    export FACTORY_SEMGREP_IMAGE='registry.example/semgrep@sha256:<digest>'
    export FACTORY_GITLEAKS_IMAGE='registry.example/gitleaks@sha256:<digest>'
    export FACTORY_TRIVY_IMAGE='registry.example/trivy@sha256:<digest>'
    export FACTORY_TRIVY_CACHE_DIR='/var/lib/factory/trivy-cache'

镜像必须在本地存在；不自动 pull。Trivy cache 需预先填充。容器禁网、只读挂载工作区，证据目录单独可写，rootfs 只读、capability drop、no-new-privileges 和资源限制。Semgrep 使用本地离线规则 runners/container/semgrep-rules.yml。

Agent Workflow 的 security-review 阶段要求容器 Python 测试和三类扫描均成功且有 SHA-256 报告证据才允许放行；findings 会阻断，缺失或 incomplete 不会放行。
