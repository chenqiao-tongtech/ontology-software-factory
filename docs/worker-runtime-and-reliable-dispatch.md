# Worker 执行器与可靠任务派发（第 20 篇配套文档）

## 1. 目标与边界

本文档在第 19 篇的 Workflow Run / Step 模型之上增加独立的任务队列、Worker 执行契约、租约与结果证据。当前实现使用 Python 标准库和 SQLite，适合本地开发、契约验证及单机参考；它不是分布式生产队列。

- `SQLiteTaskStore`：持久化任务、幂等键、租约、重试时间、结果和事件。
- `TaskWorker`：按 `taskType` 分发至明确注册的 Handler，统一处理超时、失败分类与证据校验。
- `enqueue_workflow_step`：将第 19 篇正在运行的 Step 转成任务信封，包含 `runId`、`stepId`、工作流尝试次数和业务操作 ID。
- `run_worker_console.py`：只开放 `demo.echo` 与 `demo.generate-evidence` 两个演示 Handler 的本地操作台。

**没有接入真实 LLM、代码仓库写入、测试命令或部署能力。** 工作流步骤到任务队列的状态回写仍需由项目级适配器实现，并用 outbox/reconciliation 处理跨存储原子性。

## 2. 状态模型

`queued → running → succeeded`

失败后可进入 `retry_wait`，到期后可再次被领取；不可重试错误进入 `failed`；重试耗尽或运行中租约耗尽进入 `dead_letter`。每次转移都会写入事件账本。

## 3. 幂等键分层

1. **入队幂等键**：同一个 `idempotencyKey` + 同一任务定义重复提交会返回原任务；同键不同 payload/task type 会报 `IdempotencyConflict`。
2. **单次工作流任务键**：`enqueue_workflow_step` 使用 `workflow:{runId}:{stepId}:attempt:{n}`，防止同一次工作流尝试重复派发。
3. **业务副作用键**：payload 另附稳定的 `businessOperationId={runId}:{stepId}`。真实 Worker 应把它传给目标系统（若支持 idempotency key），因为队列本地的唯一约束不能撤销远端已经发生的副作用。

不能承诺端到端 exactly-once。更诚实的目标是持久化、at-least-once 执行、业务侧幂等，以及可审计的重复执行与补偿。

## 4. 租约与故障恢复

Worker 原子领取一条已到期任务，并获得 `leaseOwner` 与 `leaseExpiresAt`。只有当前租约持有者且租约仍有效，才能 heartbeat、complete 或 fail。下次轮询发现过期租约时，调度器将任务转为 `retry_wait`，或在次数耗尽后写入 `dead_letter`。

这是一个单机参考实现。多进程可使用 SQLite `BEGIN IMMEDIATE` 进行演示级互斥；高吞吐/多主机场景应改用支持条件更新、租约和可靠队列的托管服务或数据库，并评估队列可用性与数据保留。

## 5. 超时与取消

任务声明 `timeoutSeconds`，`TaskContext.check_deadline()` 可被 Handler 协作式调用；Worker 还会检查返回时的耗时。**Python 线程里的任意阻塞调用无法安全强杀**，因此此 MVP 不把返回后检测等同于硬超时。实际执行 Git、pytest、容器构建或不可信代码时，应在独立子进程/容器/Job 中设置系统级超时、资源限额、网络策略和清理流程。

## 6. 重试

任务须声明 `retryableErrorClasses`、`maxAttempts`、基础与最大退避。仅当错误类别白名单匹配才自动重试；未知错误默认失败，避免将程序缺陷或权限拒绝无限重放。退避按 `base * 2^(attempt-1)` 并封顶；正式系统可增加 jitter、全局速率限制、熔断与按错误类别的策略。

## 7. 执行证据

一个证据对象必须含 `type`、`uri` 和 64 位 SHA-256。若任务声明 `requiredEvidence`，完成前必须逐项提供对应类型。URI 必须指向真实的对象存储/制品库，且哈希应由生产者根据实际字节计算；demo handler 使用 `demo://` 地址，仅用于测试契约，不能作为真实交付证据。

## 8. 本地运行

```bash
python -m unittest discover -s tests -v
python scripts/run_worker_console.py --host 127.0.0.1 --port 8766
```

打开 `http://127.0.0.1:8766`，创建演示任务后点击“运行一个任务”。默认数据库为 `data/worker-runtime/worker_tasks.sqlite3`，已通过 `.gitignore` 排除。

## 9. 接入真实 Agent / 工具

新增 Handler 时：

- 使用稳定的 `taskType` 版本化名字；拒绝任意用户输入的 Python/import/命令。
- Handler 只使用最小权限凭据；任务 payload 不得携带明文密钥。
- 设置输入大小、工具白名单、网络目的地、CPU/内存/时间限额。
- 将模型/工具调用、输入输出摘要、代码 commit、测试报告、安全扫描与制品哈希写成可追溯证据。
- 完成任务后由 workflow adapter 校验 `runId + stepId + attempt + revision`，再推动第 19 篇状态机；不要让 Worker 任意改变别的运行状态。
- 对“外部副作用已成功、本地任务结果未提交”的崩溃窗口，使用下游幂等键、Transactional Outbox、回查/对账或补偿流程。

## 10. 推荐生产化替换点

| 当前参考实现 | 生产化方向 |
|---|---|
| SQLite 队列 | 托管任务队列 / PostgreSQL + outbox / 专用工作流引擎 |
| 同进程 Handler | 独立 Worker 容器或 Job |
| 时间检查 | 子进程/容器的硬超时与资源限额 |
| 本地 demo 证据 | 对象存储 + 制品清单 + hash 校验 |
| 单一错误白名单 | 分错误类别、按 SLA 和成本配置重试策略 |
| 任务事件表 | 结构化日志、指标、Trace 与不可变审计存储 |
