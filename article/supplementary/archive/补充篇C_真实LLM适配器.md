# 第22篇｜让软件工厂真正拥有“大脑”：接入真实 LLM，从模拟输出到模型推理

**系列：本体论在 AI 工程中的实践｜软件工厂工程实现线**  
**本篇关键词：LLM Provider、Responses API、结构化输出、重试、调用观测、密钥治理**

前面几篇，我们逐步搭建了 Agent 岗位与 Skills、工作流状态机、Worker、事务性 Outbox 和状态回写。它们让软件工厂具备了流程、执行和恢复能力，但一直有一个关键限制：部分任务仍使用演示处理器，尚未由真实模型完成推理。

今天开始，我们要让软件工厂第一次真正调用大模型。

但“能请求到模型”只是第一步。企业级工程需要再追问五个问题：模型调用能否替换？输出能否机器验证？超时和限流如何处理？日志会不会泄露需求或密钥？失败后工作流能否得到明确状态？

本篇先把这些问题集中到一个边界清楚的 **LLM Provider Adapter** 中。后续 Agent 框架通过这个工程边界使用模型，而不是把厂商 API 散落在每个 Agent 的代码里。

> 本篇目标：给定一段真实的软件需求，系统能够调用真实模型，得到响应，记录经过脱敏的运行元数据；对于结构化响应，必须经过 Schema 校验后才能进入下游。

## 一、为什么需要 Provider Adapter？

如果每个 Agent 都直接写 `client.responses.create(...)`，很快就会出现：某些模块自行设置重试，有些模块没有超时；部分日志记录完整提示词；更换模型需要修改很多文件；测试不得不访问真实 API。

我们建立一个统一边界：

```text
Workflow / Worker
      │
      ▼
LLMProvider.generate(request)
      │
      ├── 配置：模型、超时、输出预算
      ├── 重试：限流、超时和暂时性服务错误
      ├── 观测：耗时、响应 ID、Token 用量、尝试次数
      ├── 安全：不记录 API Key，默认不保存请求内容
      ▼
Provider Adapter ──► OpenAI Responses API
```

Provider Adapter 只负责一次模型调用的基础设施问题。它不决定需求是否通过、不写代码仓库、不批准发布，也不负责跨 Agent 流程。这些职责仍由已有的工作流、Agent 契约和策略层管理。

### 配图建议 1：LLM Provider Adapter 架构图

**图片生成提示词：**
> 生成一张 16:9 横版企业软件架构信息图，白色或浅灰底、深蓝与青绿色为主色。自上而下展示 Workflow/Worker、统一 LLM Provider Adapter、OpenAI Responses API。Adapter 内用四个清晰模块表示模型配置、限时重试、结构化校验、日志与 Token 观测。侧边标注 API Key 不进入日志、默认不记录完整提示词。简洁矢量风格，中文标签准确，适合微信公众号技术文章配图，不要品牌水印。

## 二、让模型返回可验证的结构，而不是一段“看起来不错”的文字

自然语言适合人与人交流，但工程管线需要稳定的对象。需求分析 Agent 的输出可以包含：需求摘要、功能需求、非功能需求、验收标准、假设、待澄清问题和风险级别。

如果模型只返回一段 Markdown，下游仍要猜测字段边界。我们采用 JSON Schema 约束结构化输出，并在本地再次校验。这是双层防线：上游要求模型按 Schema 返回，下游拒绝不合约的数据。

本仓库的入口是：

```python
provider = OpenAIResponsesProvider()
response = provider.generate(LLMRequest(
    instructions="你是需求分析助手，只依据已提供的信息回答。",
    input="为这个需求给出一段简短分析……",
    max_output_tokens=1200,
))
print(response.output_text)
```

需要结构化对象时，调用 `generate_structured` 并传入明确的 Schema。只有解析成功并通过本地校验的对象才返回给调用方。

示例 Schema：

```json
{
  "type": "object",
  "properties": {
    "summary": {"type": "string"},
    "open_questions": {"type": "array", "items": {"type": "string"}}
  },
  "required": ["summary", "open_questions"],
  "additionalProperties": false
}
```

结构化输出并不能保证内容在事实层面正确，也不能替代业务校验。它解决的是“对象是否满足结构”，不是“对象中的判断是否真实”。具体字段还要接受本体规则、业务约束和人工确认。

OpenAI 的官方文档将 Structured Outputs 定位为通过 JSON Schema 约束响应结构的能力，并说明 Python SDK 支持基于 Pydantic 的对象模式： [Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs)。本项目在 Provider 层使用 Responses API 的 JSON Schema 格式，并保留本地验证。

## 三、重试必须有边界

以下问题通常可能暂时恢复：请求超时、连接错误、HTTP 408、409、429 和部分 5xx。身份验证失败、权限错误、结构化结果不符合 Schema 等问题，不应该盲目无限重试。

本篇实现了有上限的指数退避与随机抖动：

- 模型请求默认超时 45 秒，可按调用覆盖。
- 重试次数最多由配置控制，并有代码级上限。
- 临时错误重试前使用指数退避，并加入随机抖动，减少多个 Worker 同时重试形成的尖峰。
- 最终失败抛出经过脱敏的 `LLMProviderError`，携带是否可重试和实际尝试次数。
- SDK 自带重试被关闭，避免 SDK 重试与应用层重试叠加，导致真实请求次数不可控。

重试策略不是越多越可靠。对有副作用的工具调用，必须另外设计幂等键；不能因为一次模型请求可安全重试，就推断其触发的远程操作也可以重复执行。

## 四、观测有用，但不要把隐私写进日志

一条模型调用日志通常足够包含：Provider、模型名、响应 ID、耗时、Token 数量、尝试次数以及错误类型。不应默认记录 API Key、完整用户提示词、未经脱敏的代码、密钥和其他租户数据。

这里还涉及两个容易混淆的开关：

1. **应用日志**是我们自己的日志格式和保留策略。
2. **模型或 Agent SDK 的 Trace**是额外的可观测数据通道，可能包含输入、输出和工具信息。

本系列后续的 Agent Runtime 默认关闭 SDK Trace，只有在团队明确审核数据处理、权限和保留策略后，才通过 `AGENT_TRACE_ENABLED=true` 开启。日志里出现 `store=False` 也不等同于对所有数据处理作出了通用的合规承诺；实际仍须核对所用产品、账号设置、服务条款和适用法规。

### 配图建议 2：一次模型调用的生命周期

**图片生成提示词：**
> 16:9 横版技术流程信息图，展示一次 LLM 调用从请求创建、身份配置、发送 API、响应解析、Schema 校验、成功记账到失败重试/终止的生命周期。使用清晰箭头和状态分支；把“认证失败”“Schema 错误”画成直接终止，把“超时/429/暂时性 5xx”画成有限重试。旁边放置一个日志面板，只展示模型、延迟、Token 和 response_id，不展示提示词或密钥。高质量企业架构图，不要假数据统计。

## 五、怎样运行真实连接检查？

先安装项目和可选依赖：

```bash
python -m pip install -e '.[llm]'
export OPENAI_API_KEY='你的 API Key'
export OPENAI_MODEL='gpt-6.1-sol'
python scripts/check_llm_connection.py
```

PowerShell 可使用当前终端环境变量命令设置临时值。请勿把真实密钥写进 `.env.example`、README、JSON 配置或 Git 历史。建议使用本地未跟踪的密钥文件、操作系统 Secret Store 或 CI 的 Secret 管理功能。

脚本会发起一条真实请求，并打印响应 ID、延迟、Token 用量和输出文本。没有 API Key、没有网络权限、模型不可用或 API 配额不足时，连通性检查会失败；这并不代表本地单元测试不通过。

`gpt-6.1-sol` 是示例默认值；若当前 API 项目未开通该模型，请改为账号实际可用的模型 ID。

本篇测试通过 Fake Client 验证重试、结构化 Schema 校验、错误分类和使用元数据的行为。这些是离线测试，**不是真实 API 连通性证明**。真实连接检查需要由你在有凭据的环境里运行。

## 六、代码库本篇新增内容

- `src/ontology_software_factory/llm_provider.py`：Provider 协议、OpenAI Responses 实现、Fake Provider。
- `scripts/check_llm_connection.py`：需要真实凭据的连通性检查。
- `tests/test_llm_provider.py`：离线测试，不访问网络。
- `docs/llm-provider.md`：配置、重试、日志和故障排查。
- `docs/adr/0010-llm-provider-adapter.md`：为什么将模型厂商调用单独封装。

### 配图建议 3：真实接入前后的差异

**图片生成提示词：**
> 生成一张简洁的左右对照技术信息图。左侧为“散落的模型调用”：各 Agent 直接连接厂商 API，重试、超时和日志规则不一致。右侧为“统一 Provider Adapter”：所有调用经过统一入口，配置、重试、结构化输出、Token 统计、密钥保护集中管理。浅色底，深蓝/青绿配色，信息密度适中，图中文字用简体中文。

## 结语：模型是推理引擎，不是系统架构本身

一个可持续演进的软件工厂，不应该把业务流程绑死在某个模型 SDK 上。Provider Adapter 让模型调用变成一个可替换、可观测、可测试的基础设施能力；但权限、状态、交付、审批和证据仍由我们的工程系统决定。

下一篇，我们让真实模型不再只是“回答问题”，而是成为有边界的 Agent：它拥有角色、Skills、上下文和受控工具，但不能凭一句自然语言绕过工作流政策。

---

**参考资料**

- [OpenAI API Quickstart](https://developers.openai.com/api/docs/quickstart)
- [OpenAI API Models](https://developers.openai.com/api/docs/models)
- [Responses API Python reference](https://developers.openai.com/api/reference/python)
- [Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs)
