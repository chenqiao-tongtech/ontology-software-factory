# 本体发现质量评测协议

## 当前实现的指标

- **Term precision / recall / F1**：对候选中的标准化 term name 与 benchmark gold list 进行精确集合比较。
- **Relation precision / recall / F1**：对 `(subject, predicate, object)` 三元组进行精确比较。
- **Provenance coverage**：候选所有来源引用中，可从提供的 sourceId 与 quote 做本地复核的比例。
- **Deterministic validation**：Schema、端点、重复项、来源证据和 Critic blocker 等本地错误。

## 阈值

默认 Term F1 >= 0.75、Relation F1 >= 0.65、Provenance coverage >= 0.95，且本地验证无错误时，`passed=true`。这些阈值只是起始配置，不是普遍标准；正式门禁必须基于领域专家标注集、样本规模、错误代价和版本稳定性重新设定。

## 当前限制

1. 目前的 smoke benchmark 是合成示例，所有 fixture 引用来自固定文本，1.0 分数只说明流程测试成功，不说明模型对真实企业材料的抽取准确率。
2. 精确匹配无法识别同义词、上位词/下位词的所有合理情况；后续需要别名规范化、关系语义匹配和部分 credit。
3. 关系质量还需按层级关系与非分类关系分别评估，以防模型只擅长 `is-a` taxonomy 而遗漏业务关系。
4. 需要加入跨版本数据集、反例/冲突材料、提示注入与术语混淆测试，并由独立评估集控制过拟合。
5. 结果 `passed` 不等于 `promotionAllowed`。任何候选都必须经人类审批且审批记录绑定 exact digest。
