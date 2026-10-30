# 第 20 篇验收清单

- [x] 同幂等键 + 同 payload 返回原任务，不重复插入
- [x] 同幂等键 + 不同 payload/task type 明确冲突
- [x] Worker 原子领取任务并递增尝试次数
- [x] 只有有效租约持有者可以 heartbeat、complete、fail
- [x] 租约过期后可重新排队；耗尽次数进入 dead letter
- [x] 仅错误白名单进入退避重试
- [x] 超时检测与协作式 deadline
- [x] 缺失必需证据、SHA-256 格式错误时拒绝完成
- [x] 任务结果与事件持久化
- [x] 可将第 19 篇运行中节点转换为任务信封
- [x] 本地 Worker Console 仅注册白名单演示 Handler
- [ ] 真实模型/CI/CD/容器执行器接入（后续工作）
- [ ] 工作流状态回写的 outbox/reconciliation（后续工作）
- [ ] 身份认证、RBAC、密钥管理、硬超时与分布式队列（生产化工作）
