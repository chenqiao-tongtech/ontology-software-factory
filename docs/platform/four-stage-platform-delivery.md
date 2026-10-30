# 四阶段统一软件工厂门户：实现说明与验收边界

## 目标

在既有本体发现、Agent/Workflow/Worker、质量门禁和配置交付参考实现之上，新增一个统一的本地 Portal，将资产来源、本体语义、多智能体执行、质量/安全结果、交付物与事件证据组织在同一导航和同一组稳定标识下。

运行入口：`make portal`，默认地址 `http://127.0.0.1:8770`。

## 阶段一：平台基础与共享契约

**已实现**

- 统一深色高对比 UI、全局导航和健康状态。
- 统一门户 REST API；使用 `Source ID`、`Candidate ID`、`Run ID`、`Release ID` 和 `Event ID` 关联对象。
- JSON 持久化本地门户状态及事件账本；现有 SQLite Workflow/Task Runtime 保持为专门执行层。
- 变更 API 执行同源校验；默认绑定回环地址，显式阻止无意的非回环绑定。
- 在界面与 README 中区分真实本地操作、fixture 演示与外部未连接能力。

**仍需企业生产化**：统一 OIDC/SSO、RBAC/ABAC、多租户边界、服务端数据库、不可篡改审计存储、速率限制、CSRF/访问控制的完整安全审查和 API 版本兼容策略。

## 阶段二：企业资产接入与本体工作台

**已实现**

- 数据源注册：本地仓库目录、文档目录、SQLite 文件，以及 GitHub.com / GitLab.com HTTPS 仓库元数据 API；UI 可添加和同步来源。
- 目录/文档以受限扩展名做只读元数据扫描，并过滤隐藏目录、`.git`、依赖目录和超大文件。
- Git 可用时查询本地分支、最近提交、工作区变更数量；GitHub/GitLab.com 连接器可只读获取仓库概况和文件树。私有仓库需要在启动环境设置 `GITHUB_TOKEN` / `GITLAB_TOKEN`，Token 不持久化；不支持自托管 GitLab、OAuth 或 Webhook。
- SQLite 以只读 URI 连接，只读取表、视图和列元数据。
- 从正式本体文件绘制可交互 SVG 图谱；支持筛选、点选节点、展示定义和邻接关系。
- 基于 Markdown 标题、Python class/function、JSON 键、SQL 表声明做确定性术语候选抽取；保留源路径。
- 候选支持审查、批准为变更提案或驳回；审批不自动改写正式本体。

**限制**：规则抽取不是 LLM 本体学习；尚未实现远端文档正文同步、OAuth/SSO、Webhook 增量同步、全文索引、血缘语义推理、大图布局引擎和双版本图谱 Diff。

## 阶段三：Agent 指挥台与质量/安全实验室

**已实现**

- Agent 运行卡片和阶段拓扑；离线示例可以逐步推进 5 个确定性阶段，输出摘要和证据 URI，并经过人工审批。
- 事件账本记录来源同步、本体候选、Agent 运行、质量检查和发布操作。
- 质量实验室可运行既有架构/契约/Workflow/本体发现校验脚本与完整 unittest 套件。
- 读取 Semgrep/Gitleaks/Trivy 是否安装；用户明确勾选后才调用已安装扫描器，保存可追溯报告路径和有限控制台摘要。
- “未安装”“未执行”“超时”“完成但有发现/错误”和“通过”分开表示。

**限制**：Agent Command Center 的新增演示处理器不调用 LLM；真实模型调用仍使用已有 Agent Workflow Console 和 Agent Runtime 配置。要将真实运行接入统一拓扑，需要订阅既有 Workflow/Task/Outbox 的持久化状态，而不是把离线演示状态当作生产指标。测试床目前执行本地验证/测试，并不是容器/微虚机隔离的任意代码执行平台。

## 阶段四：交付与发布中心

**已实现**

- 从 Portal 触发已有端到端配置交付流水线。
- 显示 Release Record、manifest 文件清单、文件 SHA-256、包体积和配置范围 SBOM。
- 独立审批动作可记录为“批准用于本地演练”；执行人与审批人必须分离。
- 本地升级成功/模拟失败回退演练调用现有 `rehearse_upgrade`，展示 before/after 状态和 `realDeploymentPerformed=false`。

**限制**：制品仅是 Kafka 风格配置包，没有 Kafka 二进制；SBOM 仅描述配置包。尚未连接 OCI/通用制品仓库、Git 发布、CI/CD、Kubernetes/Argo CD、生产审批系统或真实集群。不得称为真实生产发布。

## 本地运行

```bash
python -m pip install -e .
make validate
make test
make portal
```

仅本机访问：`http://127.0.0.1:8770`。

首次运行会在 `.local-portal/` 生成本地 JSON 状态和合成 SQLite 数据库。该目录已被 `.gitignore` 忽略。数据源配置在 `config/integrations/sources.json`，可以复制 `sources.example.json` 进行备份或审查。门户不上传数据，但配置绝对路径前仍需确认该本地进程被授权读取该目录。

## 验收要点

1. `/api/health` 返回 200；门户首页能加载五个主要功能域。
2. 仓库/文档/SQLite 源连接可以读取元数据，SQLite 连接不执行写操作。
3. 图谱节点和关系来自仓库正式本体 JSON；节点点击显示真实定义。
4. 候选项包含来源路径；批准后正式本体文件哈希不变。
5. 离线 Agent 每次阶段推进写入事件，终态必须经过人工批准/驳回。
6. 质量运行记录真实脚本退出码；未安装扫描器不得显示 PASS。
7. Release Record 只有质量门禁允许时才能生成候选；演练记录明确声明未部署。
8. 默认非回环绑定被拒绝；不得将无认证门户放在公网或共享网络中。
