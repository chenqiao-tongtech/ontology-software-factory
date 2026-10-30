# 第24篇｜让多个 Agent 真正协作：构建一条可审查的 AI 软件生产流水线

**系列：本体论在 AI 工程中的实践｜软件工厂工程实现线**  
**本篇关键词：多 Agent、顺序编排、候选变更、测试策略、安全审查、人工复核**

前两篇完成了真实 LLM Provider 和 OpenAI Agents SDK Runtime 的接入。现在我们终于可以回答最关键的问题：如何让多个 Agent 围绕一条软件需求协作，而不是在聊天窗口里各自给出互不相连的答案？

本篇把五个角色串成一个可运行的纵向切片：

1. **需求分析 Agent** 将原始需求整理为验收标准、假设和待澄清问题；
2. **架构设计 Agent** 根据需求提出组件、数据流与安全边界；
3. **实现 Agent** 生成工作项和候选文件变更；
4. **测试 Agent** 根据需求和候选文件生成测试计划；
5. **安全审查 Agent** 分析变更、测试计划和证据缺口，给出阻断或复核建议。

重要区别：这是一条真实模型驱动的流水线，不是说模型产生的所有结论都天然可信。本篇会真实调用 Agent Runtime，并把生成的候选文件写入隔离产物目录，但**不会自动将变更应用到仓库、执行生成代码、合并分支或部署**。这是刻意设计的安全边界。

## 一、为什么先做顺序协作，而不是任意 Agent 群聊？

多 Agent 最容易出现的问题不一定是能力不足，而是责任不清：多个 Agent 重复分析同一件事；一个 Agent 的假设被下一个 Agent 当作事实；测试 Agent 根据架构描述写出看似合理的测试，却没有对应验收标准；安全审查 Agent 甚至可能审查不到真实文件。

我们的选择是先采用**由工作流拥有流程、由 Agent Runtime 执行单个专业角色**的模式。

```text
Workflow / Worker（决定状态与重试）
          │
          ▼
  需求分析 Agent ── RequirementBrief
          │
          ▼
  架构设计 Agent ── ArchitecturePlan
          │
          ▼
  实现 Agent ────── ImplementationPlan + Proposed Files
          │
          ▼
  测试 Agent ────── TestStrategy
          │
          ▼
  安全审查 Agent ── SecurityReview
          │
          ▼
  候选产物 + 哈希 + 人工复核状态
```

这里的每次交接都是一个 JSON 对象，而不是将上一位 Agent 的整段自然语言随意拼接给下一位。对象中明确区分需求、架构、工作项、文件候选、测试计划和审查结果。本篇提供两种运行入口：轻量直跑控制台用于快速查看五个 Agent 的结构化流水线；持久化工作流控制台则把每个阶段拆成独立 Worker Task，通过第 19～21 篇的状态机、Outbox/Inbox 和事件账本进行状态回写。

### 配图建议 1：五个专业 Agent 的软件生产链

**图片生成提示词：**
> 生成一张 16:9 横版企业技术信息图，展示五个专业 Agent 从左到右协作：需求分析、架构设计、实现提案、测试规划、安全审查。每个节点下面列出对应结构化产物；终点是隔离的候选变更区、SHA-256 哈希、人工复核门禁。明确画出“不会自动合并或部署”的终端边界。扁平矢量风格、深蓝和青绿配色、简体中文。

## 二、每个 Agent 都有单独的输出模型

多 Agent 协作的关键，不是 Agent 数量，而是交接契约。

| 阶段 | 输入 | 输出 | 机器检查点 |
|---|---|---|---|
| 需求分析 | 原始需求 | RequirementBrief | 必须有摘要、验收标准、待澄清问题 |
| 架构设计 | RequirementBrief | ArchitecturePlan | 组件、数据流、安全控制和取舍清楚 |
| 实现规划 | 需求 + 架构 | ImplementationPlan | 工作项可验证，候选文件路径安全 |
| 测试规划 | 需求 + 架构 + 候选文件摘要 | TestStrategy | 每个测试具有可判定断言与类型 |
| 安全审查 | 前序结果 + 文件候选与哈希 | SecurityReview | 风险、缓解措施、证据缺口明确 |

每个输出都由 Pydantic 模型约束。实现 Agent 如果生成非法 JSON、遗漏必需字段或返回了不符合类型的结构，就不能进入下游；安全审查给出 `blocked` 时，整个运行标记为 `blocked`。其他情况也只能进入 `needs_human_review`，不直接标成“生产就绪”。

需要强调：Pydantic 可以验证类型和字段，不能证明需求真实、架构正确或安全结论完整。关键工程事实仍需独立检查和测试。

## 三、候选文件必须进入隔离区，而不是直接改仓库

实现 Agent 可以提出类似这样的文件对象：

```json
{
  "relative_path": "src/example.py",
  "purpose": "提供一个最小 API 示例",
  "content": "def health():\n    return {\"status\": \"ok\"}\n"
}
```

Orchestrator 会检查：

- 路径必须是相对路径，禁止 `..`、绝对路径和隐藏目录；
- 文件扩展名必须位于允许清单；
- 单文件与整次运行的候选内容都有大小上限；
- 同一次运行不能出现重复路径；
- 发现明显的 API Key 或硬编码秘密模式时拒绝写入；
- 产物使用专属 `run_id` 目录，存在同名目录时拒绝覆盖；
- 每个写入文件计算 SHA-256，记录字节数、相对产物地址，并声明 `executed=false`、`applied_to_repository=false`。

这不是完整的 DLP 或静态安全扫描。正则匹配会产生漏报和误报，模型生成的代码也可能存在未被规则发现的漏洞。因此，安全 Agent 的审查意见不能替代真实 SAST、依赖扫描、单元测试和人工 Code Review。

## 四、测试 Agent 不可以“宣布测试通过”

实现阶段生成的是候选文件，测试阶段目前生成测试策略和可自动化的测试案例，而不是声称这些测试已经跑过。

举个例子，测试 Agent 可以输出：

- 单元测试：缺少必需字段时应返回 400；
- 集成测试：`/health` 在正常状态时返回结构化健康状态；
- 安全测试：路径遍历输入被拒绝；
- 验收测试：每项需求至少关联一条可判定标准。

只有后续真实测试执行器在沙箱中执行测试、采集退出码和日志、校验结果后，才能生成 `test_execution` 类型的证据。一个“测试计划文件”与“测试已执行”是两个不同的本体实体，也必须有不同的状态和证据类型。

### 配图建议 2：候选产物的治理流程

**图片生成提示词：**
> 16:9 横向流程图：模型提出文件变更 → 路径/扩展名/大小/秘密模式校验 → 隔离目录写入 → SHA-256 证据记录 → 测试策略生成 → 安全审查 → 人工审核。将“候选代码”与“已执行代码”用不同颜色和图标表示；从候选代码到执行或合并必须经过未来的独立沙箱、CI 和审批。清晰简洁的企业安全架构图，中文准确。

## 五、如何运行真实多 Agent 流水线？

安装可选依赖：

```bash
python -m pip install -e '.[agent-runtime]'
export OPENAI_API_KEY='你的 API Key'
export OPENAI_MODEL='gpt-6.1-sol'
export AGENT_TRACE_ENABLED=false
# 快速纵向切片（单次多 Agent 流水线）
python scripts/run_ai_runtime_console.py --host 127.0.0.1 --port 8768
# 持久化 Workflow → Worker → Outbox/Inbox 闭环
python scripts/run_agent_workflow_console.py --host 127.0.0.1 --port 8769
```

`gpt-6.1-sol` 是示例默认值；若当前 API 项目未开通，请换成该项目实际可用的模型 ID。

浏览器打开 `http://127.0.0.1:8768` 可运行快速流水线；打开 `http://127.0.0.1:8769` 则使用持久化工作流。后者需要反复执行“派发当前节点 → Worker 执行一个任务 → Relay 回写事件”，直到到达人工复核门。每个阶段的输出、证据和候选文件保存在 `data/real-agent-workflow/`。模型默认值是示例配置，务必选择当前 API 项目可用的模型。

也可运行本地自动化测试：

```bash
python -m unittest discover -s tests -v
python scripts/validate_agent_contracts.py
python scripts/validate_workflow_definition.py
```

离线测试通过只证明工程代码的确定性逻辑和边界校验可用。真实多 Agent 端到端验证需要有效 API Key、当前账号可用的模型、网络访问和足够的 API 配额。若模型 API 不可用，系统应失败并留下类型化失败记录，而不是伪造成功结果。

## 六、这条流水线目前还没有做什么？

为了保持边界明确，本篇没有把所有能力一步做到生产级。以下功能仍需后续独立实现：

1. **真正的测试执行**：在容器或其他隔离沙箱中运行代码，收集可验证的日志和退出码；
2. **代码仓库集成**：在临时分支或工作树里生成差异，使用 Git diff、静态扫描和独立 Code Review；
3. **自动调度与租约治理**：当前持久化入口已把五个 Agent 阶段拆为独立 Worker Task，并接入 Outbox/Inbox 与状态回写；仍需实现自动调度守护进程、并发限流、跨进程部署与更强的恢复策略；
4. **成本与用量治理**：按项目和任务实施模型预算、输入长度限制、限流和异常熔断；
5. **正式授权与人工审批**：对代码写入、受保护分支合并、发布、部署和密钥访问分别进行权限校验；
6. **生产可观测性**：按数据策略启用 Trace，关联 task_id、workflow_run_id、agent_role、model 和证据。

这是有意的分阶段工程方案。先让真实 LLM 和多个结构化 Agent 通过一条受控流程产生候选结果，再逐步开放有副作用的工具，比让一个 Agent 同时拥有源仓库写入、Shell、生产部署和策略修改能力更安全，也更易测试。

### 配图建议 3：从参考流水线到生产软件工厂的演进路线

**图片生成提示词：**
> 制作一张 16:9 横版技术路线图，三阶段：阶段一“真实 LLM + 五个结构化 Agent + 隔离候选文件”；阶段二“Worker 持久化调度 + 沙箱测试 + 证据回写”；阶段三“临时 Git 工作树 + SAST/SCA + 人工审批 + CI/CD 受控发布”。标明每个阶段的安全门禁和输出证据，避免写出未经测量的性能数字。现代扁平信息图，适合微信公众号。

## 七、代码库新增内容

- `src/ontology_software_factory/software_factory_pipeline.py`：五阶段顺序编排和候选文件管理。
- `apps/ai-runtime-console/index.html`：真实 LLM 连通性与快速多 Agent 运行界面。
- `apps/agent-workflow-console/index.html`：持久化 Workflow/Worker/Outbox/Inbox 运行界面。
- `src/ontology_software_factory/agent_workflow.py`：将真实 Agent 绑定到既有持久化 Worker 与证据契约。
- `workflows/definitions/agent-proposal-v1.json`：五个模型阶段与一个人工审批门的工作流定义。
- `scripts/run_ai_runtime_console.py`：本地服务端 API，密钥只在进程环境中读取。
- `tests/test_software_factory_pipeline.py`：离线验证顺序、路径限制、秘密模式拒绝和防覆盖。
- `docs/adr/0012-sequential-multi-agent-proposal-pipeline.md`：多 Agent 编排设计决策。

## 结语：第一个真实的 AI 纵向切片已经出现

通过第 22～24 篇，软件工厂从“展示结构和模拟运行”进入真实模型参与的工程流程：LLM Adapter 管理请求边界，Agent Runtime 管理角色和工具，Orchestrator 组织多位专业 Agent，隔离产物区保存可审查的候选变更。

它还不是无人值守的生产发布工厂，但已经有一条可以验证、可以观察、可以继续扩展的真实 AI 生产链。下一阶段应当把它与第 19～21 篇的持久化工作流、Worker 和事件闭环进行生产化整合，并引入沙箱执行器与真实 CI 证据。

---

**参考资料**

- [OpenAI Agents SDK Python](https://openai.github.io/openai-agents-python/)
- [Agent orchestration and handoffs](https://openai.github.io/openai-agents-python/agents/)
- [OpenAI Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs)
