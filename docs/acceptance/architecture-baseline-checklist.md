# 架构与规划基线验收清单（第 15 篇）

本清单验证设计产物是否内部一致，不代表软件工厂端到端功能已完成。

| ID | 验收标准 | 证据 | 状态 |
|---|---|---|---|
| ARCH-01 | 目标、非目标和 MVP 边界已记录 | `docs/project-charter.md`, `docs/scope-and-nongoals.md` | PASS |
| ARCH-02 | 总体架构定义控制面、执行面和横切治理 | `docs/architecture.md` | PASS |
| ARCH-03 | 子系统/模块/组件职责、状态、依赖有机器可读定义 | `config/architecture-baseline.json`, `docs/subsystem-decomposition.md` | PASS |
| ARCH-04 | 原则与硬约束可追溯 | `docs/architecture-principles-and-constraints.md` | PASS |
| ARCH-05 | 本体的能力问题、核心词汇、映射和演进已规划 | `docs/ontology-design-and-evolution.md` | PASS |
| ARCH-06 | 第 15–24 篇阶段门和退出条件已明确 | `docs/development-roadmap.md` | PASS |
| ARCH-07 | 子系统依赖无缺失引用和循环 | `python scripts/validate_architecture_baseline.py` | PASS |
| ARCH-08 | 当前实现状态和生产缺口没有混写 | `config/architecture-baseline.json`, `docs/implementation-status-v2.0.md` | PASS |

## 不等价说明

ARCH 通过只表示“总体规划和设计基线已形成且内部一致”；MVP-01 至 MVP-08 的端到端状态仍需各自的运行证据。规划质量不能取代真实构建、测试、扫描、部署和生产环境验收。

- [ ] 多智能体协作拓扑、AgentHandoff 契约、独立验证并行 Join 和修复循环上限均通过机器校验。
- [ ] 确定性 Workflow 控制任务派发；Agent 不自授权、不直接更改状态、不审批自己的高风险结果。
