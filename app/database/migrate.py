import hashlib
from pathlib import Path

from app.database.db import connect


MIGRATIONS_DIR = (
    Path(__file__).resolve().parents[2] / "database" / "migrations"
)


def migrate() -> list[str]:
    applied: list[str] = []
    with connect() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version TEXT PRIMARY KEY,
                    checksum TEXT NOT NULL,
                    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            cursor.execute(
                "SELECT version, checksum FROM schema_migrations"
            )
            existing = dict(cursor.fetchall())

            for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
                sql = path.read_text(encoding="utf-8")
                checksum = hashlib.sha256(sql.encode()).hexdigest()
                if path.name in existing:
                    if existing[path.name] != checksum:
                        raise RuntimeError(
                            f"Migration changed after apply: {path.name}"
                        )
                    continue
                cursor.execute(sql)
                cursor.execute(
                    """
                    INSERT INTO schema_migrations (version, checksum)
                    VALUES (%s, %s)
                    """,
                    (path.name, checksum),
                )
                applied.append(path.name)
    return applied


if __name__ == "__main__":
    for version in migrate():
        print(f"Applied {version}")
