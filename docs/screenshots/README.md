# 演示系统截图

这组截图补充展示了第 15–24 篇累计工程中的工作流控制台、Worker 任务、本体发现与维护流程，以及多智能体工作流状态。

## 截图索引

| 文件 | 内容与数据来源 |
|---|---|
| `01-workflow-console-overview.png` | 现有 Workflow Console 的工作流总览、节点状态、审批节点、证据与事件账本。 |
| `02-workflow-console-failed-retry.png` | 现有 Workflow Console 的失败节点与可重试状态。 |
| `03-worker-runtime-evidence.png` | 现有 Worker Console 的任务队列、幂等键、执行结果和证据摘要。 |
| `04-integrated-closed-loop.png` | 现有 Integrated Console 的 Workflow → Task Queue → Worker → Outbox/Inbox 闭环。 |
| `05-ai-runtime-readiness.png` | 现有 AI Runtime Console 的环境检查；截图时没有 API Key，且未安装可选 Agents SDK。 |
| `06-ontology-discovery-pipeline.png` | 由实际运行 `run_ontology_discovery.py --demo`、候选校验与 Benchmark 评测产物整理的流水线视图：术语、关系、约束、Critic、确定性验证和人工复核门。 |
| `07-ontology-definition-review.png` | 从实际候选 JSON 渲染的审查视图，展示术语定义、关系、业务约束、Competency Questions 与来源定位。 |
| `08-ontology-maintenance-approval.png` | 从审批 CLI 实际输出的已批准变更提案渲染的生命周期视图，突出 digest 绑定、版本化提案、语义回归要求与不直接修改正式本体的边界。 |
| `09-ontology-worker-evidence.png` | 由 `run_ontology_discovery_worker_demo.py` 的真实 Worker 任务输出和证据 JSON 整理，包含 Task ID、候选摘要、评测证据 URI 与 SHA-256。 |
| `10-multi-agent-workflow-human-review.png` | 现有 Agent Workflow Console 前端；后端使用临时离线 Fixture Runtime 驱动项目实际 Workflow/SQLite Worker/Outbox/Relay 逻辑。五个专业阶段成功，流程停在人工复核门。**没有调用真实 LLM。** |
| `11-multi-agent-worker-outbox-evidence.png` | 同一多 Agent Fixture 运行中的任务队列和 Outbox 事件账本视图；数据由本地 API 实际状态读取。没有调用真实 LLM。 |
| `00-contact-sheet.png` | 上述 11 张功能截图的缩略总览。 |

## 重要边界

- `01–05` 是仓库现有控制台界面截图。运行、任务与证据可能使用 demo/seed 数据，不代表真实企业 CI/CD 或生产部署结果。
- `06–09` **不是工程内置的本体 Web 管理页面**。当前本体发现功能实际以 CLI、候选 JSON、Benchmark 报告、Worker 任务和审批变更提案实现；这些截图是根据刚刚运行产生的真实 JSON 产物生成的说明性审查视图。该轮使用项目内置离线 Fixture Provider，不调用外部 LLM。
- `10–11` 为现有 Agent Workflow Console 前端配合临时 Fixture Runtime 的截图。工作流状态机、SQLite 任务处理、Outbox/Relay 和证据写入使用项目运行代码；Agent 角色输出是固定样例，不代表真实模型推理或质量结果。正式运行 Agent Workflow Console 仍需要安装可选 SDK、配置凭据并单独验收。
- 本次样例 Benchmark 中的 F1 分数仅用于验证评测管线；不能外推为真实 LLM 在生产领域本体上的精度。候选仍需要领域专家复核，且审批 CLI 仅产生版本化提案，不会写入正式本体文件。
- 本地控制台默认无认证，仅应绑定 `127.0.0.1`，不要直接暴露到局域网或公网。
