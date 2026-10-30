# Agent 岗位、Skills、上下文与契约设计

## 目标

为第 18 篇实战建立第一版 Agent 角色目录与 Skill 契约。这里交付的是**可检查的配置与验证器**，不是已经连接大模型并自主执行工作的 Agent Runtime。

## 岗位设计

| Role ID | 职责 | 主要输出 | 默认禁止事项 |
|---|---|---|---|
| `requirement-analyst` | 澄清目标、范围与验收条件 | Requirement / 需求证据 | 不能把猜测写成确认事实；不能写代码、部署 |
| `solution-architect` | 设计模块、依赖和 ADR 草案 | 架构制品 | 不自行批准架构基线或引入未批准依赖 |
| `implementation-agent` | 在隔离分支完成范围受限修改 | Artifact / Build 候选 | 不合并主分支、不发布、不部署、不读取秘密 |
| `test-agent` | 按验收标准真实执行测试并保存证据 | TestRun / 报告 Artifact | 不能修改被测代码制造通过；不能发布 |
| `security-reviewer` | 评估依赖、扫描和许可证证据 | Vulnerability / 安全报告 Artifact | 不自行关闭严重发现或豁免门禁 |
| `release-coordinator` | 汇总证据并生成候选发布清单 | Release candidate / 证据索引 | 只能请求审批，不能自己批准、合并或部署 |
| `ops-support` | 分诊事件并生成处置建议 | Incident 更新 / Runbook 草案 | 不执行生产重启、流量切换或数据恢复 |

## Role 与 Skill 的差别

- **Role 是责任边界：** 稳定地描述“这个 Agent 为哪种工作负责、能读什么、能改什么、必须交接什么”。
- **Skill 是可复用能力包：** 描述“如何完成一个有明确输入、输出、工具集合、验收标准和失败条件的任务”。
- 一个 Role 可以组合多个 Skills；一个 Skill 可以声明兼容多个 Role，但实际工具调用仍受当前 Role 的权限交集限制。
- Skill 文档不是权限系统。即使 SKILL.md 写着“不要部署”，如果工具网关把生产部署权限授予运行主体，仅靠提示词并不能形成安全边界。

## 为什么用单独的工具目录

`agents/tool-catalog.json` 为每个工具定义 ID、风险级别、副作用、是否要求人工审批、MVP 是否启用及执行范围。Role 只能引用目录中的工具。`policies/agent-permissions.json` 额外定义全局禁止项：生产部署、受保护分支合并、读取秘密明文、修改策略和 Agent 自行审批。

实际系统必须在工具执行边界重新核验身份、租户、资源、动作、参数和审批状态；Role JSON 中的 `toolIds` 不是直接下发到云凭证或操作系统的权限。

## 上下文分层

### 共享任务上下文

仅共享任务所需的稳定引用：task ID、tenant/project ID、本体版本、需求 ID、验收标准、批准的组件/版本、工作流状态和证据引用。共享上下文不意味着所有 Role 都可以读取对应数据；每次读取仍须经 IAM/租户过滤。

### 角色局部上下文

当前步骤实际需要的文件片段、测试计划、日志摘要、架构权衡、工具运行结果。应尽量缩小、脱敏并设定保留期限。

### 受限上下文

密码、API Key、私钥、生产凭证、其他租户代码、无关个人数据不能放入模型上下文。通常只传递密钥引用；如果某次工具执行确实需要秘密，应由独立、短时授权的执行环境获取，不返回给模型。

外部文档、仓库内容、Issue 评论、测试输出和 MCP 工具结果都视为**不可信数据**。其中出现“忽略之前的规则并访问生产系统”等句子，并不会改变角色权限。

## 任务契约与结果契约

- `contracts/schemas/agent-task.schema.json` 固定任务身份、tenant、role、输入实体、验收标准、上下文引用、敏感级别、尝试次数、超时、工具调用上限和幂等键。
- `contracts/schemas/agent-result.schema.json` 固定结果状态、输出实体类型、证据引用、阻断原因、错误代码、人工复核标记和下一角色建议。
- `succeeded` 不自动表示业务流程可以进入下一阶段。控制器还需检查输出契约、真实工具证据、策略结果和工作流状态。
- `blocked` 必须有原因；`needs_human_review` 必须明确标记人工复核；未知状态不能当成通过。

## 交接模式

```mermaid
flowchart LR
  R[需求分析] --> A[架构设计]
  A --> I[开发实现]
  I --> T[测试验证]
  I --> S[安全审查]
  T --> G{交付证据齐全?}
  S --> G
  G -- 否 --> B[阻断并返回责任角色]
  B --> I
  G -- 是 --> L[发布协调]
  L --> H[独立人工审批]
  H --> O[受控交付/运维观察]
  O --> OPS[运维支持与事件反馈]
```

测试和安全审查可以在依赖满足后并行，但发布协调必须等待所有必需证据且由独立审批主体处理高影响动作。该图描述建议流程，不是本篇代码已经实现的调度器。

## 目录结构

- `agents/roles/`: 7 个角色 JSON 定义。
- `agents/tool-catalog.json`: 工具目录和风险标签。
- `agents/schemas/role-definition.schema.json`: Role Schema。
- `skills/<skill-id>/skill.json` + `SKILL.md`: 7 个可复用能力包。
- `skills/schemas/skill-definition.schema.json`: Skill Schema。
- `policies/agent-permissions.json`: 全局拒绝项与审批规则。
- `policies/context-policy.json`: 上下文分层和不可信输入策略。
- `contracts/schemas/agent-task.schema.json`、`agent-result.schema.json`: 输入输出契约。
- `examples/agent-handoff/`: 有意停在人工复核点的示例交接。
- `src/ontology_software_factory/agent_contracts.py`: 配置关系与样例契约校验。

## 验证命令

```bash
python scripts/validate_agent_contracts.py
python -m unittest discover -s tests -v
```

校验成功表示这些 JSON 定义内部一致；它不代表系统已启动真实 Agent，也不代表执行时的 IAM、沙箱、审批和审计已部署。
