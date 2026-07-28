from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.documents import router as documents_router
from app.api.rag import router as rag_router
from app.config.settings import settings
from app.database.db import check_postgres, check_redis

app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="企业级 AI 标书 Agent 后端服务",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_origin_regex=r"https://.*\.openai\.site",
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(documents_router, prefix="/api/v1")
app.include_router(rag_router, prefix="/api/v1")


@app.get("/")
def root():
    return {
        "message": "AI标书Agent已经启动",
        "environment": settings.app_env,
        "version": "0.1.0",
    }


@app.get("/health")
def health():
    postgres = check_postgres()
    redis = check_redis()

    overall = (
        "healthy"
        if postgres["status"] == "healthy"
        and redis["status"] == "healthy"
        else "unhealthy"
    )

    return {
        "status": overall,
        "services": {
            "postgres": postgres,
            "redis": redis,
        },
    }
