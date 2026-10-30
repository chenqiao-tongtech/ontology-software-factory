# 通往AI之桥｜本体论在 AI 工程中的实践（第 20 篇）

# 给 Agent 一张工单，而不是一句“你去干吧”：构建可恢复的 Worker 执行器与可靠任务派发

*软件工厂工程实现线 · 第 20 篇*

上一篇，我们把需求分析、架构设计、代码实现、自动化测试、安全审查与发布审批串成了工作流状态机，并用控制台观察运行过程。但还有一个关键问题：当控制台把某个节点标记为“运行中”，究竟是谁在执行？如果 Worker 崩溃、任务重复派发、执行超时，或者任务已经产生外部副作用但还没来得及写回结果，系统该怎么办？

这就是本篇的主题：**将工作流节点转换为有身份、有时限、有重试策略、有输出契约、有执行证据的任务，并交给受控 Worker 执行。**

我们会在第 18 篇 Agent / Skills、第 19 篇工作流状态机的基础上，增加可运行的本地任务队列、Worker 运行时和任务控制台。代码只使用 Python 标准库，方便你把新增模块增量合并到既有 `ontology-software-factory` 仓库。

> 本篇交付的是单机参考实现，不是生产级分布式任务平台。演示 Handler 不会运行真实 LLM、构建代码或部署服务；这些边界会在文中明确区分。

---

## 一、为什么 Workflow 不等于 Worker？

先回顾两个不同的对象。

- **Workflow Run / Step**：描述业务流程现在走到哪里、哪些依赖已满足、是否需要人工审批，以及下一步允许发生什么。
- **Worker Task / Attempt**：描述一项具体工作由哪个执行器领取、执行了几次、租约何时过期、返回了什么结果、证据在哪里。

如果把二者混为一谈，系统很容易陷入以下局面：界面显示节点正在执行，但没有办法知道任务是否真的被接收；Worker 崩溃后节点永远卡在 `running`；重试一次可能重复创建分支、发布制品或发起扣费；一次“成功”的自然语言回复又被误当成了测试报告。

因此，本体层需要明确区分这些实体：

| 实体 | 关键属性 | 主要责任 |
|---|---|---|
| `WorkflowStep` | run、依赖、角色、状态、尝试次数 | 决定业务流程能否推进 |
| `WorkerTask` | taskType、payload、queue、幂等键 | 描述待执行的工作 |
| `TaskAttempt` | workerId、开始时间、超时、错误分类 | 描述一次具体执行 |
| `Lease` | 持有者、有效期、续租时间 | 限制谁可以提交当前尝试结果 |
| `ExecutionEvidence` | 类型、URI、SHA-256、产生时间 | 证明任务输出是什么、存放在哪里 |
| `IdempotencyKey` | 作用域、请求摘要、业务操作 ID | 抑制重复创建与重复副作用 |

**本体论在这里的价值不是给对象贴标签，而是明确哪些状态可以转换、什么输入才合法，以及一项任务在被认为完成前必须留下什么证据。**

### 配图建议 1：Workflow 与 Worker 的双层对象模型

图片生成提示词：`横向 16:9，现代企业软件架构信息图，白色背景，左侧蓝色区域展示 Workflow Run / Step 状态机，右侧紫色区域展示 Worker Task / Attempt / Lease / Evidence，对应箭头从 Workflow Step Dispatch 到 Task Queue，再到 Worker Execution，结果与 Evidence 回写，使用中文短标签、细线、清晰留白、工程设计文档风格，不要品牌 Logo，不要小字堆叠。`

---

## 二、任务不是一段 Prompt，而是有契约的信封

给 Worker 派活时，不要只发送“帮我实现接口”。应发送一个机器可解析的任务信封，例如：

```json
{
  "taskType": "workflow.step.implementation",
  "idempotencyKey": "workflow:RUN-1048:implementation:attempt:1",
  "queue": "default",
  "payload": {
    "runId": "RUN-1048",
    "stepId": "implementation",
    "workflowAttempt": 1,
    "businessOperationId": "RUN-1048:implementation",
    "input": {
      "repository": "product-service",
      "changeRequest": "add validated customer profile endpoint"
    }
  },
  "maxAttempts": 3,
  "timeoutSeconds": 3600,
  "retryableErrorClasses": ["transient", "timeout", "worker_lost", "rate_limited"],
  "requiredEvidence": ["commit-reference", "change-summary"]
}
```

这份数据定义了执行对象、输入、重试边界、超时和验收证据，不负责替代代码生成、测试策略或安全策略。真正执行时，Worker 仍必须检查角色权限、工具白名单、敏感数据访问范围和执行环境。

工程实现位于 `src/ontology_software_factory/task_runtime.py`。它提供 `SQLiteTaskStore.enqueue()` 与 `enqueue_workflow_step()`，可把第 19 篇状态机中正在运行的步骤转换成上述任务信封。对于一项工作流尝试，重复派发会复用已有任务，而不是无声地创建第二份。

注意：入队幂等键与业务副作用键不是同一回事。参考实现为每次 Workflow Step Attempt 使用 `workflow:{runId}:{stepId}:attempt:{n}`，同时提供跨重试稳定的 `businessOperationId={runId}:{stepId}`。后者应传递给实际副作用的下游系统。

---

## 三、先接受一个事实：可靠派发不等于 Exactly Once

这是任务系统设计中最容易被夸大的地方。

假设 Worker 收到任务后创建了一个远程 Git 分支，接着进程崩溃，尚未把“成功”写回队列。调度器无法凭空知道分支是否已经创建；再次派发后，第二个 Worker 可能又创建一次。即使队列自身能识别重复消息，它也不能撤销已经发生的远端副作用。

因此，本文采用的语义是：

1. **持久化入队**：先写任务记录和事件，再返回给调用方。
2. **至少一次执行**：任务可能在租约过期后重新执行，因此 Handler 必须考虑重复运行。
3. **业务幂等**：把稳定业务操作 ID 传递到代码仓库、工单、云 API、支付或发布系统；目标系统支持幂等键时优先使用。
4. **执行结果可回查**：结果、证据、状态变化及错误分类持久化，支持重试和对账。
5. **无法原子化的边界显式化**：对外部系统成功、本地写入失败的窗口，使用 outbox、回查/对账或补偿流程处理。

Google Cloud Tasks 官方文档也明确说明其任务采用至少一次投递，处理代码需要对重复执行保持安全。这里借鉴的是分布式任务系统的通用原则，而不是声称我们的 SQLite 实现拥有托管云队列的高可用能力。[参考：Cloud Tasks 概览](https://docs.cloud.google.com/tasks/docs/dual-overview)

### 配图建议 2：重复派发的崩溃窗口

图片生成提示词：`16:9 扁平技术流程信息图，展示 Dispatcher 入队 -> Worker 调用外部系统 -> Worker 崩溃 -> 未提交本地结果 -> Queue 重试 -> 第二次调用的故障链；旁边用稳定的 businessOperationId 和下游幂等检查把重复副作用收敛，白色背景，蓝灰配色，关键风险节点用橙色，箭头准确，中文标签清晰。`

---

## 四、租约：让“我正在执行”变成可过期的承诺

任务从 `queued` 进入 `running` 时，调度器会原子地写入：

- `leaseOwner`：当前 Worker 的 ID；
- `leaseExpiresAt`：租约过期时刻；
- `attempts`：递增后的执行次数；
- 一条 `task.claimed` 事件。

只有租约所有者、并且租约仍有效，才能提交 heartbeat、complete 或 fail。过期后，旧 Worker 的写入会被拒绝；后续轮询将任务恢复为 `retry_wait`，或者在次数耗尽后放入 `dead_letter`。

这个机制叫 fencing 的简化版本：它限制旧执行者修改队列的当前状态。但是，租约不能阻止已经发出的网络请求、已写入的代码或已经触发的部署。**租约保护状态，业务幂等保护副作用，二者缺一不可。**

示例实现使用 SQLite 的 `BEGIN IMMEDIATE` 将领取操作串行化，便于开发者理解状态竞争。多主机生产环境需要重新评估存储、队列、锁、吞吐、故障域和恢复时间，不能直接把这个单机方案横向复制就当成高可用。

---

## 五、失败策略：不是所有错误都该重试

如果所有错误都简单地“再试一次”，权限拒绝、输入结构错误、策略违规和程序 Bug 也会被反复执行，浪费成本并扩大风险。

本篇将错误分为三类：

- **瞬时失败**：限流、临时网络错误、Worker 丢失、可恢复超时，可以根据白名单重试。
- **确定性失败**：输入不合法、权限不足、证据不合格，不应该自动重试，应返回给上游修正或进入人工处理。
- **未知失败**：默认按不可重试处理并保留异常摘要；由运行治理人员分析后调整分类，而不是放任自动循环。

重试次数用 `maxAttempts` 控制，退避采用指数增长并设置封顶。参考代码的核心策略是：

```python
wait_seconds = min(backoff_max, backoff_base * 2 ** (attempt - 1))
```

生产系统通常还应加入随机抖动（jitter），避免大量任务在同一秒同时重试；还需要并发上限、速率控制、熔断、重试预算和死信告警。Google Cloud Tasks 的重试配置同样提供最大尝试次数与最大/最小退避参数，相关参数可作为托管实现选型时的参考。[参考：重试配置](https://docs.cloud.google.com/tasks/docs/configure-retry-task)

### 配图建议 3：任务失败分流策略

图片生成提示词：`16:9 现代技术流程图，中心为 Worker Task Failure，分三支：transient / timeout / worker_lost -> retry_wait -> queue；invalid_input / permission_denied / invalid_evidence -> failed 并通知上游；超出 maxAttempts -> dead_letter 与人工排查。右侧标注 exponential backoff、lease expiry、audit events，极简工程图风格，中文标签、专业可读。`

---

## 六、完成条件：输出之外，还必须提交证据

对于软件工厂，Worker 说“代码已完成”毫无意义。任务可能要求以下证据：

- 代码提交引用和变更摘要；
- 自动化测试报告、覆盖率摘要；
- 依赖漏洞扫描、秘密扫描结果；
- 构建制品的 URI、版本和 SHA-256；
- 发布清单、审批记录和部署结果。

因此，任务可声明 `requiredEvidence`。每份证据至少需要 `type`、`uri` 与 `sha256`。队列只有在必需证据类型齐全、哈希格式合法时，才允许把任务标记为 `succeeded`。

哈希只能证明“某份证据内容与某个摘要一致”，不自动证明报告真实、测试充分或结论正确；还需要受信任的生产者身份、制品签名、存储访问控制和验证流程。本地 demo 仅生成 `demo://` URI 与示例摘要，目的是验证契约，绝不能冒充真实测试报告。

这也说明了本体模型与 Agent 的分工：Agent 可以生成候选输出，工具可以执行操作，但系统必须依据类型、约束、权限和证据规则决定是否接受结果。

---

## 七、运行本篇配套代码

工程包加入了一个独立的 Worker Console。它提供任务列表、创建任务、处理一个已到期任务、查看结果证据和事件历史。

### 1. 验证代码

```bash
python -m unittest discover -s tests -v
```

### 2. 启动控制台

```bash
python scripts/run_worker_console.py --host 127.0.0.1 --port 8766
```

浏览器打开 `http://127.0.0.1:8766`，创建“生成演示证据”任务，再点击“运行一个任务”。任务完成后，查看输出和事件账本。

### 3. 运行时实现结构

```text
src/ontology_software_factory/task_runtime.py
  SQLiteTaskStore
    enqueue / claim / heartbeat / complete / fail
  TaskWorker
    taskType -> registered Handler
    timeout / error-class / evidence contract
  enqueue_workflow_step()
    Workflow Run + Step -> Worker Task envelope

scripts/run_worker_console.py
apps/worker-console/index.html
contracts/schemas/worker-task.schema.json
tests/test_task_runtime.py
docs/worker-runtime-and-reliable-dispatch.md
```

控制台只允许 `demo.echo` 和 `demo.generate-evidence` 两个处理器，没有任意命令执行能力。当前 Worker 同样不会真实调用 LLM 或 CI/CD；真实业务必须通过经过审查和授权的 Handler 适配器接入。

---

## 八、从 MVP 到生产环境，还差什么？

不要把这份参考工程误认为完整生产平台。下一步至少要补上：

1. **真正的执行沙箱**：代码修改、依赖安装、测试和构建应运行于独立容器/Job，限制网络、CPU、内存、磁盘、权限与执行时长。
2. **可靠的工作流回写**：任务队列和 Workflow Run 跨存储更新时，使用事务性 Outbox、可重放事件或对账任务，处理两边状态不一致的崩溃窗口。
3. **身份与密钥治理**：认证、RBAC/ABAC、短期凭证、秘密管理，以及工具调用边界的二次授权检查。
4. **可观测性**：为 Workflow Run、Step、Task、Attempt 和 Agent Call 传递同一组 trace/correlation IDs；建立队列积压、失败率、重试率、租约超时、成本和延迟指标。
5. **运行治理**：死信队列、人工重放、补偿工作流、重试预算、并发限制、速率限制与告警。
6. **证据供应链**：真实制品库 URI、摘要重算、签名/来源证明、权限边界与留存策略。

---

## 结语：Agent 负责思考，Worker 负责受控执行，证据负责证明

如果说第 18 篇定义了岗位，第 19 篇定义了流程，那么第 20 篇开始定义真正的执行边界：什么时候一项工作被接收、由谁执行、可以执行多久、失败后如何恢复、什么条件下结果被认可。

多 Agent 软件工厂绝不是让一群模型互相发送 Prompt。它是一套由本体、契约、调度器、执行器、权限、证据和审计共同组成的生产系统。

**让 Agent 生成建议，让 Worker 在边界内行动，让状态机决定是否推进，让可验证证据决定结果是否被接受。** 这才是从“AI 演示”走向“AI 工程”的关键一步。

---

### 参考资料

- Google Cloud, *Understand Cloud Tasks*：https://docs.cloud.google.com/tasks/docs/dual-overview
- Google Cloud, *Set retry parameters for a task*：https://docs.cloud.google.com/tasks/docs/configure-retry-task

*本篇代码为本地参考实现。SQLite 队列、demo:// 证据和演示处理器仅用于工程教学与契约验证，不能直接用作生产执行环境。*
