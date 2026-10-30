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
