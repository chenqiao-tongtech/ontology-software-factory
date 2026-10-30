# 发布说明：本体版本绑定的 Agent Runtime

## 本次交付

将已审批的本体快照绑定到真实多 Agent 执行链路，并补齐可交接的安装与运行文档。

### 运行时实现
- 新增 `ontology_runtime.py`：从 Portal 活动版本目录加载完整快照，重新计算 SHA-256，并核对快照 ID、Ontology Version 和 Schema Version。
- Workflow Run 创建时持久化完整本体快照；每个 Worker Task 复制同一绑定，避免工作流运行期间发布新版本导致阶段间语义漂移。
- Agent Task JSON Schema 增加 `ontologySnapshotId`、`ontologyDigest`、`ontologySchemaVersion`，Agent Result 增加相同绑定字段。
- 每次 Agent 执行前校验 Role、Skill 输入输出类；校验 Skill 与 Role 兼容性、Skill 所需工具是否被 Role 授权；校验 Workflow Step 的 Role / Skill 引用。
- OpenAI Agents Runtime 接收绑定本体的类、关系、受控词汇、不变量及 Skill 契约；返回结构化输出后检查显式实体类型。
- 每个 Agent 阶段生成 `agent-result.json`，并把本体快照摘要写入输出、Result 和 Evidence。

### 运行入口
新增 Make 目标：
- `make llm-check`
- `make ai-runtime-console`
- `make agent-workflow-console`

### 文档
- `docs/installation.md`
- `docs/dependency-inventory.md`
- `docs/ontology-runtime-version-binding.md`
- 更新 `README.md`、Makefile 和两个 Runtime Console 的版本状态展示。

## 安装升级

基础环境：

```bash
python -m pip install -e .
make validate
make test
```

真实 Agent Runtime：

```bash
python -m pip install -e '.[agent-runtime]'
export OPENAI_API_KEY='...'
export OPENAI_MODEL='账户可用的模型 ID'
export AGENT_TRACE_ENABLED=false
```

PostgreSQL / MySQL extras 仅在使用对应 Schema 连接器时安装。完整依赖列表见 `docs/dependency-inventory.md`。

## 首次运行前置条件

必须在 Portal 中创建本体快照，并通过独立 promote 审批设置活动版本。没有活动版本时，真实 Agent Workflow 创建运行请求会失败关闭。

```bash
make portal
# 浏览器访问 http://127.0.0.1:8770
```

然后按 `docs/ontology-runtime-version-binding.md` 完成快照、提案、审批和执行；在另一个终端启动：

```bash
make agent-workflow-console
# 浏览器访问 http://127.0.0.1:8769
```

## 验收边界

本次测试使用 Fake Agent Runtime 验证 Workflow / Worker / Outbox / Inbox / 契约与 Evidence 链路，不会请求外部模型。GitHub Actions 通过只证明代码校验和本地测试通过，不证明当前账户的 API Key、模型可用性、外部 MCP Server、Cognee、NVIDIA 或真实数据库已经联调。

当前 Portal actor 字段仍是本地审计元数据，不是企业身份认证。版本发布更新的是本地 Portal 活动快照目录指针；运行时读取并固定该快照，但尚未对外部服务、数据库或生产部署系统执行全局版本切换。
