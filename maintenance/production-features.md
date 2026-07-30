# Production feature maintenance

## Feature inventory

| id | feature | status | criticality | owner | production_target | repo_path | health_signals | success_criteria | runbook | check_frequency | last_check | next_check | check_result | evidence | known_risks |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| PF-001 | 招标文件理解与方案分类 | active | critical | bid-agent | http://101.200.154.141 | `app/agents/requirement_classifier.py`, `config/rules/classification.default.json` | 分类质量、冲突、无章节映射、人工反馈 | 咨询类要求不因孤立的软件词汇误入系统功能章节；方案事项均有合理章节或进入合规提醒 | `README.md` 生产验收章节 | release | 2026-07-31 | 下次发布 | healthy | 天津规划咨询项目 6 条软件误分类已归入服务范围；系统功能误分 0、无章节映射 0、内部标识 0 | 持续收集人工分类反馈 |
| PF-002 | 章节生成与模型路由 | active | critical | bid-agent | http://101.200.154.141 | `app/core/model_client.py`, `app/core/model_routing.py`, `app/services/section_service.py` | 章节任务状态、模型使用审计、HTTP 5xx | 一个真实章节生成成功；不可用模型被冷却；输入保持在模型限制内；尝试次数和费用受控 | `README.md` 模型路由章节 | release | 2026-07-31 | 下次发布 | healthy | 天津项目真实失败章节由 qwen-max 成功生成 2,298 字，0 条章节校核问题，工作流成功 | 继续监控不同模型不可用时的有界降级 |

Allowed feature statuses: `discovery`, `active`, `degraded`, `maintenance`, `retired`.

## Incident and feedback queue

| id | opened_at | feature_id | source | severity | symptom | affected_scope | reproduction | status | root_cause_or_hypothesis | fix | verification | owner | next_action | updated_at |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| INC-001 | 2026-07-31 03:53 CST | PF-002 | 用户反馈与生产日志 | sev2 | “章节生成失败，请检查模型配置或稍后重试” | 天津轨道交通方案至少 3 个章节 | 点击生成章节；生产连续返回 502 | closed | `qwen3.7-plus`、`qwen-plus-2025-07-28` 无权限；`qwen-max` 输入超过 30720 | 已实现 10 模型池、高级模型优先、零消耗失败冷却、计费失败上限和 24,000 字符 Prompt 预算 | 生产真实失败章节由 qwen-max 一次成功，2,298 字，0 条校核问题；本地 164 项测试通过 | codex | 按发布周期持续监控 | 2026-07-31 |
| INC-002 | 2026-07-31 03:53 CST | PF-001 | 用户反馈与分类汇总 | sev3 | 规划咨询项目分类不符合方案编写逻辑 | 最新天津轨道交通项目 | 查看响应事项分类汇总 | closed | 分类器缺少项目上下文，且 Reviewer 未强制纠正高置信模型的软件类误判 | 已增加咨询项目上下文覆盖和 Reviewer 确定性纠正；原位重分类同步未生成目录 | 83 条真实响应事项重分类；6 条误分全部纠正，系统功能误分 0、无章节映射 0；10 章整本生成导出成功 | codex | 按发布周期持续监控 | 2026-07-31 |

Allowed incident statuses: `new`, `triaging`, `confirmed`, `fixing`, `monitoring`, `blocked`, `deferred`, `closed`.

## Run log

| run_at | trigger | overall_health | checked_items | incidents_changed | fixes | evidence | blockers | next_action |
|---|---|---|---|---|---|---|---|---|
| 2026-07-31 03:53 CST | 用户报告章节失败与分类异常 | incident | PF-001, PF-002 | INC-001、INC-002 opened | none | 4 个章节任务失败；模型审计显示 403/403/400；分类汇总显示 6 条系统功能设计 | none | 实施最小修复并完成真实回测 |
| 2026-07-31 04:10 CST | 修复前发布门禁 | degraded | PF-001, PF-002 | INC-001、INC-002 fixing | 10 模型池、健康冷却、费用边界、Prompt 预算、咨询上下文分类 | 161 项后端测试通过；前端构建、Docker 配置、敏感信息检查通过 | 生产尚未回测 | 部署并重试失败章节 |
| 2026-07-31 04:31 CST | 用户授权真实回测与 MVP 发布 | degraded | PF-001, PF-002 | INC-001 closed；INC-002 fixing | 高级模型优先；移除上传阶段重复知识匹配；交付审查与 Word 导出合并；工作台要求查询合并 | qwen-max 真实生成 2,298 字且 0 条校核问题；164 项后端测试和前端测试通过 | 旧项目分类尚待原位更新 | 重分类后生成剩余章节并验证 Word 导出 |
| 2026-07-31 05:10 CST | 用户授权整本项目与企业知识验收 | healthy | PF-001, PF-002 | INC-002 closed | Reviewer 上下文强制纠正；未生成目录原位同步；受控整本验收脚本 | 10/10 章全部确认，共 15,321 字；qwen-max 12 次成功、82,322 Token；整本 Review 可交付、阻断风险 0、内部标识 0、追溯率 100%；Word 29 页导出成功 | LibreOffice 本机预览缺少中文字体，结构检查确认 DOCX 中文字符完整 | 发布正式 MVP 标签并持续监控 |
