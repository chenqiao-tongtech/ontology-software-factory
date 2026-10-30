# runners/

本地固定命令执行器与 Agent Run-scoped Workspace 工具位于：

- runners/restricted_runner.py：固定命令、参数白名单、超时和无 shell 调用；不是 OS 沙箱。
- src/ontology_software_factory/workspace_execution.py：每个 Workflow Run 的仓库副本、文件白名单、候选写入、测试与安全扫描证据。

Agent 生成代码的宿主机测试执行默认关闭。只有可信本地演示并明确接受宿主机执行风险时，才设置 FACTORY_ENABLE_UNSANDBOXED_TEST_EXECUTION=1。安全扫描需显式设置 FACTORY_ENABLE_LOCAL_SECURITY_SCANS=1。生产环境应先接入容器/微虚机沙箱、网络隔离和资源配额。

详细说明：docs/controlled-workspace-execution.md
