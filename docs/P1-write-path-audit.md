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

## 本轮代码修复

- 新增 `src/ontology_software_factory/console_security.py`：
  - 只接受明确的 loopback 主机名/地址：`127.0.0.1`、`::1`、`localhost`。
  - 非回环绑定默认拒绝；不做 DNS 解析，避免把任意别名误判为安全回环。
  - 对带 Origin 的浏览器写请求要求 Origin 的 scheme/authority 与 Host 一致；无 Origin 的非浏览器客户端仍可访问，因此这不是身份认证或完整 CSRF 防护的替代品。
- Worker Console 新增 `--unsafe-expose` 显式开关；默认拒绝非回环绑定；POST 增加同源检查。
- AI Runtime Console 同样新增 `--unsafe-expose` 显式开关；默认拒绝非回环绑定；POST 增加同源检查。
- 新增 `tests/test_console_security.py`，覆盖 loopback allow-list、wildcard/外部地址拒绝和 Origin 检查。

## 仍未关闭的 P1 项

1. **MCP/HTTP 全路径中介尚未证明。** 需要对所有 Adapter 构造点、Tool Handler 注册点、Portal/Worker/脚本入口做静态与动态调用图审查；任何可产生外部写副作用的 handler 都必须要求 Gateway 颁发的内部 dispatch capability，不能仅依赖调用方自报 actor 或 approval 字段。
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
