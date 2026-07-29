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
    llm_model: str = os.getenv("LLM_MODEL", "qwen-plus")
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

    @property
    def model_api_key(self) -> str:
        return self.dashscope_api_key or self.openai_api_key

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
        if self.chunk_overlap >= self.chunk_size:
            errors.append("CHUNK_OVERLAP must be smaller than CHUNK_SIZE")
        return errors


settings = Settings()
