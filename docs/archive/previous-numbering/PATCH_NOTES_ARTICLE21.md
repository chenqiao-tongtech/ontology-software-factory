# Article 21 增量补丁说明

本补丁以 Article 18/19/20 已合并的参考工程为基线。它只更新 Worker/Workflow 集成所需的模块，并新增控制台、事件契约、测试和文档。请勿用补丁覆盖现有 `pyproject.toml`、根 `README.md`、`Makefile` 或 `src/ontology_software_factory/__init__.py`。

## 关键变更

- 修改 `src/ontology_software_factory/task_runtime.py`：在任务终态事务内写 Outbox，并提供租约领取、确认、释放和重放接口。
- 修改 `src/ontology_software_factory/workflow_store.py`：增加 Workflow Inbox 去重，以及 Run + Workflow Event + Inbox 的原子消费事务。
- 修改 `src/ontology_software_factory/workflow_engine.py`：把 Worker 事件投影为节点成功/失败，验证证据契约、revision、当前节点与 workflow attempt，审计并忽略迟到结果。
- 新增 `src/ontology_software_factory/integration.py`：派发桥、演示 Handler、Outbox Relay。
- 新增 `scripts/run_integrated_console.py` 与 `apps/integrated-console/index.html`。
- 新增 integration event schema、9 个闭环集成测试与文档。

## 合并与验证

解压到现有仓库根目录，先查看文件变更，再运行：

```bash
python -m unittest discover -s tests -v
python scripts/run_integrated_console.py --host 127.0.0.1 --port 8767
```

测试通过后访问 `http://127.0.0.1:8767`。测试使用临时 SQLite 数据库；不要提交 `data/integrated-console/*.sqlite3` 或其 sidecar 文件。

## 重要边界

- 两端事务分别提交：生产者 Outbox 和消费者 Inbox 之间不做跨数据库分布式事务。
- Relay 是至少一次投递，Inbox 通过 `eventId` 去重；不宣称外部副作用 exactly-once。
- `demo://` 是占位证据。没有真实 LLM/CI/CD/部署适配器。
- 控制台没有生产身份认证、RBAC/CSRF 或容器沙箱；仅应绑定 localhost。
- 生产接入需要事件 schema 版本策略、死信告警、Outbox/Inbox 保留策略、业务幂等和对账。
