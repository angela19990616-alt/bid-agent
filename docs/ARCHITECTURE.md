# Bid Agent 可演进架构

## 1. 架构目标

Bid Agent 采用 Rule Driven、Knowledge Driven、Workflow Driven 三层底座。
模型不是业务规则的持有者，只在明确输入、输出和终止条件的节点中执行抽取或写作。

```mermaid
flowchart LR
    UI["技术方案工作台"] --> API["FastAPI 产品 API"]
    API --> WF["Controlled Workflow"]
    WF --> RE["Rule Engine"]
    WF --> KE["Knowledge Engine"]
    WF --> AI["Bounded AI Modules"]
    RE --> RDB[("规则版本与运行快照")]
    KE --> KDB[("机构私有知识与匹配结果")]
    AI --> LLM["大模型 API"]
    WF --> BDB[("业务状态与来源证据")]
    WF --> FS[("上传与 DOCX 存储")]
```

## 2. 受控调用流程

```mermaid
flowchart TD
    A["Document Upload"] --> B["Document Validator"]
    B --> C["Load Extraction Rules"]
    C --> D["Parser"]
    D --> DI["Document Ingestion"]
    DI --> E["Response Item Extractor"]
    E --> EN["Response Item Normalizer"]
    EN --> F["Proposal Classification"]
    F --> FR["Reviewer + Debug + Re-review"]
    FR --> RS["Response Strategy"]
    RS --> G["Load Enterprise Knowledge"]
    G --> GP["Knowledge Permission Filter"]
    GP --> H["Knowledge Matching"]
    FR --> PM["Proposal Memory Matching"]
    H --> I["Load Proposal Writing Rules"]
    PM --> I
    I --> J["Proposal Planner"]
    J --> K["Chapter Writer"]
    K --> L["Chapter Review"]
    L --> M["人工编辑与确认"]
    M -->|下一章| K
    M -->|全部确认| PR["Full Proposal Review"]
    PR --> DG["Delivery Gate"]
    DG --> N["Full DOCX Export"]
```

`workflow_runs.stage_trace` 保存有限阶段轨迹。流程代码只能调用表中定义的阶段，
没有 Agent 自由对话、自治工具选择或无限循环。

所有模型节点在调用前通过 `model_usage_events` 预留工作流预算。预算检查使用事务
级锁防止并发穿透；超限立即停止模型调用并保留断点。Review 和 Debug 固定为一次
审查、一次安全机械修复、一次确定性复检。

## 3. Rule Engine

默认配置位于 `config/rules/`，数据库中的激活规则可覆盖默认配置。Rule Engine
负责：

- 规则结构校验；
- 草稿、激活和退役；
- 单类型唯一激活版本；
- Git 默认版本与数据库定制版本的统一加载；
- 校验和与不可变运行快照；
- 为未来 `ai_generated` 规则保留来源字段，但 AI 生成版本必须先进入草稿。

规则类型：

| 类型 | 控制内容 |
| --- | --- |
| extraction | 文件有效性、候选证据、忽略项、Requirement 定义和命名 |
| classification | Requirement 类型、评分关系、方案章节映射、行业分类约束 |
| response_strategy | 响应动作、评分影响、风险优先级和技术正文映射 |
| proposal_memory | 优秀方案结构模式的准入、用途和事实禁用边界 |
| writing | 目录顺序、章节风格、事实边界、知识引用、篇幅、重复率和术语策略 |
| compliance | 长度、禁用表述、占位符、Requirement/Knowledge 可追溯门禁 |

模型收到的是“当前规则版本内容 + 本阶段数据”，而不是代码中的永久超长 Prompt。

## 4. Knowledge Engine

Enterprise Knowledge 只保存机构有权使用的私有知识：

- company_profile
- qualification
- product_capability
- technical_capability
- case_study
- standard_template
- expert_experience
- historical_bid
- common_chapter

Knowledge Permission Filter 先按 `organization_key` 和 permission scope 在
SQL 查询层过滤，禁止先加载其他机构知识再做内存删除。Knowledge Matching 在
Chapter Writer 之前完成。匹配输入是章节标题和映射
Requirements；输出是按相关度排序的明确知识集合。`knowledge_matches` 保存知识、
章节、Requirement、分数和理由；`section_versions.knowledge_snapshot` 固化生成时
使用的知识。

没有匹配知识并不会让 Writer 自由搜索。凡涉及企业事实，必须输出待补充占位符。

## 5. Proposal Memory

Proposal Memory 与 Enterprise Knowledge 分离。Knowledge 证明企业真实具备什么；
Memory 只提供优秀方案的章节结构、分析维度、写作方法和图表模式。所有 Memory
必须经过审核、限定机构权限并明确 `prohibited_fact_copy=true`。Writer 不得用
Memory 证明企业资质、能力、案例、人员或任何历史事实。

历史招标文件只有通过有效性、解析质量、SHA-256 重复性和机构权限检查后才成为
`historical_bid`，范围固定为 `organization_private`，仅用于后续私有 RAG。

## 6. 业务数据

| 实体 | 核心职责 |
| --- | --- |
| projects | 内部 workspace；新前端不向用户暴露“项目”概念 |
| documents / source_chunks | 文件、有效性、私有知识资格和页码/段落证据 |
| requirements | 规范化要求及 proposal_relevance、target_chapter、need_generation |
| requirement_sources | Requirement 到原文证据的多对多映射 |
| requirement_normalization_events | 响应事项标准化、拆分和合并审计轨迹 |
| sections / section_requirements | 推荐目录及 Requirement 到章节的映射 |
| section_versions | 生成/人工版本、规则快照、知识快照和输入快照 |
| review_findings | 版本化合规校核结果 |
| rule_definitions | 可编辑、可激活、可审计的规则版本 |
| enterprise_knowledge | 机构私有企业知识 |
| knowledge_matches | 写作前知识匹配证据 |
| proposal_memory | 审核通过的优秀方案结构模式，不保存可复用企业事实 |
| workflow_runs | 有限工作流轨迹和失败位置 |
| export_records | 单章节兼容导出与整本方案导出 |

## 7. 模块边界

- Document Validator：只判断输入是否值得进入后续流程。
- Parser：只把 PDF/DOCX 转为可定位 SourceSegment。
- Document Ingestion：持久化原文、页码、段落、表格位置和来源坐标。
- Requirement Extractor：依据加载的 extraction rule 调用模型。
- Response Item Normalizer：确定性拆分复合事项、标准化表达并保存审计记录。
- Classification Agent：规则优先；只对低置信和未映射条目进行一次批量模型分类。
- Classification Reviewer：纠正分类冲突，确保资格和商务条款不进入技术方案正文。
- Response Strategy：回答如何响应、写在哪里和有什么风险，并接受人工双向归类。
- Output Review / Debug：检查内部标识、无意义标签和缺失映射，只做安全机械修复并复检一次。
- Knowledge Permission Filter：在查询知识内容前按机构和 scope 默认拒绝越权。
- Knowledge Matching：加载当前机构私有知识并匹配，不写正文。
- Proposal Memory：只提供审核后的结构和写法模式，禁止作为事实来源。
- Proposal Planner：按 writing rule 和映射生成有序目录。
- Chapter Writer：只用 Requirement 证据、Matched Knowledge 和 writing rule。
- Chapter Review：每章生成后立即检查覆盖、来源、幻觉、格式和内部标识。
- Delivery Gate：整本 Review 后检查真实性、可追溯、评分覆盖和交付风险。
- Export：按确认版本顺序生成完整 DOCX 和来源总表。

## 8. 安全与演进

- 密钥仅从环境读取，规则、知识快照和日志均不得保存密钥。
- 机构私有知识不进入公共训练集，产品文案不得称为“模型训练”。
- 当前部署仍使用默认机构，但项目和知识查询已携带 organization context。正式
  多租户开放前还需增加真实身份认证、数据库行级策略和对象存储签名 URL。
- AI 自动优化规则只能生成新草稿，必须经过专家差异审查和离线样本回归后激活。
- 向量检索可替换当前确定性初筛，但 Knowledge Matching 的显式前置阶段和快照
  不能被移除。

## 9. 跨项目复用边界

主流程、数据库实体和模块接口属于稳定层，不因招标项目变化。可变内容统一放在
`config/rules/`，需要企业定制时创建新的规则版本，不复制 Agent 或 Service。

| 可变内容 | 配置位置 | 消费模块 |
| --- | --- | --- |
| 有效招标文件判定、候选词、忽略项 | `extraction.document_validation`、`candidate_markers`、`ignore_*` | Document Validator、Requirement Extractor |
| Requirement 类型、评分关系和章节路由 | `classification.requirement_types`、`classifiers`、`chapter_mapping` | Classification Agent、Classification Reviewer |
| 响应动作、评分影响、优先级和人工归类 | `response_strategy.hard_rules`、`type_defaults`、`priority_policy` | Response Strategy、Proposal Planner |
| 推荐目录与章节风格 | `writing.chapter_order`、`chapter_styles` | Proposal Planner、Chapter Writer |
| 事实边界、篇幅和写作约束 | `writing.policies`、`knowledge_category_policy` | Chapter Writer |
| 知识准入、匹配权重和数量 | `knowledge.eligibility`、`matching`、`fact_boundaries` | Knowledge Engine |
| 优秀结构模式和事实禁用边界 | `proposal_memory.eligibility`、`usage` | Proposal Memory Engine |
| 校核项、严重级别和可追溯要求 | `compliance.checks`、`required_traceability` | Compliance Checker |
| 模型、端点、批次和切分参数 | 私密 `.env`；字段模板见 `.env.example` | Model Gateway、Ingestion |

以下内容保持稳定，不进入项目规则：上传与会话安全、任务状态、失败重试、阶段轨迹、
来源快照、人工确认和 DOCX 交付。这样更换项目时只激活一组经过测试的规则版本，
无需重新组装工作流。
