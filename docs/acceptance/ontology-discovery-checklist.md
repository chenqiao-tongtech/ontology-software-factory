# 本体自动发现验收清单

- [ ] 输入源授权、租户范围、保留期和模型服务数据处理条款已确认。
- [ ] 来源在模型调用前经过敏感信息检查/脱敏，且 source manifest 固化。
- [ ] Terms、relations、constraints/CQs、independent Critic 四阶段均记录模型与 usage trace。
- [ ] 所有核心术语与关系的 source quote 能在原始来源核验。
- [ ] Schema、关系端点、重复术语、跨批次冲突与业务约束类型检查通过。
- [ ] 独立 Benchmark 已由领域专家标注，阈值经风险评估，不用合成 smoke 数据宣称质量。
- [ ] Critic blocker、无证据候选或未解决冲突会阻断审批。
- [ ] 人类审批包含 reviewer ID、approval reference 和 exact candidate digest。
- [ ] 版本化变更提案包含 ontology/schema diff、迁移兼容性分析和回归测试计划。
- [ ] 测试证明 LLM 不能直接写生产本体、策略、IAM 或 Workflow 权威状态。
- [ ] NVIDIA Auto Ontology / Cognee 外部集成均经过安全、数据边界和许可审查；未连接时标为 partial。
