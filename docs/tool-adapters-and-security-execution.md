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
