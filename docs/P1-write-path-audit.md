# P1 全仓库写操作路径审计（2026-10-31）

## 结论

本次审计确认：**真实 Agent Runtime 的工具调用路径已经接入 Tool Gateway；但不能据此宣称全仓库所有写路径都经过 Gateway。** 仓库同时存在本地控制台状态写入、演示 Worker 队列、只读数据源同步、LLM 候选生成，以及 HTTP/MCP 传输适配器。它们的安全语义不同，必须分别治理。

本轮修复了 Worker Console 与 AI Runtime Console 的默认网络暴露边界，并为两个控制台的 POST 写接口增加同源 Origin 检查。Portal 已有回环默认绑定与非回环显式开关、同源 POST 检查；它仍是无登录的单用户本地参考门户。

## 路径清单

| 入口/路径 | 写入或副作用 | 当前治理路径 | P1 判断 |
|---|---|---|---|
| OpenAI Agents Runtime 的 Function Tools | 调用已注册 Tool Handler | Agent Runtime → ToolGateway → SQLiteInvocationLedger → Harness → ToolRegistry → trusted handler | 已接入本地统一工具调用边界；审批按工具策略绑定 Run/Task/Tenant/Tool/摘要 |
| Harness / ToolRegistry | 预算、策略、审批、审计与工具分发 | Harness 校验后签发内部 dispatch capability；Registry 拒绝调用者伪造 approval 布尔值 | 核心路径已实现；需继续验证所有注册 Handler 的外部副作用均只从该入口触发 |
| Portal /api/sources、/sync、webhook | 保存数据源配置/同步状态；Webhook 触发 GitHub/GitLab 元数据重扫 | 本地 JSON 状态与事件；数据源扫描只读 | 不属于 Agent 动作工具；没有远端仓库写操作。Portal 无 IAM，禁止公网部署 |
| Portal /api/ontology/* | 本体候选、快照、提案、审批记录、活动快照指针 | 本地 JSON 状态；候选审批与 promote/rollback 有角色字符串分离和摘要/版本绑定 | 仅本地治理状态，不修改正式本体文件；actor 字符串不是身份认证，不能作为企业审批 |
| Portal /api/agents/* | 创建/推进 deterministic fixture Run 与审批记录 | 本地 JSON 状态 | 演示流程，不是生产 Agent 执行，不调用外部工具 |
| Portal /api/quality/run | 启动固定验证脚本、测试或已知扫描器 | 固定命令白名单、参数数组、超时 | 宿主机进程，不是隔离执行器；扫描器缺失不视为通过 |
| Portal /api/releases/* | 生成配置交付候选、记录演练审批、执行本地升级/回滚演练 | 固定 E2E 脚本与本地状态 | 不执行真实部署，不是客户环境发布 |
| Worker Console /api/tasks、/worker/run-once | 入队并执行任务 | SQLiteTaskStore；仅注册 demo.echo 与 demo.generate-evidence | 本地演示 Worker，不接业务写工具。现已默认只允许 loopback；非回环需显式 --unsafe-expose |
| AI Runtime Console /api/pipeline/run | 触发真实 LLM/Agent Pipeline、写运行制品 | OpenAIAgentsRuntime；Agent 工具走 Tool Gateway | 控制台本身无认证，现已默认只允许 loopback；POST 增加同源检查 |
| HTTP JSON Adapter | 对 allow-listed HTTPS origin 发起 GET/POST/PUT/PATCH/DELETE | 传入 Idempotency-Key；是否幂等取决于远端服务 | 传输适配器不是授权边界；业务写调用必须由 Gateway/Harness 前置授权后才可触发 |
| MCP stdio Adapter | 向管理员配置的 MCP Server 发起 tools/call | 固定命令、环境白名单、工具名 allow-list | 传输适配器不是授权边界；当前未证明所有 MCP 调用都由 Gateway 统一中介。不得将 MCP Server 直接暴露给 Agent |
| ConnectorRuntime / Source Connectors | 读取源系统资产元数据 | ConnectorCatalog + Principal/Tenant/SourceBinding + metadata-only audit | 只读数据源路径，不应获得动作连接器写权限 |
| Task Runtime / SQLiteTaskStore | 入队、领取、完成、取消任务并写证据 | 本地 SQLite、租约、幂等键、证据契约 | 当前 Worker demo 与 Agent 工具 Gateway 是两条路径；未来如允许任务执行外部动作，必须将执行器改为 Gateway-backed handler |

## 第二轮 P1 加固（2026-10-31）

### 1. Adapter 强制 Gateway 中介

- `ToolRegistry.invoke` 现在要求 Harness 内部派发 capability；普通调用者直接调用 Registry 会被拒绝。
- Handler 收到的 `ToolInvocationContext` 带有进程内 Gateway capability；HTTP 的 POST/PUT/PATCH/DELETE 和 MCP 的 `tools/call` 必须验证该上下文。
- MCP 原始 `request("tools/call", ...)` 也被拦截，不能绕开 `call_tool` 的校验。
- HTTP/MCP Adapter 进一步要求 toolId 在显式 allow-list 内；变更型调用必须带 Gateway 幂等键。
- 该 capability 是进程内可信代码边界，不是跨进程身份令牌；Python 同进程恶意代码、模块反射或直接访问数据库仍不在此安全模型内。

### 2. 动作连接器注册

新增 `policies/action-connectors.json` 与 `ActionConnectorRegistry`：
- 默认拒绝，空注册表不允许任何外部动作。
- 每个连接器必须显式绑定 adapterType、toolIds、methods。
- 不允许连接器降低底层工具的审批要求；非 GET 连接器不能关闭幂等要求。
- 数据源只读连接器与动作连接器分开管理。
- 当前注册表为空：尚未配置真实业务 HTTP/MCP 动作连接器。部署时需由管理员审查并登记具体工具、远端目标、网络出口、密钥引用和审批策略。

### 3. Approval reservation / commit / uncertain

- 新增 `ApprovalStore.reserve()`：在事务中校验审批绑定并将 approved 原子转换为 reserved。
- 派发成功后 `finalize_reservation(outcome="consumed")`。
- 派发异常后转换为 `uncertain`；该审批不能自动重放，必须人工/运维 reconciliation。
- Harness 高风险工具不再接受旧的任意 `approval_validator` 回调作为替代；必须注入持久化 ApprovalStore。
- 这仍不是远端事务：若进程在远端成功、但本地 commit 前崩溃，状态可能是 reserved；系统不能判断远端是否完成，必须查远端幂等记录或人工核对。

### 4. CLI / Worker / Portal / 后台入口边界

- Worker Console 只注册 `demo.echo` 与 `demo.generate-evidence`；不接受任意任务类型或 shell 命令。
- 通用 `TaskWorker` 是可注入 Handler 的执行框架，不应把业务动作 Handler 直接注册到通用 Worker；需要动作时由 Handler 调用 Tool Gateway，或将 Worker 改为 Gateway-backed dispatcher。
- Portal 的源配置、快照、提案、审批、质量和发布演练 API 写入本地控制面状态或执行固定本地校验脚本；它们不是外部客户环境部署入口。Portal actor 字段仍是自报字符串，不构成真实身份认证。
- CLI 校验脚本只应读取配置/资产或运行固定验证命令；禁止从模型输出、HTTP 请求或任务 payload 构造 shell 命令。
- AI Runtime Console 触发真实 LLM pipeline，但没有 IAM；继续保持 loopback 默认绑定。所有 Agent Function Tool 通过 Tool Gateway。
- 本轮没有发现并启用任何生产业务动作连接器；因此不能宣称生产 Portal/CLI/后台动作已全面纳入统一 Gateway。

### 5. P1 验收基线

新增 `docs/P1-acceptance-checklist.md`，把 Gateway bypass、HTTP/MCP 直连、审批状态恢复、工具 allow-list、幂等键、CLI/Worker 限制和 Evidence 契约列为自动化验收项。完整生产关闭仍需要 IAM、跨进程服务身份、外部副作用恢复、签名证据和多节点数据库。

## 本轮代码修复

- 新增 `src/ontology_software_factory/console_security.py`：
  - 只接受明确的 loopback 主机名/地址：`127.0.0.1`、`::1`、`localhost`。
  - 非回环绑定默认拒绝；不做 DNS 解析，避免把任意别名误判为安全回环。
  - 对带 Origin 的浏览器写请求要求 Origin 的 scheme/authority 与 Host 一致；无 Origin 的非浏览器客户端仍可访问，因此这不是身份认证或完整 CSRF 防护的替代品。
- Worker Console 新增 `--unsafe-expose` 显式开关；默认拒绝非回环绑定；POST 增加同源检查。
- AI Runtime Console 同样新增 `--unsafe-expose` 显式开关；默认拒绝非回环绑定；POST 增加同源检查。
- 新增 `tests/test_console_security.py`，覆盖 loopback allow-list、wildcard/外部地址拒绝和 Origin 检查。

## 仍未关闭的 P1 项

1. **Adapter 本地中介已加固，但生产全路径仍未证明。** ToolRegistry、HTTP 变更请求和 MCP tools/call 已要求 Harness/Gateway 内部 capability；仍需逐个审查所有 Handler 构造点和真实部署入口，确保没有旁路 HTTP 客户端、MCP 客户端或 subprocess 写操作。
2. **身份认证未接入。** ApprovalStore 与 Portal 当前的 requester/approver/executor 分离使用 actor 字符串；尚无 OIDC/SSO、MFA、组/角色同步或服务端身份断言。
3. **审批与外部副作用不是分布式原子事务。** 审批消费后、远端动作完成前若进程崩溃，需通过 reservation/commit 状态机与人工/自动 reconciliation 处理。
4. **外部幂等依赖远端。** 本地 ledger 可阻止重复派发并重放已缓存 JSON 结果，但无法单独保证远端 exactly-once。
5. **证据尚未形成可信制品链。** 当前契约校验字段与摘要关系；未从远端拉取制品、验证签名、存入 content-addressed store 或生成签名 attestation。
6. **生产部署仍未完成。** 多节点共享事务数据库、密钥代理、网络出口策略、执行沙箱、备份恢复和不可篡改审计尚未实现。

## 验收口径

- 所有业务外部写操作必须通过 Gateway → Harness → Policy/Approval → ToolRegistry → trusted adapter handler。
- Portal 的本地治理写操作可以由独立控制面 API 管理，但生产部署必须接入 IAM、服务端授权与审计；不能把本地 JSON 状态视为企业审批系统。
- 数据源连接器保持只读；动作连接器单独注册、单独授权。
- Worker demo handler 不得被替换成业务写 Handler，除非其执行路径也接入 Gateway。
- 只有在完整调用图审计、IAM 集成、外部副作用恢复策略和证据验证均有实现与测试后，才可将 P1 标记为生产级关闭。
