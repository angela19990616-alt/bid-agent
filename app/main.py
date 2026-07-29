from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.documents import router as documents_router
from app.api.configuration import router as configuration_router
from app.api.exports import router as exports_router
from app.api.projects import router as projects_router
from app.api.project_documents import router as project_documents_router
from app.api.rag import router as rag_router
from app.api.requirements import router as requirements_router
from app.api.sections import router as sections_router
from app.api.workspaces import router as workspaces_router
from app.config.settings import settings
from app.core.errors import AppError
from app.database.db import check_postgres, check_redis

app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="企业级 AI 标书 Agent 后端服务",
)
app.add_middleware(
    CORSMiddleware,
    # Local development ports; production uses the same-origin /api gateway.
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3100",
        "http://127.0.0.1:3100",
    ],
    allow_origin_regex=r"https://.*\.openai\.site",
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(documents_router, prefix="/api/v1")
app.include_router(rag_router, prefix="/api/v1")
app.include_router(projects_router, prefix="/api/v1")
app.include_router(project_documents_router, prefix="/api/v1")
app.include_router(requirements_router, prefix="/api/v1")
app.include_router(sections_router, prefix="/api/v1")
app.include_router(exports_router, prefix="/api/v1")
app.include_router(workspaces_router, prefix="/api/v1")
app.include_router(configuration_router, prefix="/api/v1")


@app.middleware("http")
async def add_request_id(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or str(uuid4())
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError):
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": exc.code,
                "message": exc.message,
                "request_id": request.state.request_id,
                "details": exc.details,
            }
        },
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(
    request: Request,
    exc: RequestValidationError,
):
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "请求参数不符合要求。",
                "request_id": request.state.request_id,
                "details": {"errors": jsonable_encoder(exc.errors())},
            }
        },
    )


@app.get("/")
def root():
    return {
        "message": "AI标书Agent已经启动",
        "environment": settings.app_env,
        "version": "0.1.0",
    }


@app.get("/health")
def health():
    return {"status": "healthy"}


@app.get("/ready")
def ready():
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
