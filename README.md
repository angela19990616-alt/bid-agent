# Bid Agent

Bid Agent 是面向技术投标方案生成的受控 AI 工作台。用户只需上传 PDF/DOCX
招标文件，系统在后台创建工作区，完成有效性检查、解析、技术要求与评分点提取、
推荐目录、按章节生成、人工编辑、合规校核和整本 Word 导出。

产品不要求用户理解“项目”或逐条确认大量候选条款。商务、资格、密封和评审纪律
仍被保存，但默认作为合规提醒，不与技术写作要求同级展示。

## 核心架构

系统不是 Prompt Driven，而是三个相互独立的底座：

- Rule Engine：加载、校验、版本化和激活提取、方案分类、写作与校核规则。
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
  → Response Item Extractor
  → Response Item Normalizer
  → Proposal-oriented Classification（条款属性）
  → Response Strategy（响应动作、风险、章节映射）
  → Source Grouping + Conflict Detection（差异与真实冲突）
  → Response Prioritization（风险与方案价值双排序）
  → Load Enterprise Knowledge
  → Knowledge Matching
  → Proposal Memory Matching
  → Load Proposal Writing Rules
  → Proposal Planner
  → Chapter Writer
  → Chapter Review
  → Delivery Gate
  → Export
```

每个模块职责单一。模型只负责边界明确的抽取或写作；阶段转换、版本选择、知识匹配、
校核和重试边界由应用控制。

## 规则配置

Git 中的默认规则：

- `config/rules/extraction.default.json`
- `config/rules/classification.default.json`
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
POST /api/v1/configuration/proposal-memory/case-pairs
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

成对导入“招标文件 + 中标响应 DOCX”时，系统只提取章节层级、论证维度、
段落密度和表格字段角色，历史正文、客户、金额、人员、资质和项目参数不会进入
Proposal Memory。当前本地开发环境已接入五组经授权的招标与中标响应案例；案例原件
与清单位于 Git 忽略的私有目录，不随代码提交或上传服务器。

五组案例到齐后，建议先复制
`config/examples/historical_case_pairs.example.json` 到案例私有目录，填写相对路径并
执行完整性与隐私 dry-run；只有五组全部通过才会进入正式批量写入，避免因清单缺项
产生不完整案例库。正式写入使用同一数据库事务，任一结构模式写入失败时整批回滚：

```bash
python scripts/audit_template_case_readiness.py
python scripts/import_historical_case_pairs.py /path/to/private/pairs.json --dry-run
python scripts/import_historical_case_pairs.py /path/to/private/pairs.json
```

第一条命令只读检查模板分支、案例数量和历史事实隔离，不写数据库，也不在报告中
输出文件名、原文或历史项目事实。当前本地验收结果是 5/5 组有效、258 个去噪后的
结构模式，4 组采用严格模板回填、1 组采用无模板规划，完整五组门禁通过。

清单及案例文件不应提交 Git。批量导入结果只报告组数、结构模式数、机构私有范围和
事实禁用状态，不打印案例正文、文件路径或内部 ID。重复刷新同一来源时，旧模式先
标记为 `retired` 再写入新模式；匹配时优先项目类型和行业，再匹配章节结构，并过滤
同一案例的重复章节和明显低相关结果。

## 模板优先生成

上传 DOCX 后直接检测；上传 PDF 后先在服务器本地转为可编辑 DOCX，
再执行同一套模板检测。系统在 Requirement 提取前加载独立的
`template_generation.default.json`，识别招标文件末尾或单独附件中的“响应文件格式”。
最终只有两个写作器：检测到模板使用 `strict_template_writer`；确认无模板
使用 `planned_proposal_writer`。

- DOCX 模板保留原文件包中的样式、表格、区块顺序、页眉页脚和节设置，仅裁去模板
  章节之前的采购正文，并在明确字段或章节位置回填已核验内容。
- 上传时自动建立模板字体档案；字段回填保留原单元格字体，新生成正文继承响应章节的字体和
  字号，不再强制替换为系统默认字体。导出 Word 保留原字体名称；未授权商业字体不随系统非法打包。
- 文本字段先判断姓名、企业名称、项目编号、电话、日期等语义类型，再接受同类型值；
  标签、填写说明、签字盖章提示和附件说明不能冒充字段值。每个候选值显示来源文件、
  章节及页码或段落，缺少精确定位的企业事实只进入人工审核。
- 资格图片和扫描件必须同时具备已授权真实文件、材料类型和原文件位置，才进入严格映射
  审核；知识库暂未返回文件位置时保留待审核，不由模型猜测附件。
- 缺失企业字段保持原占位符并进入“人工事项档案”；用户可先生成草稿，系统不会
  猜测企业事实。找不到章节回填位置时仍阻止导出，避免破坏模板结构。
- 正式交付文件名以 `AI投标文件_项目名称_时间.docx` 开头，文档标题为
  `《AI投标文件+项目名称》`。严格模板保留原目录、页眉页脚和分页；无模板分支自动
  生成目录后再写入各章节。
- PDF 转换成功后，有响应模板即升级为严格回填，无模板才进入目录生成。
  转换失败或结构校验失败时显式停在 `template_conversion_required`，
  不得把失败误判为“无模板”。
- 严格模板找不到章节落点时，导出门禁阻止生成错误版式并返回明确缺项。

工作区响应返回 `generation_mode`、`template_filename` 和 `template_fidelity`；兼容
接口可通过 `GET /api/v1/projects/{project_id}/generation-profile` 查看完整决策。

当前 MVP 的租户边界是单机构部署边界；多租户上线前必须增加真实身份认证、
organization_id 行级隔离和权限审计，不能仅依赖前端隐藏。

## 产品 API

```text
POST /api/v1/workspaces
GET  /api/v1/workspaces/{workspace_id}
POST /api/v1/workspaces/{workspace_id}/retry
GET  /api/v1/workspaces/{workspace_id}/requirements?view=all|proposal|scoring|compliance|risk
PATCH /api/v1/workspaces/{workspace_id}/requirements/{requirement_id}/strategy
PUT  /api/v1/workspaces/{workspace_id}/outline
POST /api/v1/workspaces/{workspace_id}/sections/{section_id}/generate
POST /api/v1/workspaces/{workspace_id}/generate-draft
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
目录确认后可调用 `POST /generate-draft`，把“一章一章点击”改为持久任务：Worker
顺序生成全部未完成且无冲突的章节，并在每章完成后保存版本和校核结果。HTTP 只负责
入队和查询进度，浏览器断开不会丢失任务；整本初稿完成后仍停在人工确认前，不会自动
批准或正式导出。
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

前端不持久化 workspace 或导出记录：刷新、重新打开页面或重新进入工作台后均从
上传入口开始，不显示历史方案和历史 Word 下载入口。服务端仍保留受会话与来源 IP
约束的处理中间结果，避免刷新页面触发破坏性删除；但前端不提供任何恢复入口。
不同 IP 即使获得旧链接或内部编号，也不能读取 Review 或下载文件。

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
- `014_proposal_classification.sql`：方案导向分类字段、规则类型及历史分类迁移。
- `015_model_usage_budget.sql`：工作流模型调用与 Token 预算审计。
- `021_response_strategy.sql`：响应策略规则类型、文档结构事项及历史硬规则纠正。
- `012_proposal_review.sql`：段落级来源、历史案例使用记录、双轮 Proposal
  Review、自动修复版本和导出审查关联。
- `013_session_workspace_access.sql`：临时浏览器会话哈希、来源 IP 绑定和访问
  边界。

迁移文件应用后禁止修改，否则校验和保护会拒绝启动；后续变更应新增迁移。

## 本地运行

不要把真实密码或模型密钥提交到 Git。复制 `.env.example` 为 `.env`，在本机
私密文件中人工填写。

模型调用统一经过兼容 OpenAI SDK 的客户端接口。默认使用 DeepSeek 官方接口：
抽取与分类优先 `deepseek-v4-flash`，方案写作与终审优先
`deepseek-v4-pro`；百炼保留为有界备用。分别在私密 `.env` 中填写
`DEEPSEEK_API_KEY` 和 `DASHSCOPE_API_KEY`，
任务模型通过 `EXTRACTION_MODEL`、`CLASSIFICATION_MODEL`、
`WRITING_MODEL` 和 `REVIEW_MODEL` 分开配置，通用回退使用 `LLM_MODEL`。
向量模型仍使用百炼 `text-embedding-v4`。
`OPENAI_BASE_URL`、各模型变量、
`EMBEDDING_MODEL` 和 `EMBEDDING_DIMENSIONS` 均可配置，切换供应商不需要修改
Agent 或业务服务。真实 Key 只能写入本机或服务器 `.env`，禁止发到聊天或提交
Git。

所有聊天模型与向量模型调用在离开本机或服务器前统一经过
`privacy_redaction.default.json`。手机号、身份证号、邮箱、固定电话、明确标注的
联系人、联系地址和银行账号会替换为稳定占位符；映射只存在于本地进程内存，
模型响应返回后再本地恢复。原始采购文件和映射表不会随模型请求发送。技术指标、
评分口径、招标主体和企业能力证据不会被通用规则盲目删除，以免破坏生成依据。

公网部署必须使用许可生产自动化调用的百炼按量计费 Key 或 Token Plan 团队版
Key。Token Plan 个人版（Lite、Standard、Pro）只用于个人交互式开发工具，不能
作为本服务的生产 Key；不同产品的 Key 与 Base URL 也不能混用。

```bash
docker compose up --build -d
docker compose ps
curl http://127.0.0.1/health
```

访问 `http://127.0.0.1/`。前端通过同源 `/api/v1` 访问后端。

后台使用统计不暴露到公网前端，仅通过服务器 SSH 隧道访问。先执行：

```bash
ssh -N -L 18000:127.0.0.1:8000 root@101.200.154.141
```

保持终端窗口运行，再在本机浏览器打开
`http://127.0.0.1:18000/internal/usage`。页面只展示聚合使用量、成功率、
模型与 Token 统计，不展示文件名、项目名、用户标识、UUID、原文或密钥。

静态和单元检查：

```bash
bash scripts/verify_release.sh
```

### 本地响应支持升级

响应分析保持底层细粒度 Requirement，同时按“要求类型 + 响应动作 + 目标章节”
聚合给业务人员展示。`GET /api/v1/workspaces/{id}/response-support` 统一返回：

- 同类响应事项组；
- 招标文件格式与附件填写约束；
- 已核验人员/企业资格材料匹配结果；
- 采购原文到生成章节的双向审核地图。

章节生成支持 `balanced`、`closest_case`、`structure_only` 和 `current_only`
四种历史案例参考方式。历史案例只能提供结构、颗粒度和表达方法；企业事实仍必须来自
已核验的机构私有知识。

当前版本已完成 DOCX 原模板的二进制保真回填、严格程度判断和人工复核门禁。

严格回填在字段匹配之前执行 Entity Resolution + Role Binding：每个空位保存章节、
表格/段落坐标、完整上下文、业务属性、实体类型和项目角色。法定代表人只读取当前
投标主体的法定代表人绑定；授权代表、项目负责人、技术负责人、联系人和签字人只
读取当前项目有效角色关系。同一人员的姓名、职务、身份证和后续证照附件必须沿同一
`person_id` 取得；无绑定时仅展示同一机构的已核验候选，禁止从历史案例或全部人员中
猜选。重复出现的“联系电话”等属性以唯一槽位键落到原表格坐标，不再跨角色覆盖。

迁移 `024_requirement_semantic_graph.sql` 增加机构、人员、项目角色关系和响应事项语义图。
身份证号和电话只预留密文及脱敏列，历史案例继续只作机构私有写法参考，不能升级为
已核验企业事实。生产应用迁移前应先备份 PostgreSQL；回滚应用版本时保留 024 的新增
表和列，避免删除审计关系，待确认无引用后再另行制定数据回退脚本。
模板字段默认由采购文件与机构私有 `enterprise_knowledge` 自动匹配：只有
`company_profile` / `qualification` 中带 `verified_enterprise_fact=true` 的结构化
事实才可自动回填；前端不再要求业务人员重复录入，只展示自动填写、待审核和资料缺失。
五份历史中标案例位于独立的“大岳五案例示例库”：写作环节只学习结构与表达；
严格回填环节可提取字段候选值，但必须同时展示案例名称和原文摘要，人工确认后才能进入正式文件。
候选值不会被标记为已核验企业事实，也不会进入公共训练集。
PDF 已支持先转为可编辑 DOCX 再分流，但扫描件 OCR、复杂版式像素级还原、
Excel 附件和资格证书图片版面编排属于下一增量。转换后必须先通过 Word 可编辑
结构校验，系统不得声称已经像素级还原所有 PDF 格式。

该命令是每次更新的统一交付门禁：检查 Python 漏导入/未定义名称、外部规则、
受控工作流无重复阶段、模型最多三次尝试、后端全量测试、前端生产构建、
Docker Compose 配置、已跟踪文件敏感信息和 Git 差异。GitHub Actions 会在
每次推送和 Pull Request 中再次运行同一套检查。

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

验收脚本会实际执行上传、解析、Requirement 提取、目录规划和后台整本初稿生成。
报告只记录状态、数量、ID、字符数和校核严重级别，不记录招标原文、生成正文、
企业知识、文件名或模型密钥。章节仍必须经过人工编辑和确认后才能整本导出。
在专门的受控验收环境中，可增加 `--approve-and-export`：脚本会明确批准当前生成版本、
执行只读整本 Review、通过交付门禁后导出，并用 `python-docx` 重新打开产物验证非空。
脚本使用同一 Cookie 会话完成上传后的轮询；若本地启用了邀请码，可在当前终端临时
注入 `BID_AGENT_INVITE_CODE` 环境变量，脚本会先授权且不会把邀请码写入报告。

## ECS 部署

服务器目录为 `/opt/bid-agent`。通过 GitHub 同步代码后：

```bash
cd /opt/bid-agent
BID_AGENT_BRANCH=codex/v2-response-map \
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
交付审查只读取已保存且已确认的版本，不会在导出时偷偷改写正文。任何阻断级真实性、
隐私、覆盖或追溯问题都会阻止正式 Word 导出；用户应先按报告修改并重新确认章节。
用户可见报告不展示 Requirement UUID、数据库 ID 或其他内部标识。

生成和人工保存阶段可执行确定性文本清理；正式导出阶段不再 Auto Fix。无法确认的
评分缺口或事实不会被补造，而是保留为 Review 风险项。

门禁阈值位于 `config/rules/compliance.default.json` 的
`deliverability_gate`，不是写死在 Prompt 中。只有最终复检完成且真实性、
隐私、需求覆盖、评分点覆盖和来源追溯全部达到配置阈值，正式 DOCX 导出才会
放行；否则 Review 会明确标记“不建议正式交付”。

### 面向技术方案的 Requirement 分类

Requirement 提取后会加载独立的 classification rule，输出
`requirement_type`、`proposal_chapter`、`scoring_relation`、`importance`
和分类置信度。资格与商务要求保留为合规提醒，但不进入技术方案正文。
Proposal Planner 优先使用 `proposal_chapter`，`target_chapter` 仅作为旧数据
兼容字段。

分类采用混合执行：明确命中高优先级规则的条目不调用模型；只有低置信或无法映射
的条目才进行一次批量模型分类。随后在同一进程内完成分类冲突复核、用户可见内容
Review、安全机械修复和复检，不逐条调用模型，也不进行无限循环。Review 报告展示
分类质量、高置信比例、低置信数量、未映射数量与冲突数量。

分类之后加载独立的 `response_strategy` rule，决定 `response_action`、
`proposal_mapping`、`scoring_impact` 和 `priority`。Proposal Planner 只消费
同时满足 `response_action=write_into_proposal`、`proposal_relevance=true` 和
`target_chapter!=null` 的事项，商务合规、附件、响应表和风险提醒不会进入技术正文。

冲突检测采用本地规则优先，只比较同一对象、同一指标。结果区分评分增强、
兼容差异、待复核差异和真实冲突；权威等级只用于解释，不自动覆盖来源。真实冲突
保留两处原文及位置，由人工选择采用 A、采用 B、分别响应或提交澄清。提交澄清只
暂停关联章节，未解决的真实冲突阻止正式整本导出。

响应排序把风险 `P0-P3` 与方案价值 `★★★★★-★` 分开。★★★★★必须有明确评分
依据；不进入技术方案的事项价值为 `none`，但仍可作为 P0 风险置顶提醒。

响应事项页面按 `P0 → P1 → P2 → P3` 排序，并提供全部、技术方案、评分响应、
商务合规、风险提醒和冲突事项标签页。人工可将误分事项在“技术方案”和“商务合规”之间切换，
草稿目录随之双向同步；也可将每条标记为“需要”“不需要”或
“与原文不符”；反馈只保存在机构私有数据库中。被标记为“与原文不符”的完全相同
文本会在后续抽取中由本地规则过滤，不会上传外部服务，也不会触发额外模型调用。

硬性格式要求（目录/章节顺序、必写内容、篇幅、字体字号、表格、签章和装订等）
在 Requirement Extractor 阶段按独立规则提取并保留原文位置。Proposal Planner
优先采用采购文件明确给出的已有章节顺序；Chapter Writer 在生成前接收相关原文
约束；Proposal Review 单列格式约束覆盖情况。签章、装订等无法由系统可靠完成的
事项只进入人工复核，不虚构“已满足”。

### 受控自我优化与企业智库植入

系统不允许 Agent 自主改 Prompt 或无限反思。优化信号按以下边界处理：

- “与原文不符”反馈保存于机构私有数据库，后续仅精确过滤相同错误文本；
- 分类数量、低置信、冲突和无章节映射用于 Review 指标，规则修改仍需版本化和测试；
- 确定性 Review/Debug 只清理内部标识、机械标签和已知错误，不调用模型；
- 模型仅在规则无法高置信处理时使用；模型池至少保存 10 个文本候选，
  但可能计费的失败最多允许 2 次。

企业智库在章节写作前一次性匹配：先排除当前招标文件和当前项目，按章节标题与
Requirement 检索机构私有知识，再将匹配快照传给 Chapter Writer。企业简介、
资质、能力和案例只有标记为 `verified_enterprise_fact=true` 才能作为事实；
历史标书默认只参考结构、术语和响应方法，不能变成企业案例或资质。匹配结果、
规则版本和内容来源随章节版本保存，便于追溯和审计。

### 模型额度保护与受控自检

模型调用按 `workflow_run_id` 记入 `model_usage_events`。调用前使用数据库事务锁
原子预留预算，调用成功后以供应商返回的实际 Token 用量结算；失败调用也保留
预留量，避免异常重试绕过限制。系统按已解析正文字符数为每份文件分配预算：
小文件从 12 次调用、80,000 Token 起步，约 2 万汉字的常规 60 页招标文件可
获得约 37 次调用、240,000 Token；硬上限为 40 次、300,000 Token，可通过
`MAX_MODEL_CALLS_PER_WORKFLOW` 和 `MAX_MODEL_TOKENS_PER_WORKFLOW` 调低。

达到预算后系统停止新的模型请求。Requirement Extractor 每完成一批便写入
`requirement_extraction_batches` 检查点，重试会复用已完成批次，只处理剩余
部分。分类只对低置信条目调用一次批量模型；Review、机械 Debug 和复检均为
确定性单轮处理，不产生额外模型调用或自治循环。前端技术要点页显示当前工作流

模型 SDK 自带重试已关闭，由版本化 `model_routing` 规则统一控制重试和切模。
单次供应商请求默认最多等待 180 秒，超时后才能进入下一条受控备用路线，防止一个
模型无限占用 Worker。部署健康检查同时验证 `/health` 和经 Nginx 转发的
`/api/v1/access/status`，避免只检查静态首页而漏掉 502。
调用次数与动态上限。

章节写作不会复用文档抽取工作流的剩余额度。每次“生成本章”创建独立、受控的
写作运行，最多扫描 10 个不同候选、180,000 Token。无权限、未开通、模型不存在
等已知零消耗失败会立即切换并让该模型冷却 30 分钟；可能计费的失败最多 2 次。
每次调用始终按任务的固定质量顺序选择当前可用的最高级模型，备用模型成功不会
跨等级抢占首位。写作 Prompt 在规则层限制为 24,000 字符，并按响应事项、格式
要求、企业知识和方案记忆分别分配预算，避免备用模型因上下文上限不同再次失败。
反向代理为受控章节请求保留 300 秒响应窗口，生成成功后再返回并持久化版本。

模型池、任务候选顺序、冷却时间、输出上限和费用边界均位于
`config/rules/model_routing.default.json`。只有额度不足、限流、模型未开通、
输入长度不兼容、超时或供应商 5xx 等可恢复错误才会切换；业务校验、普通参数
错误或代码错误不会触发无边界重试。模型列表可人工维护和版本管理，不写死在
Chapter Writer 中。

旧项目需要应用新版分类规则时，可执行原位重分类；该操作保留响应事项 ID、
来源、人工状态和章节关联，不重新抽取文件：

```bash
docker compose exec -T backend \
  python -m scripts.reclassify_project <project_id>
```
