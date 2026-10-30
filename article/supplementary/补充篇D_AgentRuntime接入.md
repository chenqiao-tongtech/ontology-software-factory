# 第23篇｜给大模型戴上工程工牌：接入 Agent Runtime，让角色、Skills 与工具权限真正生效

**系列：本体论在 AI 工程中的实践｜软件工厂工程实现线**  
**本篇关键词：OpenAI Agents SDK、Agent Runtime、工具白名单、结构化结果、技能契约、人工审批**

第 22 篇让软件工厂可以真实调用 LLM。但一个直接调用模型的函数，还不等于一个可治理的 Agent。Agent 不只是生成内容；它可能持续多轮推理、调用工具、委托给其他角色，并在过程中积累上下文。

如果没有 Runtime，我们的 `agents/roles/*.json`、`skills/` 和 `policies/agent-permissions.json` 只是一组文件。下一步是让它们进入执行路径：角色决定任务责任，Skill 限定完成方法，策略决定可访问工具，输出契约决定结果能否交给下一环。

本篇采用 OpenAI Agents SDK 作为首个真实运行时。选择它不是要把软件工厂的所有编排都交给第三方框架，而是利用其 Agent 执行循环、函数工具和结构化输出能力；工作流状态、租约、Outbox/Inbox、重试与审计仍由我们自己的工程层负责。

## 一、先分清三个概念

**LLM Provider** 负责一次模型调用。它通常关心 API 请求、模型、超时、Token 和响应格式。

**Agent Runtime** 负责 Agent 如何运行：将角色说明提供给模型、管理执行轮次、验证工具参数、调用允许的工具、处理结构化输出。

**Workflow Orchestrator** 决定企业业务的流程：需求分析后何时进入架构设计、哪个步骤需要审批、任务失败后如何重试、哪些结果可以进入下一状态。

```text
Workflow Orchestrator（自有）
      │ 创建有契约的 Worker Task
      ▼
Worker Runtime（自有）
      │
      ▼
Agent Runtime Adapter（OpenAI Agents SDK）
      ├── Role + Skill
      ├── Typed Output
      └── 允许的函数工具
               │
               ▼
       LLM Provider / Responses API
```

### 配图建议 1：三层边界图

**图片生成提示词：**
> 16:9 横版软件架构信息图，清晰展示 Workflow Orchestrator、Worker Runtime、Agent Runtime Adapter、LLM Provider 四层。突出前三层里工作流状态、任务队列、角色/Skills/工具权限各司其职；外部模型只负责推理。箭头只表示调用方向，不把第三方 Agent 框架画成系统数据库或唯一状态源。中文标签、浅色底、专业架构图风格。

## 二、将 Agent 角色从配置变成运行时对象

本项目已有七类角色，例如 `requirement-analyst`、`solution-architect`、`implementation-agent`、`test-agent` 和 `security-reviewer`。每个角色定义用途、Skills、工具 ID、允许/禁止动作和交接要求。

Runtime Adapter 根据 `roleId` 读取配置，并执行三个步骤：

1. 加载角色用途、输出契约与相应 Skill 文档；
2. 计算角色声明的工具与运行时实际注册工具的交集；
3. 使用 Pydantic 输出模型创建 Agent，运行后将结果转换为 JSON 对象返回。

这里有一个关键安全原则：**角色配置声明“可以”，不等于系统授权“允许”。**

工具能否执行必须在工具实际入口再次检查。若角色 JSON 声明了 `repository.write`，但当前运行时没有实现这个工具，那么它不会因为配置里出现了这个字符串就被执行。`production.deploy`、`secrets.read.raw`、受保护分支合并等高风险能力被全局排除在本 MVP 的工具注册表之外。

## 三、工具不是提示词，而是可执行能力边界

本篇只注册三个低风险工具：

- `documents.read`：读取有限目录中的文档；拒绝绝对路径、`..` 路径遍历、越出仓库的符号链接以及过大的文件。
- `catalog.read`：列出配置中的 Agent Role 和 Skill ID，不访问密钥或客户数据。
- `contract.validate`：使用 JSON Schema 校验输入对象，只返回校验结果，不写文件、不运行代码。

示意代码：

```python
allowed_ids = [
    tool_id for tool_id in role["toolIds"]
    if tool_id not in GLOBAL_DENY_LIST
    and tool_id in RUNTIME_TOOL_REGISTRY
]
agent = Agent(
    name=role["displayName"],
    instructions=role_instructions,
    model=model_name,
    tools=[RUNTIME_TOOL_REGISTRY[item] for item in allowed_ids],
    output_type=OUTPUT_MODELS[role_id],
)
```

这是一个“声明集合 ∩ 实际注册集合 − 全局拒绝集合”的最小权限模型。它还不是完整的企业授权系统：生产环境必须加入用户身份、租户、项目资源、动作级授权、审批与外部审计；不能把上述交集误认为已经解决所有访问控制问题。

OpenAI Agents SDK 将 Agent、工具、结构化输出、Agent handoff、Guardrails 和追踪作为核心能力。官方文档建议从一个聚焦 Agent 开始，再按需要增加工具和专业角色： [Agents SDK Quickstart](https://developers.openai.com/api/docs/guides/agents/quickstart?lang=python)、[Tools](https://openai.github.io/openai-agents-python/tools/)。

## 四、为什么所有 Agent 都需要明确的输出类型？

自由文本结果容易让下游不知道：字段到底缺失了，还是模型选择不提供？一段“测试已通过”的回答，也不代表系统真的运行过测试。

因此，我们为五个关键角色定义 Pydantic 输出模型：

| 角色 | 结构化输出 | 工程用途 |
|---|---|---|
| 需求分析 | `RequirementBrief` | 功能/非功能需求、验收标准、假设、开放问题 |
| 架构设计 | `ArchitecturePlan` | 组件、数据流、安全控制、权衡与问题 |
| 实现规划 | `ImplementationPlan` | 工作项、依赖、候选文件、待人工复核标记 |
| 测试规划 | `TestStrategy` | 测试用例、必要门禁、残余风险 |
| 安全审查 | `SecurityReview` | 严重性、发现、缓解建议与放行建议 |

结构化输出只让结果满足对象结构。它不保证模型做出的判断一定正确。因此，每个字段仍要经过后端校验和流程门禁；测试 Agent 也不能因为计划中存在测试用例，就将工作流直接标记为“测试通过”。

## 五、Skills 怎样真正进入 Agent 的执行过程？

Skill 不能只是一个名字。Runtime 会将角色对应的 Skill 文档内容作为额外指导上下文载入 Agent。Skill 在第 18 篇已经有自己的版本、输入输出和验收标准；本篇让其内容进入真实模型请求。

但是，**把 Skill 文本提供给模型，不代表它的验收条件自动生效**。验收还要由机器可检验规则执行，例如：输出是否包含必需字段、路径是否安全、是否包含验收标准、是否提交必需证据。凡是能够写成确定性规则的内容，就不应仅依赖模型“记得遵守”。

运行时对用户需求、Issue、外部文档和工具返回都视为不可信数据。工具输出不能覆盖系统指令；角色提示词也不能授予工具表以外的新权限。

### 配图建议 2：Agent 的受控执行循环

**图片生成提示词：**
> 画一张 16:9 横版技术流程图：接收 Worker Task → 载入 Role 与 Skill → 计算有效工具白名单 → LLM 推理 → 可选工具调用 → 工具入口授权和参数校验 → 输出 Pydantic 对象 → Agent Result 契约校验 → Workflow 状态回写。绘出工具调用被拒绝时的失败分支，突出“模型提出调用”和“系统实际允许执行”是两个不同步骤。简体中文、清晰的工程图风格。

## 六、如何运行第一个真实 Agent？

安装 Runtime 依赖与设置模型密钥：

```bash
python -m pip install -e '.[agent-runtime]'
export OPENAI_API_KEY='你的 API Key'
export OPENAI_MODEL='gpt-6.1-sol'
export AGENT_TRACE_ENABLED=false
```

第 24 篇的控制台提供真实多 Agent 执行入口。当前 Runtime Adapter 也可在 Python 中创建并调用：

```python
runtime = OpenAIAgentsRuntime(project_root=".")
result = runtime.run_agent("requirement-analyst", {
    "run_id": "manual-check-001",
    "source_requirement": "为一个轻量 Python 服务定义健康检查接口",
})
print(result["output"])
```

`gpt-6.1-sol` 是示例默认值；若当前 API 项目未开通，请换成该项目实际可用的模型 ID。

第一次运行会产生真实模型请求。没有凭据或网络访问时，系统应明确失败，而不是自动用模拟结果掩盖问题。

本地测试使用 Fake Client 和 Fake Agent Runner 覆盖工具权限交集、路径遍历拒绝、结构化输出以及错误路径；这些测试不向模型服务发送请求。

## 七、为什么默认关闭 SDK Trace？

Trace 对调试 Agent 很有价值，但可能携带输入、输出、工具调用和其他执行信息。团队在开启之前必须了解数据是否离开部署边界、哪些角色能够查看、保留期限如何设置，以及是否包含客户或商业敏感信息。

本实现默认关闭 Agents SDK tracing；只有显式设置 `AGENT_TRACE_ENABLED=true` 才开启。该开关是一个本地的隐私默认值，不等于完整的数据治理能力。生产部署还需要租户隔离、日志访问控制、保留/删除策略、调用成本预算、速率限制和可审计的策略变更流程。

### 配图建议 3：角色声明如何收敛成工具权限

**图片生成提示词：**
> 生成一张 16:9 横向工程信息图，展示三层工具授权收敛过程：左侧是 Role JSON 声明的工具集合，中间是 Runtime 实际注册并经过审查的工具目录，右侧是最终生效的交集工具列表。用交集符号表示“声明工具 ∩ 已注册工具 − 全局禁止工具”，在下方标出未注册的 Shell、秘密读取、仓库合并和生产部署工具均不可调用。避免将提示词文字本身画成安全边界；需要突出真正的授权发生在应用程序工具入口。现代企业架构图，简体中文，深蓝和青绿色，留白充足。

## 本篇代码新增内容

- `src/ontology_software_factory/agent_models.py`：五类 Agent 的强类型输出模型。
- `src/ontology_software_factory/agent_runtime.py`：OpenAI Agents SDK Adapter、角色加载和工具白名单收敛。
- `tests/test_agent_runtime_policy.py`：路径安全和最小权限策略测试。
- `docs/agent-runtime.md`：运行方式、工具边界、Trace 与故障处理。
- `docs/adr/0011-openai-agents-runtime-adapter.md`：为何将 Agent Runtime 与 Workflow Orchestrator 分离。

## 结语：Agent 是受约束的执行者，不是权限管理员

现在，角色、Skill 与工具不再只是仓库里的声明文件，它们开始影响真实 Agent 的执行。但模型仍不是权限决策的最终依据：真正的权限在工具入口校验，真正的工作流状态在我们自己的数据库，真正的完成证据来自可验证的结果。

下一篇，我们把需求分析、架构设计、实现提案、测试规划和安全审查串成一条真实多 Agent 流水线，并将候选变更保存在隔离区域。目标不是让 Agent 一下子拥有生产环境的全部权限，而是先让它安全地产出可审查的工程成果。

---

**参考资料**

- [OpenAI Agents SDK Python](https://openai.github.io/openai-agents-python/)
- [Agents SDK Quickstart](https://openai.github.io/openai-agents-python/quickstart/)
- [Agent definitions](https://developers.openai.com/api/docs/guides/agents/define-agents)
- [Tools](https://openai.github.io/openai-agents-python/tools/)
- [Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs)
