# Production feature maintenance

## Feature inventory

| id | feature | status | criticality | owner | production_target | repo_path | health_signals | success_criteria | runbook | check_frequency | last_check | next_check | check_result | evidence | known_risks |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| PF-001 | 招标文件理解与方案分类 | active | critical | bid-agent | http://101.200.154.141 | `app/agents/requirement_classifier.py`, `app/services/conflict_service.py`, `config/rules/classification.default.json` | 分类质量、冲突、无章节映射、人工反馈 | 咨询类要求不因孤立的软件词汇误入系统功能章节；真实冲突保留双来源并由人工决策；方案事项通过三重门禁 | `README.md` 生产验收章节 | release | 2026-07-31 | 下次发布 | healthy | ECS `b7a29f94`；真实样例抽取 83 条响应事项、形成 4 章，冲突误报 0 | 持续用真实文件回测冲突误报率 |
| PF-002 | 章节生成与模型路由 | active | critical | bid-agent | http://101.200.154.141 | `app/core/model_client.py`, `app/core/model_routing.py`, `app/services/section_service.py` | 章节任务状态、模型使用审计、HTTP 5xx | 一个真实章节生成成功；不可用模型被冷却；输入保持在模型限制内；尝试次数和费用受控 | `README.md` 模型路由章节 | release | 2026-07-31 | 下次发布 | healthy | ECS `e10c2637`；DeepSeek V4 Flash 抽取与 V4 Pro 写作生产真实调用成功，公网健康 | 继续监控实际全文件处理时延和有界降级 |
| PF-003 | 私有使用统计后台 | active | medium | bid-agent | SSH 隧道至 `127.0.0.1:8000/internal/usage` | `app/api/internal_dashboard.py`, `app/services/usage_dashboard_service.py` | 页面可访问、聚合查询成功、仅回环端口、前端无入口 | 仅管理员通过 SSH 隧道访问；展示使用量、成功率和模型消耗；不展示文件名、项目名、用户标识、UUID、原文或密钥 | `README.md` 后台使用统计章节 | release | 2026-08-03 | 下次发布 | healthy | ECS `180f1b23`；后台查询 200，公网 8000 超时不可达，官网 200，5 容器健康 | SSH 隧道依赖管理员本机连接保持在线 |
| PF-004 | 聚合响应、格式资格与溯源审核 | discovery | high | bid-agent | 本地 `http://127.0.0.1/` | `app/services/response_support_service.py`, `app/services/response_template_service.py`, `app/memory/historical_case_learning.py`, `frontend/app/page.tsx` | 同类分组、模板决策、格式清单、资格匹配、案例模式、审核地图 | DOCX 模板优先并保留原包版式；底层细粒度不丢失；未核验资格不进入响应；历史案例不复制事实 | `README.md` 模板优先生成 | local acceptance | 2026-08-06 | 全量回归后 | maintenance | 仓库自贡招标文件正确定位真实第七章而非目录，原包裁剪、项目字段与技术方案回填成功；结构隔离聚焦测试通过 | 非可填写 PDF 仍需人工坐标级回填；当前仓库仅有一组案例，尚缺用户所述其余四组 |

Allowed feature statuses: `discovery`, `active`, `degraded`, `maintenance`, `retired`.

## Incident and feedback queue

| id | opened_at | feature_id | source | severity | symptom | affected_scope | reproduction | status | root_cause_or_hypothesis | fix | verification | owner | next_action | updated_at |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| INC-001 | 2026-07-31 03:53 CST | PF-002 | 用户反馈与生产日志 | sev2 | “章节生成失败，请检查模型配置或稍后重试” | 天津轨道交通方案至少 3 个章节 | 点击生成章节；生产连续返回 502 | closed | `qwen3.7-plus`、`qwen-plus-2025-07-28` 无权限；`qwen-max` 输入超过 30720 | 已实现 10 模型池、高级模型优先、零消耗失败冷却、计费失败上限和 24,000 字符 Prompt 预算 | 生产真实失败章节由 qwen-max 一次成功，2,298 字，0 条校核问题；本地 164 项测试通过 | codex | 按发布周期持续监控 | 2026-07-31 |
| INC-002 | 2026-07-31 03:53 CST | PF-001 | 用户反馈与分类汇总 | sev3 | 规划咨询项目分类不符合方案编写逻辑 | 最新天津轨道交通项目 | 查看响应事项分类汇总 | closed | 分类器缺少项目上下文，且 Reviewer 未强制纠正高置信模型的软件类误判 | 已增加咨询项目上下文覆盖和 Reviewer 确定性纠正；原位重分类同步未生成目录 | 83 条真实响应事项重分类；6 条误分全部纠正，系统功能误分 0、无章节映射 0；10 章整本生成导出成功 | codex | 按发布周期持续监控 | 2026-07-31 |
| INC-003 | 2026-07-31 | PF-001 | 用户反馈 | sev3 | 已忽略事项恢复“写入方案”后未回到推荐目录 | 人工确认与目录同步 | 先忽略一条方案事项，再恢复写入 | closed | 人工反馈只恢复 Requirement 状态，未重建草稿章节关联，前端也未刷新目录 | 增加草稿目录双向同步；忽略时移除关联，恢复时按方案章节重新关联并刷新前端 | 后端 179 项测试、前端构建及 2 项页面测试通过 | codex | 随下一次生产发布回测 | 2026-07-31 |
| INC-004 | 2026-07-31 | PF-001, PF-002 | 用户反馈 | sev3 | 最新输出再次出现 `###` 且 Requirement 分类错误 | 最新生产方案 | 查看最新生成章节及响应事项 | monitoring | 分类器与响应动作直接耦合，缺少独立 Response Strategy；写作规则禁止 Markdown 但保存前未强制清除标题标记 | 新增规则驱动的 Response Strategy、五类响应视图、人工双向归类和 `###` 保存门禁 | 后端 188 项、前端与发布门禁通过；ECS `f752ddd5`、迁移 021、公网健康和邀请码保护正常 | codex | 等待用户真实文件试用反馈 | 2026-07-31 |
| INC-005 | 2026-07-31 17:20 CST | PF-001 | 用户公网实测 | sev2 | 上传处理失败与后续进度轮询 500 | 新上传招标文件的 Requirement 分析 | 公网上传并等待后台处理 | closed | 工作流阶段遗漏；模型超时未进入小批恢复；Workspace 消费了内部字段名而非 API 字段 `type` | 注册固定阶段；小批恢复；统一 Workspace 字段契约并正确结束目录工作流 | 199 项测试及发布门禁通过；全新 DeepSeek 样例 113 条、5/5 章、整本 Review 和 Word 导出成功 | codex | 按发布周期持续监控 | 2026-07-31 |

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
| 2026-07-31 | DeepSeek V4 生产发布 | healthy | PF-002 | none | 抽取/分类优先 V4 Flash 且关闭思考；写作/终审优先 V4 Pro 且开启思考；百炼有界备用 | 196 项测试与完整门禁通过；生产两类真实 API 调用成功；5 容器健康，公网首页 200 | none | 用下一份真实招标文件观察端到端耗时 |
| 2026-07-31 | Workspace 500 修复与全新整本回归 | healthy | PF-001, PF-002 | INC-005 closed | 修复字段契约、工作流收尾和误导性网络提示；增加模型边界本地隐私脱敏 | 全新样例 241 秒完成 113 条与 5 章目录；5/5 章共 8,246 字，整本 Review 覆盖率 100%、阻断 0、内部标识 0；Word 导出成功；199 项测试通过；ECS `60da6037` 脱敏与本地恢复真实调用成功 | none | 持续监控分类质量、时延和隐私规则误报 |
| 2026-07-31 | V3.0.0 正式发布 | healthy | PF-001, PF-002 | none | 固化 Git 标签 `v3.0.0`，统一前后端版本并部署 `676b6f0c` | 199 项测试与发布门禁通过；生产应用报告 3.0.0；5 容器健康；公网首页 200、邀请码保护开启 | none | 仅按用户反馈进行最小前端体验优化 |
| 2026-08-03 | 私有使用统计后台开发 | maintenance | PF-003 | none | 增加只读聚合统计页、SSH 隧道访问和回环端口约束 | 202 项后端测试、前端生产构建、Docker 配置与完整发布门禁通过 | 尚未部署生产 | 提交 Git；部署需生产授权 |
| 2026-08-03 | 私有使用统计后台发布 | healthy | PF-003 | none | 部署 `180f1b23`，后端仅绑定 `127.0.0.1:8000`，建立管理员 SSH 隧道 | 私有页 200；公网 8000 不可达；公网首页 200；5 容器健康；数据库备份 `postgres-20260803T030854Z.sql` | none | 随发布周期复查聚合查询与访问边界 |
| 2026-08-06 | 下一阶段响应支持本地验收版 | healthy | PF-004 | none | 同类事项折叠聚合、格式清单、资格材料匹配、四种案例参考模式和采购原文审核地图 | 205 项后端、2 项前端、完整门禁通过；本地 5 容器健康 | 二进制模板回填与证书图片编排待下一增量 | 用户本地确认后再决定是否继续和部署 |
| 2026-08-06 | 模板优先生成开发 | healthy | PF-004 | none | 增加 DOCX/PDF 模板检测、目录误命中过滤、原包裁剪回填、已核验字段入口、导出门禁、生成模式档案和中标案例结构隔离学习 | 后端全量 214 项、前端干净依赖生产构建、Docker Compose、架构与静态检查通过；真实自贡文件定位第七章第 359 区块，3 个必填字段正确识别并完成 32 页逐页回填审计 | 仓库当前仅有一组案例（两个响应分册），其余四组案例文件尚未提供；PDF 坐标级回填仍保持人工门禁 | 提交 Git，不部署生产；文件补齐后通过机构私有接口逐组导入 |
| 2026-08-06 | 五组案例批量导入门禁 | healthy | PF-004 | none | 增加清单驱动的完整批次校验、目录边界、重复检查、结构隔离 dry-run 和全批单事务写入 | 8 项案例学习与批量导入测试、pyflakes 和 CLI 帮助检查通过 | 尚缺四组真实招标与中标响应文件，未执行正式五组写库 | 文件补齐后先 dry-run，再在本地数据库执行正式导入与相似匹配回归 |
| 2026-08-06 | 单组真实案例启用与本地部署 | healthy | PF-004 | none | 采用自贡招标文件与“响应文件其他文件”作为一组方案结构案例；资格分册不参与正文写法；应用迁移 023 并重建本地 backend、worker、frontend | dry-run 识别 49 个结构模式；正式写入 49 个唯一机构私有记录，事实禁用与来源事实移除标志全真；真实章节查询命中 2 项；前端 200、后端/数据库/Redis 健康且启动日志无错误 | 当前仅一组案例，相似性覆盖有限；未部署生产 | 先本地使用并收集效果，后续案例到位再增量导入 |
