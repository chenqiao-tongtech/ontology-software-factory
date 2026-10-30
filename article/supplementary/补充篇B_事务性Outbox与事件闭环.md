# 第 21 篇｜把软件工厂真正闭环：事务性 Outbox、事件回放与工作流状态回写

**副标题：从“Worker 已经做完”到“工作流可靠地知道做完了”**

> 本文是《本体论在 AI 工程中的实践》软件工厂工程实现线第 21 篇。接续第 19 篇工作流状态机、第 20 篇 Worker 任务队列，解决两套模块之间最容易被忽略的工程问题：执行结果如何可靠地回到工作流。

上一章我们把 Worker、任务队列、租约、重试与执行证据做了出来，也明确指出了一个尚未闭合的缺口：**Worker 的任务状态已经成功，不等于 Workflow Run 已经收到结果。**

想象这样一次执行：代码生成 Worker 完成了任务，并将任务标记为 `succeeded`；就在准备通知工作流时，进程崩溃。工作流仍停留在“代码生成中”，调度器可能再次派发任务。反过来，如果工作流已经处理完结果，但 Relay 在确认消息之前崩溃，事件也可能重复发送。

这不是简单加一个 HTTP 回调就能解决的。它涉及两个持久化边界、消息重投、事件幂等，以及过期执行结果的隔离。本篇我们把这条链路接起来：

**Workflow → Worker Task → Task Result + Outbox → Relay → Workflow Inbox → Run 状态推进。**

---

## 一、为什么“任务成功”还不等于“流程成功”？

在软件工厂里至少有三种事实需要分别记录：

1. **执行事实**：某个 Worker 领取了任务，运行了哪一次尝试，最后成功还是失败。
2. **交付事实**：任务实际产出了什么结果与证据，例如测试报告、构建摘要或制品地址。
3. **编排事实**：工作流是否接受该结果，当前步骤是否完成，是否可以推进下一个步骤。

它们彼此关联，但不能被压缩成一个布尔值。任务执行成功，可能因为证据不完整而无法通过工作流契约；旧尝试的结果可能在新尝试已经开始后才到达；工作流也可能已经被操作者取消。

因此，我们需要一个“结果集成协议”，而不是直接把 Worker 的状态字段复制给 Workflow。

### 配图建议 1：画出完整执行闭环

**建议位置：** 放在本节之后，帮助读者第一眼理解系统的两个事务边界。

**图片生成提示词：**

> 生成一张适合微信公众号技术文章的 16:9 横向架构信息图，主题“AI 软件工厂的工作流执行闭环”。从左到右清晰展示 Workflow Engine / Workflow Run、Task Queue、Worker、Task Database + Transactional Outbox、Outbox Relay、Workflow Inbox + Revision Check、Workflow Run 状态推进；用实线箭头表现事件流，用两个带边框的事务区域分别圈出“生产者事务：Task Status + Task Event + Outbox Event 原子提交”和“消费者事务：Workflow Run + Workflow Event + Inbox 去重原子提交”。标出 at-least-once delivery、eventId deduplication、stale-attempt fencing。风格专业、简洁、深蓝与青绿色科技配色、文字准确清楚，不要出现无意义英文，不要虚构厂商品牌，不要 3D 装饰。

---

## 二、事务性 Outbox：把“状态变化”和“待发送事件”一起提交

一个常见但不可靠的写法是：

```python
mark_task_succeeded(task_id)
publish_workflow_result(task_id)
```

两步之间发生崩溃，任务已成功，但通知丢失。如果把顺序反过来，又可能出现“消息已发出，而任务事务最终回滚”的问题。这就是典型的双写窗口。

事务性 Outbox 的做法是：**Worker 将任务终态、任务事件账本和待发送的集成事件写入同一个本地数据库事务。** 事务提交后，Relay 再扫描 Outbox 并负责投递。

第 21 篇的参考实现中，当任务进入 `succeeded`、`failed` 或 `dead_letter` 等终态时，`task_runtime.py` 会根据任务载荷里的 `workflowRunId` 和 `workflowStepId` 写入 `integration_outbox`。如果任务仍处于 `retry_wait`，则不会提前通知工作流“这个步骤最终失败了”。

这里的重点不是事件一定马上送达，而是**只要任务终态已经提交，相应的待投递事件就不会因为应用进程在下一行代码崩溃而消失**。

### Outbox 事件包含什么？

集成事件携带 `eventId`、`taskId`、`idempotencyKey`、`workflowRunId`、`workflowStepId`、`workflowAttempt`，以及成功时的 `output` 和 `evidence`，或失败时的 `errorClass`、`errorMessage`。

这些字段不是为了让日志看起来丰富，而是为了让消费者能够回答三个问题：**这是哪个任务的结果？属于哪条工作流、哪一个节点？它是不是当前仍有效的那一轮尝试？**

参考工程新增的事件契约位于：`contracts/schemas/workflow-integration-event.schema.json`。

---

## 三、Relay：让事件“至少送达一次”，而不是假装只送达一次

Outbox Relay 负责领取待发送事件、调用工作流投影器，并在消费者事务完成之后确认事件。

事件状态可以理解为：

```text
pending → leased → delivered
            │
            ├── 可恢复错误 → pending（延迟重试）
            └── 超过投递上限 → dead_letter
```

Relay 领取事件时会设置租约。若 Relay 在处理过程中宕机，租约到期后事件可再次被领取。若连续失败达到上限，事件进入死信状态，应由监控告警和运营流程接手。

但必须接受一个事实：Relay 可能完成了工作流状态回写，却在更新 Outbox 为 `delivered` 之前崩溃。这时同一个事件会被再次发送。

所以，我们的承诺应该是**至少一次投递（at-least-once delivery）**，而不是“整个系统端到端只执行一次”。在多个独立事务和外部副作用之间，后者不是一句配置就能保证的。

---

## 四、Workflow Inbox：让重复事件不重复推进流程

消费者端需要保存已经处理过的 `eventId`。第 21 篇给 Workflow Store 增加了 `workflow_inbox` 表，其 `integration_event_id` 是唯一键。

处理一条结果事件时，系统在同一个接收端事务中完成：

- 更新 Workflow Run 和 Step 状态；
- 追加 Workflow Event 审计记录；
- 插入 Inbox 的已消费事件 ID。

如果同一个 `eventId` 被再次投递，Inbox 唯一键和去重检查确保工作流不会再次推进，也不会再次增加 Run revision。这个事务的原子性很关键：不能只更新 Run、却没保存 Inbox；否则重投后仍可能重复消费。

还要注意，Inbox 去重不是“任何事件都能套用”。在接受结果之前，投影器还会验证当前 Run 状态、当前 Step、工作流 attempt 和必需证据。

### 配图建议 2：重复投递与幂等消费

**建议位置：** 放在本节末尾。

**图片生成提示词：**

> 生成一张 16:9 技术流程图，说明“Outbox 至少一次投递 + Inbox 幂等消费”。左侧 Relay 第一次发送 eventId=EVT-123，右侧 Workflow Consumer 在同一事务内写入 Run 更新、Workflow Event 和 Inbox 的 EVT-123；随后 Relay 因未收到确认再次发送同一 eventId，消费者识别重复后返回 deduplicated，不再次推进 Run。用两个独立事务框标注生产者事务与消费者事务，不要把它们画成一个全局事务。加上“不是端到端 exactly-once”的醒目注释。风格为简洁工程架构图、浅色背景、箭头与数据库图标清晰、中文为主，适合微信公众号配图。

---

## 五、迟到的结果尤其危险：用 attempt fencing 防止旧结果覆盖新状态

幂等处理解决的是“同一个事件的重复投递”，但还有另一类问题：**不同事件中的旧结果**。

例如，代码生成步骤第一次执行超时，工作流允许重试并启动第二次尝试。随后第一次 Worker 终于返回成功。如果系统只检查 `taskStatus == succeeded`，就可能用旧结果覆盖第二次尝试。

因此，本篇对工作流节点结果实施 fencing：检查事件携带的 `workflowAttempt` 是否仍与当前 Step 一致，同时检查它是否还是当前运行节点。若步骤已变化、attempt 已更新、运行已取消或已经进入终态，结果会作为 `worker.result_ignored` 记录下来，而不是复活工作流或覆盖新状态。

同样，工作流暂停时，Relay 不应该把结果直接确认为已消费。参考实现会延后处理，等工作流恢复后再继续投影。

这说明：**事件 ID 去重与业务状态校验是两道不同的防线。** 前者防重复，后者防过期、越序和不合法的状态迁移。

---

## 六、证据不是附属文本，而是交接协议的一部分

如果一个 Step 声明需要 `test-report` 或 `security-scan` 等证据，Worker 返回成功状态本身还不够。工作流投影器会核验结果里的证据类型，缺少必需证据就拒绝将该节点标记为成功。

当前演示 Handler 只会生成 `demo://` 占位证据，附带 SHA-256 形式的摘要，用于测试事件链路。它不是真实测试报告、构建制品、安全扫描结果，也不代表代码已经部署。

生产环境需要把证据 URI 绑定到真正的制品存储，并进一步验证访问权限、内容摘要、来源任务、生成工具版本和保留策略。尤其要避免把 Agent 的自然语言描述当作“测试通过”的证明。

---

## 七、打开统一控制台，跑通一条完整链路

本篇新增 `apps/integrated-console/index.html` 和 `scripts/run_integrated_console.py`。它把 Workflow Run、Worker Task、Outbox 事件、执行证据和工作流事件账本放到一套本地操作台中。

运行：

```bash
python -m unittest discover -s tests -v
python scripts/run_integrated_console.py --host 127.0.0.1 --port 8767
```

浏览器打开 `http://127.0.0.1:8767`，依次执行：

1. 创建 Workflow Run；
2. 派发当前 Step，观察 Worker Task 和稳定幂等键；
3. 运行一次 Worker，观察任务进入终态并产生 Outbox 事件；
4. 执行 Relay 或 Drain Outbox；
5. 检查 Workflow Step 是否推进，以及 `executionTaskId`、结果与证据是否已经回写；
6. 重放已处理的 Outbox 事件，确认相同 `eventId` 不会再次推进流程。

### 配图建议 3：闭环监控台

**建议位置：** 放在本节运行步骤之后，展示读者最终可以观察到的界面。

**图片生成提示词：**

> 生成一张适合技术公众号的 16:9 Web 控制台产品概念图，标题“Software Factory · Closed-loop Execution Console”。深色侧边栏与清爽浅色主工作区，展示顶部 Workflow Runs / Worker Tasks / Pending Outbox / Delivered 统计卡片；中部左侧工作流步骤时间线，右侧任务详情与证据摘要；底部 Outbox Event Ledger，列出 eventId、status、deliveryAttempts、lastError。包含“Dispatch Step”“Run Worker”“Relay Once”“Drain Outbox”“Replay Event”等控制按钮。画面像真实 SaaS 管理台截图，不要添加真实品牌标志；中文/英文 UI 文本可读、布局整洁，不要虚构数据暗示生产部署成功。

---

## 八、本篇的工程边界与下一步

本篇实现了两个独立事务之间的可靠交接协议：生产者通过 Outbox 避免任务与待发送事件的双写丢失，消费者通过 Inbox 去重，工作流状态机通过 revision、当前节点和 attempt 检查保护业务状态。

然而，这仍是一套单机参考实现：

- Outbox Relay 在本地 SQLite 上运行，不是高可用消息代理；
- Workflow 与 Task Store 虽可使用同一个 SQLite 文件便于演示，但各自使用独立连接和事务，不能视为跨 Store 的单个原子事务；
- 事件重试、死信与重放需要在生产环境接入指标、告警、操作权限和保留策略；
- 对外部写库、合并代码、创建云资源、发布部署等副作用，仍需要业务级幂等键或对账机制；
- 本地控制台没有生产认证与授权，只应绑定 `127.0.0.1`。

AWS Prescriptive Guidance 对事务性 Outbox 的说明指出，该模式用于解决数据库更新与消息发送的双写不一致窗口；消费者仍需考虑重复消息与幂等处理。microservices.io 也强调，Relay 在“发出消息但尚未记录已发布”时崩溃，可能再次发送，所以消费者必须能够安全处理重复消息。

参考资料：

- AWS Prescriptive Guidance — Transactional outbox pattern：<https://docs.aws.amazon.com/prescriptive-guidance/latest/cloud-design-patterns/transactional-outbox.html>
- microservices.io — Transactional outbox：<https://microservices.io/patterns/data/transactional-outbox.html>

## 结语

真正的 AI 软件工厂，不是每个 Agent 都能说“我完成了”，而是系统能回答：这个任务执行了哪一轮？结果证据在哪里？工作流是否接收了它？如果事件重复、Worker 崩溃或旧结果迟到，系统是否仍然可恢复、可解释、可审计？

**任务队列让工作开始，Outbox 让结果不会轻易丢失，Inbox 让重复结果不重复改变状态，而本体与状态机共同决定这个结果是否有资格推进下一步。** 这才是从多 Agent 协作走向工程闭环的关键一环。
