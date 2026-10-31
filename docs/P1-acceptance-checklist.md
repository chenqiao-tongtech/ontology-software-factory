# P1 统一运行时与治理控制面验收清单

> 适用：本地参考实现和 CI 回归；不替代企业部署环境验收。

## A. 唯一工具派发入口

- [x] ToolRegistry 拒绝没有 Harness 内部派发 capability 的直接调用。
- [x] HTTP JSON Adapter 对 POST/PUT/PATCH/DELETE 拒绝缺失 Gateway context 的请求。
- [x] HTTP 变更请求要求 context.tool_id 在该 Adapter 的 allow-list 内。
- [x] HTTP 变更请求要求 Gateway 幂等键，并且显式传入的幂等键不得与 context 不一致。
- [x] MCP `tools/call` 要求 Gateway context；原始 JSON-RPC request 不允许绕过。
- [x] MCP 调用绑定 allow-listed toolId、MCP tool name 和 Gateway idempotency key。
- [ ] 真实部署中的所有 HTTP/MCP handler、脚本和后台任务完成调用图审计；不存在旁路客户端或 shell 副作用。

## B. 动作连接器注册与授权

- [x] 新增 default-deny ActionConnectorRegistry。
- [x] Connector 必须显式声明 adapterType、toolIds、methods。
- [x] Connector 不能降低 Tool Registry 的 approvalRequired 要求。
- [x] 非 GET connector 不能关闭 idempotencyRequired。
- [x] 未登记 connector/tool/method 默认拒绝。
- [ ] 为生产 HTTP/MCP 动作配置远端 origin/command、网络出口、secret reference、租户资源范围和服务端审计。
- [ ] 将工具 riskClass、审批等级和资源策略做成策略版本锁，并完成角色/租户/项目授权测试。

## C. 审批与异常恢复

- [x] Approval 绑定 Run、Task、Tenant、Tool 和规范化 payload digest。
- [x] requester、approver、executor 分离。
- [x] reserve 原子转换 approved → reserved。
- [x] 成功派发后 reserved → consumed。
- [x] 派发异常后 reserved → uncertain；禁止自动复用。
- [x] 高风险工具必须注入持久化 ApprovalStore；不再接受旧回调作为审批替代。
- [ ] 进程崩溃后的 reserved 记录提供管理界面、远端查询/核验和人工 reconciliation 工作流。
- [ ] 远端系统确认幂等键语义；不能只依赖本地 ledger 宣称 exactly-once。

## D. CLI、Portal、Worker 和后台任务

- [x] Worker Console 仅允许 demo.echo / demo.generate-evidence。
- [x] Worker Console / AI Runtime Console 默认 loopback，非回环需显式 unsafe 开关。
- [x] Portal 同源写请求检查与本地控制台边界已有审计记录。
- [x] Task Runtime 取消后通过租约 fencing 拒绝迟到完成。
- [ ] 全部 CLI、Portal subprocess、Worker Handler 和后台任务的写副作用完成静态/动态清点。
- [ ] 所有新增外部写 Handler 必须经过 Gateway；代码审查与 CI 禁止绕过。
- [ ] Portal/CLI 生产入口接入服务端 IAM，不接受请求体中的 actor 字符串作为身份凭据。

## E. Evidence 与审计

- [x] Evidence Contract 绑定 Run、Task、Input SHA-256、Tool Version、Exit Code、Report SHA-256。
- [x] Task 完成时执行契约校验。
- [ ] 远端 Evidence 拉取、内容摘要重算、签名/attestation 验证和 content-addressed 存储。
- [ ] Audit event 增加可信身份声明、不可篡改存储、保留策略和跨节点关联 ID。

## F. 生产级关闭条件

P1 只有在以下全部满足后才可标记为生产级关闭：

1. 所有 Agent/Workflow/Portal/CLI/Worker/后台任务写操作的调用图已清点，所有外部动作经过唯一 Gateway。
2. OIDC/SSO/MFA、服务身份、角色/租户/项目资源授权和独立审批人身份在真实环境通过验收。
3. 外部系统幂等语义、超时未知状态、reservation reconciliation 和补偿流程经过故障注入测试。
4. Evidence 的制品内容、签名、来源和工具版本可独立验证。
5. 多节点共享事务存储、密钥管理、网络出口、隔离执行、审计保留、备份恢复均经过环境级验收。

当前 CI 单元测试只证明本地参考实现的合同，不代表以上生产级条件已经满足。
