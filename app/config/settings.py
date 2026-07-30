import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    app_name: str = os.getenv("APP_NAME", "AI标书Agent")
    app_env: str = os.getenv("APP_ENV", "development")

    postgres_host: str = os.getenv("POSTGRES_HOST", "127.0.0.1")
    postgres_port: int = int(os.getenv("POSTGRES_PORT", "5432"))
    postgres_db: str = os.getenv("POSTGRES_DB", "bid_agent")
    postgres_user: str = os.getenv("POSTGRES_USER", "biduser")
    postgres_password: str = os.getenv("POSTGRES_PASSWORD", "")

    redis_host: str = os.getenv("REDIS_HOST", "127.0.0.1")
    redis_port: int = int(os.getenv("REDIS_PORT", "6379"))
    redis_db: int = int(os.getenv("REDIS_DB", "0"))
    dashscope_api_key: str = os.getenv("DASHSCOPE_API_KEY", "")
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    openai_base_url: str = os.getenv(
        "OPENAI_BASE_URL",
        "https://dashscope.aliyuncs.com/compatible-mode/v1",
    )
    llm_model: str = os.getenv("LLM_MODEL", "qwen3.7-plus")
    extraction_model: str = os.getenv(
        "EXTRACTION_MODEL", "qwen3.7-plus"
    )
    classification_model: str = os.getenv(
        "CLASSIFICATION_MODEL", "qwen3.7-plus"
    )
    writing_model: str = os.getenv(
        "WRITING_MODEL", "qwen3.7-plus"
    )
    review_model: str = os.getenv("REVIEW_MODEL", "qwen3.7-plus")
    max_model_calls_per_workflow: int = int(
        os.getenv("MAX_MODEL_CALLS_PER_WORKFLOW", "40")
    )
    max_model_tokens_per_workflow: int = int(
        os.getenv("MAX_MODEL_TOKENS_PER_WORKFLOW", "300000")
    )
    model_request_timeout_seconds: float = float(
        os.getenv("MODEL_REQUEST_TIMEOUT_SECONDS", "180")
    )
    embedding_model: str = os.getenv(
        "EMBEDDING_MODEL",
        "text-embedding-v4",
    )
    embedding_dimensions: int = int(os.getenv("EMBEDDING_DIMENSIONS", "1024"))
    embedding_batch_size: int = int(os.getenv("EMBEDDING_BATCH_SIZE", "10"))
    chunk_size: int = int(os.getenv("CHUNK_SIZE", "1200"))
    chunk_overlap: int = int(os.getenv("CHUNK_OVERLAP", "200"))
    max_upload_size_mb: int = int(os.getenv("MAX_UPLOAD_SIZE_MB", "20"))
    storage_root: str = os.getenv("STORAGE_ROOT", "storage")
    export_root: str = os.getenv("EXPORT_ROOT", "exports")
    rules_root: str = os.getenv("RULES_ROOT", "config/rules")
    database_connect_timeout: int = int(
        os.getenv("DATABASE_CONNECT_TIMEOUT", "5")
    )
    edge_proxy_secret: str = os.getenv("BID_AGENT_EDGE_SECRET", "")
    invite_code: str = os.getenv("BID_AGENT_INVITE_CODE", "")
    invite_access_ttl_hours: int = int(
        os.getenv("BID_AGENT_INVITE_ACCESS_TTL_HOURS", "168")
    )
    enable_legacy_api: bool = (
        os.getenv(
            "ENABLE_LEGACY_API",
            (
                "false"
                if os.getenv("APP_ENV", "development") == "production"
                else "true"
            ),
        ).lower()
        == "true"
    )

    @property
    def model_api_key(self) -> str:
        return self.dashscope_api_key or self.openai_api_key

    def model_for_task(self, task: str) -> str:
        return {
            "extraction": self.extraction_model,
            "classification": self.classification_model,
            "writing": self.writing_model,
            "review": self.review_model,
        }.get(task, self.llm_model)

    @property
    def postgres_dsn(self) -> str:
        return (
            f"host={self.postgres_host} "
            f"port={self.postgres_port} "
            f"dbname={self.postgres_db} "
            f"user={self.postgres_user} "
            f"password={self.postgres_password}"
        )

    def validate_runtime(self) -> list[str]:
        errors: list[str] = []
        if self.app_env == "production" and not self.postgres_password:
            errors.append("POSTGRES_PASSWORD is required in production")
        if self.app_env == "production" and not self.edge_proxy_secret:
            errors.append("BID_AGENT_EDGE_SECRET is required in production")
        if self.app_env == "production" and not self.invite_code:
            errors.append("BID_AGENT_INVITE_CODE is required in production")
        if self.invite_access_ttl_hours < 1:
            errors.append(
                "BID_AGENT_INVITE_ACCESS_TTL_HOURS must be positive"
            )
        if self.chunk_overlap >= self.chunk_size:
            errors.append("CHUNK_OVERLAP must be smaller than CHUNK_SIZE")
        if self.max_model_calls_per_workflow < 1:
            errors.append(
                "MAX_MODEL_CALLS_PER_WORKFLOW must be positive"
            )
        if self.max_model_tokens_per_workflow < 1000:
            errors.append(
                "MAX_MODEL_TOKENS_PER_WORKFLOW must be at least 1000"
            )
        return errors


settings = Settings()
