# Bid Agent MVP API

## 1. 约定

- 基础路径：`/api/v1`
- 数据格式：JSON；文件上传使用 `multipart/form-data`
- ID：UUID 字符串
- 时间：UTC ISO 8601
- 列表默认按更新时间倒序
- 耗时操作返回任务 ID，由前端轮询任务状态
- 创建任务类接口支持 `Idempotency-Key` 请求头

统一错误：

```json
{
  "error": {
    "code": "DOCUMENT_PARSE_FAILED",
    "message": "文件无法解析，请确认文件未损坏且包含可检索文本。",
    "request_id": "uuid",
    "details": {}
  }
}
```

错误响应不得包含密钥、内部路径、完整文件正文或模型原始请求。

## 2. 项目

### `POST /projects`

创建项目。

请求：

```json
{
  "name": "某项目技术标"
}
```

返回 `201`：项目对象。

### `GET /projects`

返回项目摘要列表。

### `GET /projects/{project_id}`

返回项目详情、当前阶段和各类资源数量。

## 3. 文件

### `POST /projects/{project_id}/documents`

上传 PDF 或 DOCX。字段名为 `file`，服务端校验扩展名、MIME、大小和文件签名。

返回 `202`：

```json
{
  "document": {
    "id": "uuid",
    "filename": "招标文件.pdf",
    "status": "uploaded"
  },
  "job_id": "uuid"
}
```

### `GET /projects/{project_id}/documents`

返回项目文件及解析状态。

### `GET /projects/{project_id}/documents/{document_id}`

返回文件元数据、解析进度和错误；不返回服务器真实路径。

### `POST /projects/{project_id}/documents/{document_id}/parse`

对解析失败的文件重新发起解析，返回 `202` 和新任务 ID。

## 4. 来源片段

### `GET /projects/{project_id}/sources/{source_chunk_id}`

返回用于回看的原文片段：

```json
{
  "id": "uuid",
  "document_id": "uuid",
  "filename": "招标文件.pdf",
  "locator": {
    "kind": "page",
    "page": 12
  },
  "text": "原文片段"
}
```

DOCX 的 `locator.kind` 为 `paragraph`，并返回起止段落序号。

## 5. 要求

### `POST /projects/{project_id}/requirements/extract`

从已解析文件提取候选要求。

请求：

```json
{
  "document_ids": ["uuid"]
}
```

返回 `202` 和任务 ID。

### `GET /projects/{project_id}/requirements`

可按 `status`、`type` 和 `document_id` 过滤。每项返回来源摘要。

### `PATCH /projects/{project_id}/requirements/{requirement_id}`

编辑要求或改变确认状态。

请求示例：

```json
{
  "title": "项目实施计划",
  "normalized_text": "方案需包含明确的项目实施计划。",
  "type": "scoring",
  "status": "confirmed"
}
```

确认前服务端必须验证至少存在一个有效来源。

### `DELETE /projects/{project_id}/requirements/{requirement_id}`

软删除，状态变为 `rejected`，返回 `204`。

## 6. 章节

### `POST /projects/{project_id}/sections`

创建待生成章节。

请求：

```json
{
  "title": "项目实施方案",
  "requirement_ids": ["uuid", "uuid"]
}
```

只接受属于当前项目且状态为 `confirmed` 的要求。

### `POST /projects/{project_id}/sections/{section_id}/generate`

生成或重试生成章节，返回 `202` 和任务 ID。输入要求及来源保存为不可变快照。

### `GET /projects/{project_id}/sections/{section_id}`

返回章节、当前版本、关联要求和校核摘要。

### `PUT /projects/{project_id}/sections/{section_id}/content`

保存人工编辑版本。

请求：

```json
{
  "base_version_id": "uuid",
  "content": "编辑后的章节正文"
}
```

当基础版本不是最新版本时返回 `409 SECTION_VERSION_CONFLICT`，避免覆盖他人修改。

### `POST /projects/{project_id}/sections/{section_id}/approve`

将当前版本标记为已确认；存在阻断级校核问题时返回 `409`。

## 7. 导出

### `GET /projects/{project_id}/generation-profile`

返回 `strict_template`、`planned` 或 `pdf_template_manual_fill`，以及模板来源、
保真等级和历史案例参考模式。该接口不返回模板正文或内部存储路径。

### `PUT /projects/{project_id}/generation-profile/template-fields`

保存人工核验的模板字段，例如项目编号、供应商名称和日期。严格模板
仍存在未填占位符或缺少章节落点时，导出门禁会返回明确缺项而不是猜填。

```json
{
  "values": {
    "project_number": "已核验项目编号",
    "bidder_name": "已核验供应商名称"
  }
}
```

主产品流程不要求用户理解 Project；前端应使用等价的
`PUT /workspaces/{workspace_id}/template-fields`，并从工作区响应中读取
`template_required_fields` 和 `template_field_values`。

### `POST /configuration/proposal-memory/case-pairs`

以 multipart 方式上传一份招标文件和对应中标响应 DOCX，并提交 `project_type`、
`industry` 与 `quality_score`。只保存机构私有结构模式，响应只返回学习到的模式数量，
不暴露内部 ID 或案例正文。

### `POST /projects/{project_id}/exports`

创建 DOCX 导出。

请求：

```json
{
  "section_id": "uuid",
  "section_version_id": "uuid",
  "format": "docx"
}
```

返回 `202` 和任务 ID。

### `GET /projects/{project_id}/exports/{export_id}`

返回导出状态。完成后包含应用内下载地址。

### `GET /projects/{project_id}/exports/{export_id}/download`

下载 DOCX。响应设置安全文件名和正确 MIME，不暴露磁盘路径。

## 8. 任务

### `GET /projects/{project_id}/jobs/{job_id}`

返回：

```json
{
  "id": "uuid",
  "type": "requirement_extraction",
  "status": "running",
  "progress": 45,
  "error": null,
  "retryable": true
}
```

状态为 `queued`、`running`、`succeeded` 或 `failed`。

### `POST /projects/{project_id}/jobs/{job_id}/retry`

仅对可重试失败任务创建新任务，返回 `202`。

## 9. 健康检查

### `GET /health`

只说明服务是否存活，不暴露配置。

### `GET /ready`

检查数据库和必要存储是否可用。外部大模型临时不可用可以显示为降级状态，但不得输出密钥或完整连接串。

## 10. 关键响应码

| 状态码 | 用途 |
| --- | --- |
| `200` | 查询或更新成功 |
| `201` | 资源创建成功 |
| `202` | 异步任务已接受 |
| `204` | 删除成功 |
| `400` | 请求格式或文件不合法 |
| `404` | 项目内资源不存在 |
| `409` | 状态、版本或幂等冲突 |
| `413` | 上传文件过大 |
| `422` | 业务校验失败 |
| `503` | 必要依赖暂不可用 |
# 严格回填字段

工作区详情新增：

- `template_field_decisions`：字段值、来源、可信度、审核状态和原因。
- `case_library_count`：当前默认启用的机构私有真实案例数。
- `case_library_scope`：固定为 `organization_private`。
- `case_library_fact_usage`：固定为 `prohibited`，表示历史案例不能直接作为企业事实。

`POST /api/v1/workspaces/{workspace_id}/template-fields/review`

请求：

```json
{
  "field_key": "bidder_name",
  "action": "confirm"
}
```

`action` 支持 `confirm` 和 `reset`。企业字段必须先保存，再人工确认；字段值变化后原确认自动失效。
