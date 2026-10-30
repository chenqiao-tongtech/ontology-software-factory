# 第 20 篇工程说明：MCP、工具权限与受控执行

## 实现范围

- `tool_registry.py` 按角色声明、平台工具白名单、已注册处理器三者交集执行 default-deny。
- 每个工具声明输入 Schema、副作用等级和审批要求；调用端无法从 payload 选择 Python callable 或 Shell 字符串。
- `adapters/mcp_stdio.py` 提供可测试的 MCP stdio JSON-RPC 客户端骨架，MCP server 命令来自管理员审核配置，不来自 Agent。
- MCP 连接层过滤继承环境变量，避免默认把 `OPENAI_API_KEY` 等秘密传给子进程。

## 安全边界

该实现不等同于 OS 沙箱、远程 IAM 或完整企业 MCP 网关。生产接入时还需要容器/微虚机隔离、只读文件系统、资源配额、受控网络、短期凭证、server 供应链审查和调用审计。工具授权必须在服务端执行，不能信任模型自述的角色。

## 验证

```bash
python -m unittest tests.test_tool_registry tests.test_mcp_stdio -v
```

MCP 测试使用仓库内固定的 fixture server，不会访问外网或调用真实企业服务。


## Agent Runtime 工具接入补充

真实 Agent Workflow 已将 workspace.read、repository.branch.write、architecture.plan.write、tests.run 和 security.scan 注册到运行时工具集合。工作区由 WorkspaceManager 按 Workflow Run 创建为源仓库的独立副本；工具写入不会改变当前 checkout，也不会创建、推送或合并 Git 分支。

测试执行默认关闭宿主机执行；只有显式设置 FACTORY_ENABLE_UNSANDBOXED_TEST_EXECUTION=1 才会运行固定 suite ID。安全扫描默认关闭，需显式设置 FACTORY_ENABLE_LOCAL_SECURITY_SCANS=1，并且 Semgrep/Gitleaks/Trivy 必须已安装。所有结果写入工作区 .agent-evidence 并生成 SHA-256。固定命令、独立目录和超时并不构成 OS 沙箱；生产执行仍需容器/微虚机隔离。

详见 [受控工作区、测试执行与安全扫描](controlled-workspace-execution.md)。
