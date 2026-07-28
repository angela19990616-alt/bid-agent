import psycopg
import redis

from app.config.settings import settings


def check_postgres() -> dict:
    try:
        with psycopg.connect(settings.postgres_dsn, connect_timeout=5) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT current_database(), version();")
                database, version = cur.fetchone()

        return {
            "status": "healthy",
            "database": database,
            "version": version.split(",")[0],
        }
    except Exception as exc:
        return {
            "status": "unhealthy",
            "error": str(exc),
        }


def check_redis() -> dict:
    try:
        client = redis.Redis(
            host=settings.redis_host,
            port=settings.redis_port,
            db=settings.redis_db,
            socket_connect_timeout=5,
            decode_responses=True,
        )
        client.ping()

        return {
            "status": "healthy",
        }
    except Exception as exc:
        return {
            "status": "unhealthy",
            "error": str(exc),
        }
