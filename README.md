# Bid Agent

Bid Agent 是面向技术投标方案生成的受控 AI 工作台。用户只需上传 PDF/DOCX
招标文件，系统在后台创建工作区，完成有效性检查、解析、技术要求与评分点提取、
推荐目录、按章节生成、人工编辑、合规校核和整本 Word 导出。

产品不要求用户理解“项目”或逐条确认大量候选条款。商务、资格、密封和评审纪律
仍被保存，但默认作为合规提醒，不与技术写作要求同级展示。

## 核心架构

系统不是 Prompt Driven，而是三个相互独立的底座：

- Rule Engine：加载、校验、版本化和激活提取规则、写作规则、校核规则。
- Knowledge Engine：读取机构私有企业知识，在写作前一次性完成 Knowledge
  Matching，并保存匹配依据。
- Controlled Workflow：按有限阶段调用模块并保存规则快照、知识快照和运行轨迹；
  不允许 Agent 自由对话或无限循环。

固定流程：

```text
Document Upload
  → Document Validator
  → Load Extraction Rules
  → Parser
  → Requirement Extractor
  → Requirement Reviewer
  → Load Enterprise Knowledge
  → Knowledge Matching
  → Load Proposal Writing Rules
  → Proposal Planner
  → Chapter Writer
  → Compliance Checker
  → Export
```

每个模块职责单一。模型只负责边界明确的抽取或写作；阶段转换、版本选择、知识匹配、
校核和重试边界由应用控制。

## 规则配置

Git 中的默认规则：

- `config/rules/extraction.default.json`
- `config/rules/writing.default.json`
- `config/rules/compliance.default.json`

默认文件本身带 `key`、`rule_type` 和 `version`。数据库表 `rule_definitions` 支持
人工创建新版本、草稿/激活/退役状态以及 `manual`、`system`、`ai_generated`
来源，为后续专家访谈生成规则预留了能力。一次运行只使用一个激活版本；若数据库
没有激活版本，使用 Git 中的系统默认版本。

规则接口：

```text
GET  /api/v1/configuration/rules/active/{rule_type}
GET  /api/v1/configuration/rules
POST /api/v1/configuration/rules
POST /api/v1/configuration/rules/{definition_id}/activate
```

激活新规则不会改写历史运行。`workflow_runs.rule_snapshot` 和
`section_versions.rule_snapshot` 保存当时使用的版本与校验和。

## 企业知识与隐私

企业知识分类包括企业简介、资质、产品能力、技术能力、案例、标准模板、专家经验、
历史标书和常见章节。接口：

```text
GET  /api/v1/configuration/knowledge
POST /api/v1/configuration/knowledge
POST /api/v1/configuration/knowledge/documents
```

历史投标 PDF/DOCX 可通过 `knowledge/documents` 导入。系统只返回摘要，不通过
列表接口暴露知识正文；导入内容固定为机构私有、禁止公共训练，并默认标记为
`verified_enterprise_fact=false`，只能参考结构和响应方法，不能直接当作本企业
案例、资质或能力。

Chapter Writer 调用模型前，Knowledge Engine 会先读取全部可用的机构私有知识，
再按章节和 Requirement 完成匹配；写作阶段不会边写边自由搜索。匹配结果保存到
`knowledge_matches`，生成版本保存知识快照。没有匹配知识时，涉及企业事实的内容
必须使用 `【待补充：需要的企业事实】`，禁止虚构资质、人员、案例或能力。

通过有效性、解析质量、重复性和权限检查的历史招标文件，以
`organization_private` 范围进入私有知识库，供后续 RAG 检索。它不是“模型训练”，
不会未经授权进入任何公共训练集。

当前 MVP 的租户边界是单机构部署边界；多租户上线前必须增加真实身份认证、
organization_id 行级隔离和权限审计，不能仅依赖前端隐藏。

## 产品 API

```text
POST /api/v1/workspaces
GET  /api/v1/workspaces/{workspace_id}
GET  /api/v1/workspaces/{workspace_id}/requirements?view=proposal
GET  /api/v1/workspaces/{workspace_id}/requirements?view=compliance
PUT  /api/v1/workspaces/{workspace_id}/outline
POST /api/v1/workspaces/{workspace_id}/sections/{section_id}/generate
PUT  /api/v1/workspaces/{workspace_id}/sections/{section_id}/content
POST /api/v1/workspaces/{workspace_id}/sections/{section_id}/approve
POST /api/v1/workspaces/{workspace_id}/exports
GET  /api/v1/workspaces/{workspace_id}/exports/{export_id}/download
```

内部仍保留旧 `/projects` 接口用于兼容，但新前端不暴露项目概念。

上传接口先完成文件校验和解析，立即返回内部 workspace 及 `extracting` 状态；
Requirement 提取、知识匹配和推荐目录规划在受控后台任务中继续执行。前端轮询
`GET /workspaces/{workspace_id}`，状态变为 `outline_ready` 后进入技术要点页面。
这样真实大文件不会因模型处理耗时而占用一个长连接。当前 MVP 使用进程内后台
任务；生产环境需要进一步接入持久化任务队列，以支持进程重启后的自动恢复。

## 数据迁移

应用启动时运行 `python -m app.database.migrate`。关键迁移：

- `009_proposal_workspaces.sql`：Requirement 方案相关性、章节映射、文件有效性和
  私有知识资格、推荐目录顺序。
- `010_rule_knowledge_engine.sql`：规则版本、企业知识、工作流轨迹、知识匹配、
  生成快照和整本方案导出。

迁移文件应用后禁止修改，否则校验和保护会拒绝启动；后续变更应新增迁移。

## 本地运行

不要把真实密码或模型密钥提交到 Git。复制 `.env.example` 为 `.env`，在本机
私密文件中人工填写。

```bash
docker compose up --build -d
docker compose ps
curl http://127.0.0.1/health
```

访问 `http://127.0.0.1/`。前端通过同源 `/api/v1` 访问后端。

静态和单元检查：

```bash
.venv/bin/python -m pytest
cd frontend
npm test
npm run build
```

需要真实 PostgreSQL、Redis、模型和文件样本的集成验收在 Docker/ECS 中执行。

### 隐私安全的真实样本验收

将真实 PDF/DOCX 放入被 Git 忽略的 `acceptance_samples/`，然后运行：

```bash
python scripts/acceptance_mvp.py \
  acceptance_samples/真实招标文件.docx \
  --base-url http://127.0.0.1 \
  --timeout 900 \
  --output acceptance_reports/real-sample.json
```

验收脚本会实际执行上传、解析、Requirement 提取、目录规划和逐章模型生成。
报告只记录状态、数量、ID、字符数和校核严重级别，不记录招标原文、生成正文、
企业知识、文件名或模型密钥。章节仍必须经过人工编辑和确认后才能整本导出。

## ECS 部署

服务器目录为 `/opt/bid-agent`。通过 GitHub 同步代码后：

```bash
cd /opt/bid-agent
git pull --ff-only
docker compose up --build -d
docker compose ps
docker compose logs --tail=200 backend
```

回滚代码时切回上一个已验证提交并重新构建。数据库迁移采用前向迁移；涉及数据结构
回滚时必须先备份 PostgreSQL，并提供单独的补偿迁移，不能直接删除生产数据。

## 完成定义

“代码已写”不等于完成。一次可交付验收至少包括：

- 真实 PDF/DOCX 上传和有效性拒绝测试；
- 原文页码/段落可追溯的 Requirement；
- 技术写作要求与合规提醒分流；
- 规则版本及运行快照可查询；
- 写作前企业知识匹配结果可查询；
- 推荐目录映射正确；
- 逐章真实模型生成、人工编辑和阻断校核；
- 整本 DOCX 可打开、章节顺序正确、来源总表完整；
- Docker 健康检查、失败重试和隐私边界检查。
