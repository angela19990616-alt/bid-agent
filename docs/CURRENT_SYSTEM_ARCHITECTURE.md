# Bid Agent 当前完整架构与知识图谱演进图

> 更新日期：2026-08-08  
> 口径：已实现与未实现能力分开标注，本文可直接提供给 ChatGPT 或其他架构评审人员。

## 1. 产品定位

Bid Agent 不是“上传文件后让大模型自由写标书”，而是一套受控的投标响应决策与交付系统：

```text
理解招标文件
  → 保留原始格式和来源
  → 决定每个响应事项如何处理
  → 在权限内匹配企业事实和历史结构
  → 按招标模板回填或按章生成
  → 追溯、校核、人工确认
  → 导出 Word
```

三条底线：

1. 规则驱动，不把业务规则全部写死在 Prompt 中。
2. 企业事实必须有权威来源，历史标书不等于企业事实。
3. 任务流程是有限状态机，Agent 不允许自由对话或无限循环。

## 2. 当前系统总体架构

```mermaid
flowchart TB
    U["用户浏览器"] --> N["Nginx + Next.js 前端"]
    N --> A["邀请码 / Session 访问边界"]
    A --> API["FastAPI REST API"]

    subgraph APP["应用服务层"]
        API --> WS["Workspace Service"]
        API --> RS["Requirement / Response Service"]
        API --> PS["Proposal / Section Service"]
        API --> ES["Review / Export Service"]
        API --> CS["Configuration / Rule Service"]
    end

    WS --> FS["DOCX / PDF 文件存储"]
    WS --> JOB["processing_jobs 持久任务"]
    JOB --> WK["Workspace Worker"]
    WK --> DRAFT["整本初稿任务：逐章生成 + 逐章校核"]
    WK --> PIPE["Controlled Pipeline"]

    PIPE --> RULE["Rule Engine"]
    PIPE --> TMPL["Template + Strict Fill Engine"]
    PIPE --> REQ["Requirement Decision Engine"]
    PIPE --> KNOW["Knowledge + Proposal Memory Engine"]
    PIPE --> WRITE["Planner + Chapter Writer"]
    PIPE --> REVIEW["Review + Delivery Gate"]

    RULE --> PG[("PostgreSQL + pgvector")]
    TMPL --> PG
    REQ --> PG
    KNOW --> PG
    WRITE --> PG
    REVIEW --> PG

    WRITE --> ROUTER["Model Router + Budget + Privacy Redaction"]
    ROUTER --> DS["DeepSeek"]
    ROUTER --> BL["百炼备用模型池"]

    REVIEW --> OUT["保真 DOCX / 技术方案 DOCX"]
    REDIS[("Redis")]
    API -. "当前仅健康检查/预留" .-> REDIS
```

### 当前部署拓扑

```mermaid
flowchart LR
    INTERNET["公网用户"] --> P80["ECS :80"]
    P80 --> FE["frontend / Nginx"]
    FE --> BE["backend / FastAPI :8000"]
    BE --> PG[("PostgreSQL :5432")]
    BE --> RD[("Redis :6379")]
    WORKER["worker"] --> PG
    WORKER --> RD
    BE --> VOL1["document_storage"]
    WORKER --> VOL1
    BE --> VOL2["export_storage"]
    WORKER --> VOL2

    NOTE["5432 / 6379 / 8000 只绑定 127.0.0.1"]
    NOTE -.-> PG
    NOTE -.-> RD
    NOTE -.-> BE
```

当前正式运行和大文件分析环境为阿里云 ECS。本地 Mac 主要负责代码修改、单元测试和轻量回归。

## 3. 完整业务执行链路

```mermaid
flowchart TD
    UP["上传 PDF / DOCX"] --> VAL["Document Validator"]
    VAL --> PARSE["Parser + Document Ingestion"]
    PARSE --> SRC["原文、页码、段落、表格位置"]

    SRC --> TD["Template Detection"]
    TD --> MODE{"Generation Mode"}
    MODE -->|"识别到 DOCX 格式"| STRICT["Strict Template"]
    MODE -->|"仅有 PDF 格式"| PDF["PDF 人工保真门禁"]
    MODE -->|"没有格式"| PLAN["Requirement-driven Planning"]

    SRC --> ER["Load Extraction Rules"]
    ER --> EXT["Requirement Extractor"]
    EXT --> NORM["Requirement Normalizer"]
    NORM --> CLASS["Proposal-oriented Classifier"]
    CLASS --> CR["Classification Reviewer"]
    CR --> STRAT["Response Strategy"]
    STRAT --> CONFLICT["Conflict Detection"]
    CONFLICT --> PRIORITY["Risk + Proposal Value Ranking"]

    PRIORITY --> ACTION{"Response Action"}
    ACTION -->|"write_into_proposal"| MAP["Proposal Mapping"]
    ACTION -->|"response_table"| RT["响应表"]
    ACTION -->|"compliance / risk"| RC["合规清单 / 风险报告"]
    ACTION -->|"attachment"| AL["附件材料清单"]
    ACTION -->|"ignore"| IG["忽略原因和反馈记录"]

    MAP --> KP["Knowledge Permission Filter"]
    KP --> KM["Enterprise Knowledge Matching"]
    KM --> PM["Proposal Memory Matching"]

    STRICT --> TP["模板标题成为唯一写作骨架"]
    PLAN --> RP["推荐技术方案目录"]
    TP --> HUMAN["人工确认目录 / 变量 / 材料"]
    RP --> HUMAN
    KM --> HUMAN
    PM --> HUMAN

    HUMAN --> WRITE["分章生成"]
    WRITE --> CRED["章节来源与 Requirement 覆盖记录"]
    CRED --> CHREV["Chapter Review"]
    CHREV --> EDIT["人工编辑 / Prompt 微调"]
    EDIT --> FULL["Proposal Review"]
    FULL --> GATE["Delivery Gate"]
    GATE --> FILL["原表格字段回填 + 原章节正文插入"]
    FILL --> DOCX["Word 导出"]
```

## 4. 模板优先生成决策

```mermaid
flowchart TD
    D["招标文件"] --> DET{"是否识别到投标文件格式"}
    DET -->|"是，DOCX"| KEEP["保留原标题、表格、顺序、样式"]
    KEEP --> FIELD["空白字段 → 严格字段映射"]
    KEEP --> SECTION["写作标题 → 分章写作任务"]
    FIELD --> DEC{"Fill Decision"}
    DEC -->|"AUTO_FILL"| AUTO["原位自动回填"]
    DEC -->|"REVIEW_REQUIRED"| MANUAL["人工确认后回填"]
    DEC -->|"MISSING"| MISS["留空并进入人工事项档案"]
    SECTION --> GEN["正文写入模板同名章节"]

    DET -->|"是，PDF"| PDFG["不伪称坐标级自动回填，进入人工保真门禁"]
    DET -->|"否"| FALLBACK["响应事项 + 写作规则 + 历史结构 → 推荐目录"]
```

## 5. Rule Engine、Knowledge Engine 和 Model Router

```mermaid
flowchart LR
    subgraph RULES["可版本化规则"]
        R1["文档抽取规则"]
        R2["分类与响应策略规则"]
        R3["冲突与排序规则"]
        R4["模板生成规则"]
        R5["企业知识规则"]
        R6["写作与合规规则"]
        R7["模型路由与隐私脱敏规则"]
    end

    subgraph KNOWLEDGE["当前知识层"]
        K1["企业知识 enterprise_knowledge"]
        K2["五组机构私有历史案例"]
        K3["Proposal Memory 结构模式"]
        K4["pgvector 语义检索"]
        K5["机构 / Workspace 权限过滤"]
    end

    RULES --> TASK["受控任务上下文"]
    KNOWLEDGE --> TASK
    TASK --> PRIV["本地脱敏"]
    PRIV --> ROUTE["按任务、质量、预算、健康状态选模型"]
    ROUTE --> MODEL["提取 / 分类 / 写作 / 终审"]
    MODEL --> AUDIT["模型使用、来源、规则快照审计"]
```

## 6. 当前核心数据关系

```mermaid
erDiagram
    PROJECT ||--o{ DOCUMENT : contains
    DOCUMENT ||--o{ DOCUMENT_CHUNK : ingested_as
    PROJECT ||--o{ WORKFLOW_RUN : executes
    PROJECT ||--o{ PROCESSING_JOB : queues
    PROJECT ||--o{ REQUIREMENT : owns
    REQUIREMENT ||--o{ REQUIREMENT_SOURCE : traced_to
    DOCUMENT_CHUNK ||--o{ REQUIREMENT_SOURCE : supports
    REQUIREMENT }o--o{ SECTION : mapped_into
    SECTION ||--o{ SECTION_VERSION : versions
    SECTION_VERSION ||--o{ REVIEW_FINDING : reviewed_by
    SECTION_VERSION ||--o{ PROVENANCE_RECORD : attributed_by
    PROJECT ||--o{ CONFLICT_RECORD : detects
    PROJECT ||--|| GENERATION_PROFILE : configures
    GENERATION_PROFILE }o--|| DOCUMENT : template_source
    PROJECT ||--o{ EXPORT_RECORD : produces
    ENTERPRISE_KNOWLEDGE }o--o{ REQUIREMENT : matches
    PROPOSAL_MEMORY }o--o{ SECTION : guides_structure
    RULE_DEFINITION ||--o{ WORKFLOW_RUN : snapshotted_in
```

注：这是业务关系图，不代表每个关系都以单独物理关联表实现；部分匹配和快照当前保存在 JSONB 或工作流记录中。

## 7. 当前已实现、部分实现与待实现

| 能力 | 状态 | 说明 |
|---|---|---|
| PDF / DOCX 上传、解析与有效性判断 | 已实现 | 支持原文分块和来源保留 |
| Requirement 抽取、标准化、分类、响应决策 | 已实现 | 含风险、方案价值、响应动作和目录映射 |
| 冲突检测和四种人工决策 | 已实现 | 提交澄清只暂停受影响章节 |
| DOCX 格式识别与原表回填 | 已实现 | 表格与写作章节均服从已识别模板 |
| 分章生成、校核、人工编辑、Word 导出 | 已实现 | 支持来源追溯和交付门禁 |
| 五组历史中标案例结构参考 | 已实现 | 仅限机构私有结构学习，禁止转化为企业事实 |
| 企业事实严格三态回填 | 已实现底层 | 真实企业数据 API 未接入，因此许多字段仍是待审核或缺失 |
| 业绩、人员、证书、社保和评分数量自动配组 | 部分实现 | 策略和接口边界已有，待真实台账和钉钉 API |
| 扫描 PDF 坐标级保真回填 | 未实现 | 当前不伪称可自动回填，保持人工门禁 |
| 企业知识图谱 | 未实现 | 现有追溯数据可作为图谱迁移基础 |

## 8. 企业知识图谱演进架构（下一阶段）

不建议立即引入一个独立的“大而全图数据库”。先在 PostgreSQL 中建立稳定的企业实体、关系和证据模型，结合 pgvector 做候选召回；只有当多跳关系查询成为性能瓶颈时，再同步到 Neo4j 或其他图引擎。

```mermaid
flowchart TB
    subgraph SOURCES["授权数据源"]
        DING["钉盘 / 钉钉知识库"]
        LEDGER["项目合同台账"]
        HR["人员 / 证书 / 社保数据"]
        QUAL["公司资质 / 荣誉"]
        CASE["历史招标 + 中标投标文件"]
        APPROVAL["材料调用审批记录"]
    end

    SOURCES --> ING["权限校验 + 解析 + 脱敏 + 版本化"]
    ING --> ENTITY["实体归一化 / 去重"]
    ENTITY --> GRAPH[("企业知识图谱")]
    ENTITY --> VECTOR[("pgvector 语义索引")]

    GRAPH --> PF["Permission Filter"]
    VECTOR --> PF
    PF --> MATCH["评分条件 / Requirement 驱动的候选匹配"]
    MATCH --> EXPLAIN["匹配路径、不匹配原因、数量上限和去重解释"]
    EXPLAIN --> HUMAN["人工选择 / 审批"]
    HUMAN --> ASSEMBLE["响应表、人员清单、业绩材料和证明附件装配"]
    ASSEMBLE --> AUDIT["来源、权限、审批和导出审计"]
```

### 建议的图谱实体

- `Company`：公司、分支机构、统一社会信用代码。
- `Person`：人员；敏感证件值不直接进通用图谱。
- `Certificate`：资质或人员证书、有效期和签发机构。
- `Project`：历史项目、行业、地区和服务类型。
- `Contract`：合同编号、甲方、服务内容、时间和可用材料范围。
- `CaseEvidence`：合同首尾页、中标通知书、评价函等证据。
- `TenderRequirement`：当前项目的响应事项。
- `ScoringPoint`：采分条件、数量、上限、一人多证等规则。
- `Material`：可装配文档或图片，只保存受控存储引用。
- `ApprovalPolicy`：例如合同全页需业务发展部审批。

### 建议的核心关系

```mermaid
erDiagram
    COMPANY ||--o{ PERSON : employs
    PERSON ||--o{ CERTIFICATE : holds
    PERSON }o--o{ PROJECT : participated_in
    COMPANY ||--o{ CONTRACT : signed
    CONTRACT }o--|| PROJECT : proves
    CONTRACT ||--o{ CASE_EVIDENCE : supported_by
    PROJECT ||--o{ MATERIAL : has_material
    TENDER_REQUIREMENT ||--o{ SCORING_POINT : evaluated_by
    SCORING_POINT }o--o{ CERTIFICATE : requires
    SCORING_POINT }o--o{ PROJECT : requires_experience
    TENDER_REQUIREMENT }o--o{ MATERIAL : evidenced_by
    MATERIAL }o--o{ APPROVAL_POLICY : governed_by
```

### 图谱设计底线

1. 图谱节点必须带 `organization_key`、来源、版本、核验状态和权限范围。
2. 图谱中的“关系”也必须有证据，不能只因为语义相似就生成事实边。
3. 身份证号、证件原图等保存在受控数据仓，图谱只保存脱敏属性和受控引用。
4. 语义检索用于召回候选，结构化规则和人工审核决定能否真正使用。
5. 不把知识图谱称为“模型训练”，它是机构私有、可追溯的检索和决策数据层。

## 9. 知识图谱实施顺序

1. 先定义实体 ID、来源和权限模型。
2. 先接入公司、项目合同台账、人员证书索引三类高价值数据。
3. 建立台账记录到证明材料的可审计关联。
4. 用真实评分办法验证“条件 → 候选人员/业绩 → 材料”的匹配路径。
5. 再接入钉钉文件下载和审批流。
6. 最后评估是否真的需要独立图数据库，避免过早增加运维复杂度。

## 10. 当前需要特别关注的架构债务

1. **任务队列**：当前 Worker 从 PostgreSQL `processing_jobs` 通过 `SKIP LOCKED` 取任务，Redis 还没有真正承接队列。单机 MVP 可用，多 Worker 并发前应评估 Redis Queue / Celery / RabbitMQ。
   上传解析和整本初稿均已采用持久任务；初稿只生成和校核，不自动批准。Worker 常驻期间周期恢复超时任务，浏览器断开不影响继续运行。
2. **目录层级持久化**：模板能识别五级标题，但当前生成任务的 Section 模型仍偏扁平，父子节点编辑需后续迁移。
3. **企业权威事实**：严格回填决策已存在，但真实企业数据接口未打通前，不能大规模自动回填。
4. **扫描件保真**：需要 OCR、表格坐标、图片槽位和版式渲染对比后，才能对扫描 PDF 宣称自动保真回填。
