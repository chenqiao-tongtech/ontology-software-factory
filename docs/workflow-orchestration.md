# 工作流编排与运行控制台：架构与 API

## 1. 范围与非目标

本篇提供一个单机、持久化的工作流状态机参考实现。它负责校验状态转换、保存 Run/Step 状态与事件记录，并通过 HTTP API 支持本地控制台。它不运行 LLM，不调度真实 Worker，不执行 shell/CI/CD，也不包含生产身份认证。

## 2. 数据分层

- Definition：`workflows/definitions/software-delivery-v1.json`，版本固定为 `1.0.0`。
- Run：某个 definition 版本的一次运行；包含当前节点、环境、节点状态、attempt、证据占位和错误。
- Event：追加写入的操作记录，包括 actor、action、摘要、时间与有限的结构化 payload。
- Store：SQLite 的 `workflow_runs` 和 `workflow_events` 表。Run 状态更新与事件写入在一个事务中提交，更新使用 revision 做乐观并发检查。

Run payload 当前包含 `revision` 字段以方便 API 返回。生产数据库还应增加显式租户/项目边界、幂等命令 ID、数据保留策略、加密和敏感字段处理。

## 3. 状态机规则

- `complete_step`：只允许当前 Run 正在运行的当前 Step 完成；完成后推进到依赖已满足的下一节点。
- `fail_step`：只模拟当前运行节点失败。默认代表瞬时 Worker/心跳错误；对包含“权限/permission、断言/assertion、schema、策略/policy”等确定性拒绝词样的失败原因，演示引擎将其视为不可重试。生产环境应使用显式错误代码枚举，而不是对自然语言进行推断。
- `retry`：只允许 `failed` Run 中的 `failed` 节点重试，且必须仍可重试并未超过 `maxAttempts`。每次重试都会增加 attempt 并记录事件。
- `approve` / `reject`：只允许在 `waiting_approval` 的审批节点执行，并要求非空理由。
- `pause` / `resume` / `cancel`：由状态机检查当前运行状态；终态不能再次取消。
- 所有变更都用预期 revision 更新；当另一个请求先修改同一 Run 时，当前请求得到 409，而不是覆盖新状态。

## 4. HTTP API

所有 API 由 `scripts/run_workflow_console.py` 提供，默认仅绑定 `127.0.0.1:8765`。

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/health` | 健康检查 |
| GET | `/api/runs` | 返回运行列表 |
| GET | `/api/runs/{runId}` | 返回 Run 与有序事件 |
| POST | `/api/runs` | 创建演示运行；Body: `title`, `requestedBy`, `environment` |
| POST | `/api/runs/{runId}/actions` | 提交操作；Body: `action`, `stepId?`, `note?`, `actor?` |

支持的动作：`complete_step`、`fail_step`、`retry`、`approve`、`reject`、`pause`、`resume`、`cancel`。错误返回 JSON `{ "error": "..." }`，HTTP 状态码用于区分参数错误、找不到运行、非法状态或 revision 冲突。

## 5. 启动 / 校验

```bash
python scripts/validate_workflow_definition.py
python -m unittest discover -s tests -v
python scripts/run_workflow_console.py --host 127.0.0.1 --port 8765
```

停止服务后，如要清空本地演示状态，删除 `data/workflow-console/workflow_console.sqlite3` 及其 SQLite sidecar 文件。该文件包含运行和审批演示记录，不应提交到 Git；`data/workflow-console/.gitignore` 已忽略数据库文件。

## 6. 接生产环境时的必补项

1. 身份认证、RBAC/ABAC，以及审批人与创建人的职责分离。
2. 独立 Worker 与任务队列；HTTP 请求不直接执行耗时或外部副作用。
3. 可靠任务派发（如事务型发件箱）、幂等命令 ID、去重和恢复扫描器。
4. 持久化定时器、超时/心跳、指数退避与最大重试次数。
5. 对外部副作用设计补偿/回滚，并在执行前后记录证据。
6. 把 Agent Task/Result JSON Schema、角色权限矩阵与 Skill 版本绑定到 Step 定义。
7. 结构化日志、trace ID、成本/Token 记录、告警、数据最小化和多租户隔离。
8. 数据库备份、迁移、保留周期、密钥管理和审计只读权限。

## 7. 安全注意事项

此服务没有认证，也没有 CSRF 防护，不应用 `--host 0.0.0.0` 暴露到局域网或公网。按钮中的“模拟节点成功/失败”用于测试状态机，不会运行真实任务。生产版必须在执行工具的边界重新检查身份、权限、租户、状态、输入 schema 和幂等键，不能仅相信前端。
