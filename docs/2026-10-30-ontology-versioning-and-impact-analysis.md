# 本体版本快照、结构差异与影响分析

本轮在本地 Factory Portal 中增加**显式创建、不可变保存的本体快照**，并提供两个快照之间的结构化差异与概念影响范围分析。

## 能力范围

- 快照以当前 `ontology/software-factory-ontology.json` 完整内容为基准。
- 使用规范化 JSON（键排序、紧凑序列化）计算 SHA-256；同一内容的摘要不受 JSON 对象键顺序影响。
- 快照包含本体 ID、业务版本、契约 Schema 版本、摘要、时间、操作者、原因和完整本体内容。
- 相同摘要不会重复存储；本地状态最多保留最近 100 个不同快照。
- 差异覆盖核心类、扩展类、核心关系、扩展关系、受控词汇和 MVP 不变量。
- 关系变更会列出关系两端涉及的概念类；新增、删除或修改的类也会进入影响范围。
- 任何结构差异都会标记 `reviewRequired=true`，供人工评审。

## API

创建快照（必须提供操作者和原因）：

```bash
curl -X POST http://127.0.0.1:8768/api/ontology/versions/snapshot \
  -H 'Content-Type: application/json' \
  -d '{"actor":"ontology-maintainer","reason":"发布评审前保存基线"}'
```

列出快照元数据（不返回完整本体正文）：

```bash
curl http://127.0.0.1:8768/api/ontology/versions
```

比较两个快照：

```bash
curl 'http://127.0.0.1:8768/api/ontology/diff?from=ont-<旧摘要前缀>&to=ont-<新摘要前缀>'
```

快照 ID 由内容摘要生成；相同内容会返回已存在的快照，而不是生成重复记录。

## 影响分析的边界

当前可以可靠推导的是**本体结构内部影响**：哪些类、关系端点、受控词汇和约束发生变化。Portal 尚未建立 Agent、Skill、Workflow、工具契约等消费者对本体 ID 的稳定引用索引，因此 API 的 `potentialConsumers` 保持空数组，并明确说明尚未建立索引。不能把“概念类受影响”误报为“某个 Agent 已被证实受影响”。

## 治理与安全边界

- 快照只记录版本，不修改正式本体文件。
- 创建快照需要显式调用 API，并提供操作者与原因；不会在 GET 请求时偷偷生成版本。
- 快照不等同于 Git commit、签名制品或防篡改审计存储；当前数据保存在本地 Portal JSON 状态文件中。
- 本轮不提供一键回滚。历史快照可用于比较和人工恢复参考；正式变更仍应通过代码评审、校验和 CI 提交。
- 当前 Portal 默认仅绑定 loopback，尚非多用户生产治理服务。

## 验证

`tests/test_ontology_versioning.py` 覆盖摘要稳定性、快照输入校验、快照内容隔离、类/关系/词汇/不变量差异，以及无结构变化场景。完整验收以本 PR 的 GitHub Actions 结果为准。
