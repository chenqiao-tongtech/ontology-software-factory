# Integrated Console UI 说明

## 目标用户

软件工厂平台工程师与值班操作者，需要在一个页面中检查 Workflow Run、Worker Task、Outbox 交付状态与证据回写是否一致。

## 主视图

- 顶部统计：Workflow Runs、Worker Tasks、待投递 Outbox、已确认 Outbox。
- 左侧运行列表：Run 状态、当前 Step、revision 与更新时间。
- 运行详情：Step 时间线、运行状态、错误、执行 taskId、证据链接。
- Worker Task 表：任务状态、尝试次数、幂等键与错误。
- Outbox 表：eventId、类型、状态、投递尝试、最近错误、已确认时间。
- 操作区：创建 Run、派发当前 Step、运行一次 Worker、Relay 一次、Drain Outbox、重放指定 Outbox event、暂停/恢复/重试/审批/取消。

## 交互原则

- 有副作用或状态变化的操作必须显示正在处理状态和 API 返回结果。
- 重放保留原始 eventId；操作者应清楚看到“这是重复投递测试，不是新业务事件”。
- “执行证据”区必须区分 demo URI 与真实制品。
- 出错时显示 API 传回的错误摘要，并保留事件账本以便定位。
- 页面仅提供本机演示用按钮；任何生产版本均需后端做身份验证、授权和状态校验，不得信任前端隐藏按钮。

## API 来源

UI 调用 `scripts/run_integrated_console.py` 中的本地 HTTP API。默认地址是 `127.0.0.1:8767`，静态页面不依赖外部 CDN。
