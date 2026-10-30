# ADR 0017：采用可替换的 LLM 辅助本体发现流水线

- Status: Accepted for MVP / external integrations remain optional
- Date: 2026-10-29

## Context

本体工程从人工术语表开始，但业务资料可能分散在需求、API、数据库元数据、事件、运行手册和既有语义目录中。LLM 能从这些来源提出候选术语、关系、约束和能力问题，也容易生成无证据关系、过度泛化的概念或把授权规则误当作领域规则。直接让模型写生产本体会导致不可追溯的语义漂移。

## Decision

- 自建四阶段发现服务：Term → Relations → Constraints/Competency Questions → Independent Critic。
- 用 JSON Schema 严格结构化每一步输出，并保留 source manifest、source hashes、quote refs、模型/阶段/延迟/token trace。
- 确定性本地校验负责证据引用、重复术语、关系端点与 Schema；人工 gold benchmark 提供 precision/recall/F1 的门禁信号。
- 所有输出先成为不可覆盖的 `OntologyCandidate`；仅独立人类审批且记录绑定 candidate digest 后，才可生成版本化变更提案。
- NVIDIA Auto Ontology 作为可选只读语义目录来源，不作为必需运行时或生产本体的唯一权威；Cognee 作为可选图式抽取/grounding 适配器，仅使用隔离 review dataset。
- LLMs4OL/OLLM 作为研究和评测方法来源，不作为核心依赖。
- 提取模型、关系模型、约束模型、Critic 可独立配置，Usage Ledger 记录阶段成本；外部模型不可用时流程 fail closed。

## Alternatives considered

1. 人工手工维护：最可控，但大规模发现/变更影响分析成本较高。
2. 只用 NVIDIA Auto Ontology：擅长企业元数据和语义上下文，但本项目需要覆盖软件生产本体、Agent、Workflow、Evidence、Quality Gate 与 release lifecycle；不可假设它已直接覆盖全部领域语义。
3. 只用 Cognee：适合自定义图模型和知识抽取/grounding，但不能替代本项目的领域本体版本、政策边界与发布审批。
4. 让一个 Agent 一次性生成完整本体：调用更少，但难以分离术语、关系、约束与反例审查，且证据覆盖较难审计。

## Consequences

Benefits: repeatable candidate generation, explicit evidence, pluggable model/provider/semantic catalogue, measurable quality, human-governed promotion.

Costs: multiple model calls and higher latency; requires curated benchmark, careful source redaction, and schema/ontology migration tests. Offline fixture tests are not evidence of live model quality or external integration success.
