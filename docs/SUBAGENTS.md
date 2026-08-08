# Bid Agent 项目子智能体

子智能体配置位于 `.codex/agents/`，供 Codex Desktop、CLI 和 IDE 在任务适合并行分析时按需调用。

| Agent | 主要职责 | 默认权限 |
|---|---|---|
| `ops_maintainer` | 服务、Worker、队列、日志、资源和故障巡检 | 只读 |
| `code_reviewer` | 正确性、并发、事务、回归和可维护性审查 | 只读 |
| `test_engineer` | 单元、API、集成、DOCX 和页面回归 | 只读 |
| `security_privacy_reviewer` | 权限、隔离、脱敏、密钥和企业数据审查 | 只读 |
| `bid_quality_reviewer` | 格式、Requirement、采分点、证据和交付真实性 | 只读 |
| `frontend_ux_reviewer` | 用户流程、等待反馈、错误恢复和隐私体验 | 只读 |
| `release_auditor` | Git、迁移、Docker、测试、部署证据和回滚门禁 | 只读 |

## 调用示例

```text
这次发布前，请让 code_reviewer 审查代码风险，
test_engineer 核对回归证据，release_auditor 给出 GO/NO-GO。
等待三个 Agent 都完成后统一汇总。
```

```text
请让 ops_maintainer 只读定位公网 502，
security_privacy_reviewer 同时检查是否存在访问边界风险。
不要重启或修改生产。
```

```text
请让 bid_quality_reviewer 审查格式保真、采分点和企业事实，
frontend_ux_reviewer 检查业务人员是否能顺利完成全流程。
```

## 成本控制

- 默认最多并行 4 个子智能体。
- 普通任务选择 1-3 个最相关角色，不运行全员审查。
- 快速巡检使用 `gpt-5.6-terra`；只有代码、安全和投标质量深度审查使用 `gpt-5.6-sol`。
- 专业 Agent 默认只读，由主 Agent 集中实施修改，减少重复读取和并行编辑冲突。

