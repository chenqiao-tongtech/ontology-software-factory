# P1 Harness 运行时治理实施记录

> 日期：2026-10-31  
> 阶段：P1 统一运行时与治理控制面  
> 实施分支：work/five-phase-delivery-2026-10-31  
> 状态：第一轮代码增量已提交；仍需本地全量测试与真实 Provider 验收。

## 1. 本轮目标

在不替换现有 Harness、Tool Registry、Runtime Contract Lock、Task Runtime 和 Workflow Store 的前提下，补齐两项 P1 控制面缺口：

1. Run 级工具预算检查必须以持久化 usage ledger 为准，不能只依赖当前 Python 进程内的内存计数。
2. Agent Run 生命周期事件与工具调用审计进入同一 metadata-only audit stream，且不记录 Prompt、模型输出、工具 payload 或 Secret。

## 2. 代码变更

### 2.1 Harness 持久化预算检查

文件：`src/ontology_software_factory/harness.py`

- 工具调用前通过 `usage(run_id)` 读取权威计数。
- 配置 `usage_store` 时，预算判断使用持久化账本返回的 `toolCalls`；新建 HarnessRuntime 实例或进程重启后不会因为本地计数归零而放宽预算。
- 达到 `min(max_tool_calls, max_run_tool_calls)` 时，在调用 ToolRegistry Handler 前抛出 `HarnessBudgetExceeded`。
- 账本写入仍在工具实际派发前执行，采用保守计费策略：已授权派发但 Handler 失败的调用也计入调用预算。

### 2.2 统一 Agent 生命周期审计

文件：`src/ontology_software_factory/harness.py`、`src/ontology_software_factory/agent_runtime.py`

新增 `HarnessRuntime.record_lifecycle_event()`，并在 OpenAI Agents Runtime 的执行边界记录：

- `agent.run.started`
- `agent.run.completed`
- `agent.run.failed`

事件字段包括 Run、Task、Principal、Role、Tenant、Project、Policy Version/Digest、状态和白名单元数据。元数据只允许记录 Workflow ID/Version、本体快照 ID/Digest、Runtime Contract Lock Digest、Provider/Model、耗时、错误类型和工具数等标量字段。

**明确不写入**：Prompt、完整 Task 输入、模型输出、Tool payload、Secret、原始 SDK 异常内容。工具调用事件继续保留既有的结果 SHA-256，而不是原始结果正文。

### 2.3 回归测试

新增 `tests/test_harness_governance.py`：

- 持久化 Run 工具调用数达到上限时，在 Handler 执行前拒绝。
- 生命周期审计只保留白名单元数据，不包含 prompt/apiKey/payload 字段。

## 3. 执行链路

当前 OpenAI Agents SDK 适配器执行链路：

1. 校验 Ontology Binding 与 Run-level Runtime Contract Lock。
2. 校验 Role、Skill 和 Tool Policy 版本/摘要。
3. 创建 Harness Principal 并组装受限上下文。
4. 从 Role、Policy 和实际 Handler 交集中确定工具白名单。
5. 检查 Run 级 Token 预算。
6. 写入 `agent.run.started` 元数据事件。
7. 激活当前执行的 Harness Context；Agent 工具函数只能通过 `_invoke_harness_tool()` 进入 Harness。
8. Harness 再经 ToolRegistry 做角色授权、审批检查、JSON Schema 输入校验后调用可信 Handler。
9. 记录真实 SDK usage（如果 SDK 返回）；校验结构化输出。
10. 写入 completed/failed 生命周期事件，并复位 ContextVar。

## 4. 验证状态

本轮通过 GitHub 文件写入接口提交代码与测试文件，但当前执行环境没有直接运行仓库 Python 测试的本地 checkout，也没有可用的仓库 CI workflow run 结果。因此：

- **代码已写入分支**：是。
- **新增测试已写入分支**：是。
- **本轮 Python 测试已执行**：否。
- **GitHub Actions 已验证**：尚无对应成功的 CI 运行证据。
- **真实 OpenAI Agents SDK / 外部 Tool / MCP 已验收**：否。

在本地仓库根目录执行：

```bash
python -m pip install -e .
python -m unittest tests.test_harness_governance tests.test_agent_runtime_harness tests.test_agent_runtime_policy
make validate
make test
```

如果项目测试目录不是 Python package，可直接使用：

```bash
python -m unittest discover -s tests -p 'test_harness_governance.py'
python -m unittest discover -s tests
```

## 5. 本轮仍未覆盖的 P1 项目

以下项目仍需后续增量，不能因本轮改动而标记为完成：

- 将 MCP、HTTP Connector、Portal 所有写操作及非 OpenAI Provider 统一接入同一个 Tool Gateway。
- 在 Run/Task 状态机中统一取消、超时、重试和取消后的迟到结果处置。
- 将 Approval 作为独立、可验证的记录贯穿所有高风险 Tool Invocation；不能只依赖调用参数或本地 actor 字符串。
- 将 Evidence Contract 统一为 Run/Task/Input Digest/Tool Version/Exit Code/Report Digest/Status，并由存储层校验来源绑定。
- 为 Tool Invocation 增加跨进程幂等键与外部副作用去重协议。
- 增加 Run 级并发额度、时间额度、费用额度与可观测的拒绝原因。
- 为历史无 Runtime Contract Lock 的 Run 建立只读兼容路径。
- 增加策略漂移、跨租户、审批缺失、取消、重复请求和失败重试的端到端负向测试。

## 6. 安全与部署边界

本轮依旧是单机参考实现。SQLite usage ledger 不能替代多节点原子预算服务；本地 JSONL audit 文件不能替代防篡改审计存储；OpenAI Agents SDK 的执行接入不能证明其他 Agent Framework、MCP Server 或 Portal 路径均已受控。生产部署仍需要 IAM/SSO、PDP、Secret Broker、隔离执行器、集中式事件/证据存储和外部安全验收。


## 7. 第二轮 P1 增量（2026-10-31）

### 7.1 CI 失败定位与修复

首次 PR CI 执行 364 项测试时发现两处问题：

- 生命周期审计写入使用了双重转义换行，导致 JSONL 文件的多条事件被拼接为一行；已修正为标准单行 JSON + LF。
- 持久化预算检查在调用 Usage Store 原子记账前做了 read-then-check，预算拒绝没有写入 `budget_exceeded` 账本事件；已改为持久化模式由 Usage Store 在同一原子操作中完成预算判断和计数，保留拒绝事件，并将单 Agent/Run 的有效限制设为两个配置上限的较小值。本地内存模式仍在锁内检查和递增。

### 7.2 Task 取消与迟到结果隔离

文件：`src/ontology_software_factory/task_runtime.py`

新增 `SQLiteTaskStore.cancel(task_id, actor, reason)`：

- 通过 SQLite `BEGIN IMMEDIATE` 事务完成状态检查、状态更新和事件写入。
- 已进入终态的任务保持原状态，不重复取消。
- 取消运行中任务时清除 Worker Lease，后续 Worker 调用 `complete()` 或 `fail()` 将因 Lease/状态不匹配而失败，不能复活任务。
- 未知 Task 拒绝关闭（fail closed）。

限制：Python Handler 线程不能被安全强杀。取消会阻止迟到结果提交，但不能撤销已经发生的外部副作用；Handler 必须检查取消/截止状态，并对外部写操作使用幂等键和补偿/对账机制。

新增 `tests/test_task_runtime_cancellation.py` 覆盖排队任务取消、运行任务取消后的迟到完成拒绝和未知任务拒绝。

### 7.3 第二轮验证

以上修复和新增测试已推送到本 PR 分支。GitHub Actions 将对最新提交重新执行 `make validate` 与 `make test`。在新的 check run 完成前，不将 P1 标记为 CI 通过。
