# AI 标书 Agent

基于 FastAPI、LangGraph、PostgreSQL/pgvector 和 Redis 的标书生成服务。

当前已具备文档上传解析、文本分块、pgvector 入库、相似检索和基于知识库的大模型方案生成链路。

## 环境要求

- Python 3.11 或 3.12
- Docker 与 Docker Compose

## 本地启动

复制环境变量模板，并设置新的数据库密码和 API Key：

```bash
cp .env.example .env
```

创建 Python 环境并安装依赖：

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

启动 PostgreSQL 和 Redis：

```bash
docker compose up -d
docker compose ps
```

数据库首次创建时会自动执行 `database/init/001_schema.sql`。如果已有名为 `postgres_data` 的数据卷，初始化脚本不会再次自动执行，可手动执行：

```bash
docker compose exec -T postgres \
  psql -U biduser -d bid_agent \
  < database/init/001_schema.sql
```

启动 API：

```bash
uvicorn app.main:app --reload
```

访问：

- API 文档：http://127.0.0.1:8000/docs
- 健康检查：http://127.0.0.1:8000/health

## 测试

```bash
pytest
```

现有工作流演示也可以单独运行：

```bash
python test_agent.py
```

## RAG 接口

上传并索引 PDF、DOCX、TXT 或 Markdown：

```bash
curl -F "file=@招标文件.docx" \
  http://127.0.0.1:8000/api/v1/documents/upload
```

检索知识库：

```bash
curl -X POST http://127.0.0.1:8000/api/v1/search \
  -H "Content-Type: application/json" \
  -d '{"query":"项目实施进度如何安排","limit":5}'
```

生成带知识库来源的方案：

```bash
curl -X POST http://127.0.0.1:8000/api/v1/generate \
  -H "Content-Type: application/json" \
  -d '{"query":"编制本项目的咨询服务实施方案","retrieval_limit":5}'
```

默认使用 `qwen-plus` 和 1024 维的 `text-embedding-v4`。模型、向量维度、分块长度和上传大小均可在 `.env` 中调整；修改向量维度时必须同步迁移数据库字段。

## 项目结构

```text
app/
├── agents/       Agent 实现
├── api/          HTTP API
├── config/       环境配置
├── core/         LLM 工厂等核心能力
├── database/     PostgreSQL、Redis 与向量存储
├── prompts/      提示词模板
├── rag/          检索增强生成
├── services/     业务服务
└── workflows/    LangGraph 工作流
database/init/    数据库初始化脚本
tests/            自动化测试
```

## 安全说明

- 不要提交 `.env`、API Key、数据库密码或本地虚拟环境。
- 如果凭证曾进入 Git 历史，应立即在供应商后台轮换；仅删除文件不能使旧凭证失效。
- 生产环境应通过密钥管理服务注入配置，并为数据库使用独立的受限账号。
