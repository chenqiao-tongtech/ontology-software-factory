# Article 20 增量补丁说明

此补丁以第 18 篇 Agent/Skills 契约与第 19 篇 Workflow State Machine / Console 为前置基线，只新增 Worker Runtime 相关路径。

## 本次新增路径

- `src/ontology_software_factory/task_runtime.py`
- `scripts/run_worker_console.py`
- `apps/worker-console/index.html`
- `contracts/schemas/worker-task.schema.json`
- `examples/worker-tasks/sample-task.json`
- `tests/test_task_runtime.py`
- `docs/worker-runtime-and-reliable-dispatch.md`
- `docs/adr/0008-worker-task-dispatch-and-idempotency.md`
- `docs/acceptance/worker-runtime-checklist.md`
- `data/worker-runtime/README.md`, `data/worker-runtime/.gitignore`
- `README_ARTICLE20.md`
- `article/通往AI之桥_软件工厂工程实现线20_公众号发布稿.md`

## 合并方法

1. 在当前分支解压本补丁。
2. 检查新增的 Python 模块与现有包风格；不覆盖 `src/ontology_software_factory/__init__.py`。
3. 保留既有 `README.md`、`pyproject.toml`、`Makefile` 与 Article 18/19 路径。
4. 把文章 Markdown 发布稿复制到内容仓库所需位置。
5. 运行：

```bash
python -m unittest discover -s tests -v
python scripts/run_worker_console.py --host 127.0.0.1 --port 8766
```

## 安全和正确性边界

- Demo Console 没有认证、RBAC、CSRF 或生产级权限治理；默认仅绑定 localhost。
- 只有 `demo.echo` 和 `demo.generate-evidence` 可由演示 UI 调用。
- `demo://` 证据不代表真实制品。
- Worker Task Store 不与 Article 19 Workflow Store 在一个事务中；生产集成需实现 workflow adapter + outbox/reconciliation。
- Handler 的 timeout 是合作式/返回后检测；任意阻塞代码需在子进程或容器中硬隔离。
- at-least-once + 幂等设计比声称 exactly-once 更诚实；所有外部副作用都必须使用业务级幂等和/或对账。
