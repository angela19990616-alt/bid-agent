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
POST /api/v1/workspaces/{workspace_id}/retry
GET  /api/v1/workspaces/{workspace_id}/requirements?view=proposal
GET  /api/v1/workspaces/{workspace_id}/requirements?view=compliance
PUT  /api/v1/workspaces/{workspace_id}/outline
POST /api/v1/workspaces/{workspace_id}/sections/{section_id}/generate
PUT  /api/v1/workspaces/{workspace_id}/sections/{section_id}/content
POST /api/v1/workspaces/{workspace_id}/sections/{section_id}/approve
POST /api/v1/workspaces/{workspace_id}/review
GET  /api/v1/workspaces/{workspace_id}/review
GET  /api/v1/workspaces/{workspace_id}/review/download?format=md|json
POST /api/v1/workspaces/{workspace_id}/exports
GET  /api/v1/workspaces/{workspace_id}/exports/{export_id}/download
```

旧 `/projects` 等兼容接口仅在非生产环境且显式启用
`ENABLE_LEGACY_API=true` 时加载；生产默认关闭，防止绕过工作区会话边界。

上传接口先完成文件校验和解析，立即返回内部 workspace 及 `extracting` 状态；
Requirement 提取、知识匹配和推荐目录规划在受控后台任务中继续执行。前端轮询
`GET /workspaces/{workspace_id}`，状态变为 `outline_ready` 后进入技术要点页面。
这样真实大文件不会因模型处理耗时而占用一个长连接。长任务写入 PostgreSQL
`processing_jobs` 持久队列，由独立 `worker` 容器领取执行；Web 容器始终只负责
短请求。Worker 重启会恢复超时未完成任务，多个 Worker 领取任务时使用数据库锁
避免重复执行。
处理失败时 workspace 回到 `draft`，前端可调用 `POST /retry`，复用已保存的有效
文档、Requirement 指纹去重和工作流快照，从中断后的提取/规划阶段继续执行。

前端 Nginx 固定代理到唯一容器名 `bid-backend`，避免开发机上其他 Compose 项目
占用通用 `backend` 网络别名后随机命中新旧接口。

章节生成接口支持可选 `instruction`，用于调整本章侧重点、结构、详略和表达。
该微调要求不能覆盖来源追溯、事实边界、禁止虚构和隐私规则。生成正文入库前会
清理 UUID、Prompt 标签和“要求编号”等内部标识，用户页面与导出文件只保留可读
方案正文。

### 等待时间与临时会话边界

处理中显示的预计时长不是固定文案。后端从本机已完成工作流中读取真实处理耗时和
文档 `source_count`，按当前文档工作量计算预计剩余区间，并返回历史样本数量。
历史样本不足时明确返回 `insufficient_history`，前端显示“暂无可靠预计时长”，
不会编造分钟数。

新上传方案会绑定随机浏览器会话 Cookie 和来源 IP 的会话密钥哈希。原始会话令牌
和明文 IP 均不写入数据库。工作区读取、重试、Requirement、目录、章节、Review、
DOCX 导出和所有下载接口都必须同时通过会话与 IP 校验；失败统一返回未找到，避免
泄露方案是否存在。

前端只把当前 workspace 放在 `sessionStorage` 中：同一标签页刷新可继续，关闭
标签页或浏览器会话后入口自动清空，不再提供跨会话“最近方案恢复”。不同 IP 即使
获得旧链接或内部编号，也不能读取 Review 或下载文件。

公网试用入口由 `BID_AGENT_INVITE_CODE` 保护。验证成功后，后端签发带有效期的
HttpOnly、SameSite=Strict 签名 Cookie；邀请码不会写入前端存储。未授权请求不能
读取工作区、上传文件、生成章节或导出。更换服务器 `.env` 中的邀请码并重启服务
会立即使此前签发的 Cookie 失效。默认授权有效期为 168 小时，可通过
`BID_AGENT_INVITE_ACCESS_TTL_HOURS` 调整。

当前单码模式只适合小范围受邀试用。若需要按用户统计次数、单独吊销或控制模型
额度，应新增一人一码、使用计数和管理后台，不能继续共享同一个邀请码。

## 数据迁移

应用启动时运行 `python -m app.database.migrate`。关键迁移：

- `009_proposal_workspaces.sql`：Requirement 方案相关性、章节映射、文件有效性和
  私有知识资格、推荐目录顺序。
- `010_rule_knowledge_engine.sql`：规则版本、企业知识、工作流轨迹、知识匹配、
  生成快照和整本方案导出。
- `012_proposal_review.sql`：段落级来源、历史案例使用记录、双轮 Proposal
  Review、自动修复版本和导出审查关联。
- `013_session_workspace_access.sql`：临时浏览器会话哈希、来源 IP 绑定和访问
  边界。

迁移文件应用后禁止修改，否则校验和保护会拒绝启动；后续变更应新增迁移。

## 本地运行

不要把真实密码或模型密钥提交到 Git。复制 `.env.example` 为 `.env`，在本机
私密文件中人工填写。

模型调用统一经过兼容 OpenAI SDK 的客户端接口，当前国内部署默认连接阿里云百炼：
在私密 `.env` 中填写 `DASHSCOPE_API_KEY`，并使用百炼兼容端点、
`qwen-plus` 和 `text-embedding-v4`。`OPENAI_BASE_URL`、`LLM_MODEL`、
`EMBEDDING_MODEL` 和 `EMBEDDING_DIMENSIONS` 均可配置，切换供应商不需要修改
Agent 或业务服务。真实 Key 只能写入本机或服务器 `.env`，禁止发到聊天或提交
Git。

公网部署必须使用许可生产自动化调用的百炼按量计费 Key 或 Token Plan 团队版
Key。Token Plan 个人版（Lite、Standard、Pro）只用于个人交互式开发工具，不能
作为本服务的生产 Key；不同产品的 Key 与 Base URL 也不能混用。

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
BID_AGENT_BRANCH=codex/feat-frontend-integration \
  bash scripts/deploy_ecs.sh
```

脚本会拒绝非 `/opt/bid-agent` 目录和脏工作区；先快进目标分支并备份 PostgreSQL，
再构建、启动和轮询健康接口。失败时输出部署前提交和备份文件，但不会自动执行破坏性
回滚。数据库迁移采用前向迁移；涉及数据结构回滚时必须使用备份和单独的补偿迁移，
不能直接删除生产数据。

## 完成定义

“代码已写”不等于完成。一次可交付验收至少包括：

- 真实 PDF/DOCX 上传和有效性拒绝测试；
- 原文页码/段落可追溯的 Requirement；
- 技术写作要求与合规提醒分流；
- 规则版本及运行快照可查询；
- 写作前企业知识匹配结果可查询；
- 推荐目录映射正确；
- 逐章真实模型生成、人工编辑和非阻断校核提醒；
- 整本 DOCX 可打开、章节顺序正确、来源总表完整；
- Docker 健康检查、失败重试和隐私边界检查。

## Proposal Review 与交付提醒

正式交付流程为：

```text
需求确认 → 知识匹配 → 章节生成 → 初次 Proposal Review
→ Auto Fix → 最终 Proposal Review → Deliverability Gate → DOCX
```

章节每个非空内容块都会在 `content_provenance` 中记录来源类型、可读来源名称、
采购文件位置或知识条目、使用方式、核验状态和置信度。历史案例一旦影响正文，
还会写入 `historical_case_usage`；历史案例默认只能用于结构或语言参考，未经核验
的企业事实不得进入最终文档。

点击前端“执行交付审查”，或调用 `POST /workspaces/{id}/review`，系统会生成：

- `exports/{workspace}/reviews/proposal_review.json`：机器可读报告；
- `exports/{workspace}/reviews/Proposal_Review.md`：用户可读报告。

报告分别列出 Requirement Coverage、Scoring Coverage、Knowledge Usage、
Truth and Privacy Review、Language and AI Style Review 以及每一项交付检查。
检查会自动清理可确定修复的问题，其余结果作为人工提醒，不阻断章节确认或 Word 导出。
用户可见报告不展示 Requirement UUID、数据库 ID 或其他内部标识。

Auto Fix 只执行可确定的安全修复：删除内部标识、敏感字段、未经核验的高风险
企业事实和无依据的政策/机构/时间承诺，清理 Markdown 装饰、Emoji、箭头及
口号化表达。无法确认的评分缺口或事实不会被补造，而是保留为 Review 风险项。

门禁阈值位于 `config/rules/compliance.default.json` 的
`deliverability_gate`，不是写死在 Prompt 中。只有最终复检完成且真实性、
隐私、需求覆盖、评分点覆盖和来源追溯全部达到配置阈值，正式 DOCX 导出才会
放行；否则 Review 会明确标记“不建议正式交付”。
