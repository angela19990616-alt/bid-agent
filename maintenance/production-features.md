# Production feature maintenance

## Feature inventory

| id | feature | status | criticality | owner | production_target | repo_path | health_signals | success_criteria | runbook | check_frequency | last_check | next_check | check_result | evidence | known_risks |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| PF-001 | 招标文件理解与方案分类 | active | critical | bid-agent | http://101.200.154.141 | `app/agents/requirement_classifier.py`, `app/services/conflict_service.py`, `config/rules/classification.default.json` | 分类质量、冲突、无章节映射、人工反馈 | 咨询类要求不因孤立的软件词汇误入系统功能章节；真实冲突保留双来源并由人工决策；方案事项通过三重门禁 | `README.md` 生产验收章节 | release | 2026-07-31 | 下次发布 | healthy | ECS `b7a29f94`；真实样例抽取 83 条响应事项、形成 4 章，冲突误报 0 | 持续用真实文件回测冲突误报率 |
| PF-002 | 章节生成与模型路由 | active | critical | bid-agent | http://101.200.154.141 | `app/core/model_client.py`, `app/core/model_routing.py`, `app/services/section_service.py` | 章节任务状态、模型使用审计、HTTP 5xx | 一个真实章节生成成功；不可用模型被冷却；输入保持在模型限制内；尝试次数和费用受控 | `README.md` 模型路由章节 | release | 2026-07-31 | 下次发布 | healthy | 真实样例 4/4 章通过章节校核，共 6,910 字；整本 Review 可交付、覆盖率 100%、阻断问题 0，Word 导出成功 | 继续监控不同模型不可用时的有界降级 |

Allowed feature statuses: `discovery`, `active`, `degraded`, `maintenance`, `retired`.

## Incident and feedback queue

| id | opened_at | feature_id | source | severity | symptom | affected_scope | reproduction | status | root_cause_or_hypothesis | fix | verification | owner | next_action | updated_at |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| INC-001 | 2026-07-31 03:53 CST | PF-002 | 用户反馈与生产日志 | sev2 | “章节生成失败，请检查模型配置或稍后重试” | 天津轨道交通方案至少 3 个章节 | 点击生成章节；生产连续返回 502 | closed | `qwen3.7-plus`、`qwen-plus-2025-07-28` 无权限；`qwen-max` 输入超过 30720 | 已实现 10 模型池、高级模型优先、零消耗失败冷却、计费失败上限和 24,000 字符 Prompt 预算 | 生产真实失败章节由 qwen-max 一次成功，2,298 字，0 条校核问题；本地 164 项测试通过 | codex | 按发布周期持续监控 | 2026-07-31 |
| INC-002 | 2026-07-31 03:53 CST | PF-001 | 用户反馈与分类汇总 | sev3 | 规划咨询项目分类不符合方案编写逻辑 | 最新天津轨道交通项目 | 查看响应事项分类汇总 | closed | 分类器缺少项目上下文，且 Reviewer 未强制纠正高置信模型的软件类误判 | 已增加咨询项目上下文覆盖和 Reviewer 确定性纠正；原位重分类同步未生成目录 | 83 条真实响应事项重分类；6 条误分全部纠正，系统功能误分 0、无章节映射 0；10 章整本生成导出成功 | codex | 按发布周期持续监控 | 2026-07-31 |
| INC-003 | 2026-07-31 | PF-001 | 用户反馈 | sev3 | 已忽略事项恢复“写入方案”后未回到推荐目录 | 人工确认与目录同步 | 先忽略一条方案事项，再恢复写入 | closed | 人工反馈只恢复 Requirement 状态，未重建草稿章节关联，前端也未刷新目录 | 增加草稿目录双向同步；忽略时移除关联，恢复时按方案章节重新关联并刷新前端 | 后端 179 项测试、前端构建及 2 项页面测试通过 | codex | 随下一次生产发布回测 | 2026-07-31 |
| INC-004 | 2026-07-31 | PF-001, PF-002 | 用户反馈 | sev3 | 最新输出再次出现 `###` 且 Requirement 分类错误 | 最新生产方案 | 查看最新生成章节及响应事项 | monitoring | 分类器与响应动作直接耦合，缺少独立 Response Strategy；写作规则禁止 Markdown 但保存前未强制清除标题标记 | 新增规则驱动的 Response Strategy、五类响应视图、人工双向归类和 `###` 保存门禁 | 后端 188 项、前端与发布门禁通过；ECS `f752ddd5`、迁移 021、公网健康和邀请码保护正常 | codex | 等待用户真实文件试用反馈 | 2026-07-31 |
| INC-005 | 2026-07-31 17:20 CST | PF-001 | 用户公网实测 | sev2 | 上传处理失败：未知工作流阶段 `response_strategy_analysis`；修复后大批抽取遇模型超时 | 新上传招标文件的 Requirement 分析 | 公网上传并等待后台处理 | closed | 新增阶段未同步加入工作流白名单；模型超时异常未进入小批次恢复路径 | 注册固定阶段；抽取失败按可恢复小批次拆分并保留检查点，避免整单重跑 | 196 项测试及发布门禁通过；ECS `b7a29f94`；真实样例完成 83 条抽取、4/4 章生成校核、整本 Review 和 Word 导出 | codex | 按发布周期持续监控 | 2026-07-31 |

Allowed incident statuses: `new`, `triaging`, `confirmed`, `fixing`, `monitoring`, `blocked`, `deferred`, `closed`.

## Run log

| run_at | trigger | overall_health | checked_items | incidents_changed | fixes | evidence | blockers | next_action |
|---|---|---|---|---|---|---|---|---|
| 2026-07-31 03:53 CST | 用户报告章节失败与分类异常 | incident | PF-001, PF-002 | INC-001、INC-002 opened | none | 4 个章节任务失败；模型审计显示 403/403/400；分类汇总显示 6 条系统功能设计 | none | 实施最小修复并完成真实回测 |
| 2026-07-31 04:10 CST | 修复前发布门禁 | degraded | PF-001, PF-002 | INC-001、INC-002 fixing | 10 模型池、健康冷却、费用边界、Prompt 预算、咨询上下文分类 | 161 项后端测试通过；前端构建、Docker 配置、敏感信息检查通过 | 生产尚未回测 | 部署并重试失败章节 |
| 2026-07-31 04:31 CST | 用户授权真实回测与 MVP 发布 | degraded | PF-001, PF-002 | INC-001 closed；INC-002 fixing | 高级模型优先；移除上传阶段重复知识匹配；交付审查与 Word 导出合并；工作台要求查询合并 | qwen-max 真实生成 2,298 字且 0 条校核问题；164 项后端测试和前端测试通过 | 旧项目分类尚待原位更新 | 重分类后生成剩余章节并验证 Word 导出 |
| 2026-07-31 05:10 CST | 用户授权整本项目与企业知识验收 | healthy | PF-001, PF-002 | INC-002 closed | Reviewer 上下文强制纠正；未生成目录原位同步；受控整本验收脚本 | 10/10 章全部确认，共 15,321 字；qwen-max 12 次成功、82,322 Token；整本 Review 可交付、阻断风险 0、内部标识 0、追溯率 100%；Word 29 页导出成功 | LibreOffice 本机预览缺少中文字体，结构检查确认 DOCX 中文字符完整 | 发布正式 MVP 标签并持续监控 |
| 2026-07-31 | 人工反馈双向同步回归 | healthy | PF-001 | INC-003 closed | 恢复写入时重建草稿目录关联，忽略时移除关联，前端即时刷新目录 | 后端 179 项测试通过；前端生产构建和 2 项页面测试通过；ECS 提交 `2475c763` 健康，公网首页及访问控制正常 | none | 持续收集人工反馈 |
| 2026-07-31 | 用户报告最新输出格式与分类异常 | incident | PF-001, PF-002 | INC-004 opened | none | 待查询最新模型使用事件、章节内容和分类结果 | none | 只读取证并定位根因 |
| 2026-07-31 | Response Strategy 最小增量修复 | degraded | PF-001, PF-002 | INC-004 fixing | 分类与响应动作解耦；Planner 只读写入方案事项；人工归类同步目录；保存前清除 Markdown 标题标记 | 4 个指定策略案例通过；后端 188 项、前端 2 项及完整发布门禁通过 | 尚未部署 ECS | 提交并在获授权后部署真实回测 |
| 2026-07-31 | Response Strategy 测试公网发布 | healthy | PF-001, PF-002 | INC-004 monitoring | 部署 `f752ddd5` 并应用迁移 021 | 公网首页 200、健康接口正常、邀请码保护开启、容器无新增错误 | none | 等待用户真实文件试用 |
| 2026-07-31 | 冲突检测与响应价值治理开发 | maintenance | PF-001, PF-002 | none | 新增来源分组、四类差异、版本化人工决策、风险/价值双排序和章节级暂停 | 后端全量测试、前端测试与构建通过 | 尚未应用生产迁移 022 | 完成发布门禁后提交，部署需生产授权 |
| 2026-07-31 | 用户授权冲突检测与响应价值治理发布 | healthy | PF-001, PF-002 | none | 部署 `f46aa736` 并应用迁移 022 | 公网首页与健康接口正常；邀请码保护开启；冲突 API 注册；容器无新增错误 | none | 等待真实招标文件试用反馈 |
| 2026-07-31 | 用户授权真实样例全流程回归 | healthy | PF-001, PF-002 | INC-005 closed | 注册 Response Strategy 阶段；模型超时自动拆分小批次并从检查点续跑 | 196 项测试和完整发布门禁通过；83 条响应事项、4/4 章共 6,910 字、章节问题 0；整本 Review 可交付、覆盖率 100%、阻断问题 0；Word 导出成功 | none | 按发布周期持续监控真实文件成功率和时延 |
