import psycopg

from app.config.settings import settings


class ConfigService:

    @staticmethod
    def get(config_key: str):
        with psycopg.connect(settings.postgres_dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT config_value
                    FROM system_config
                    WHERE config_key=%s
                    AND is_active=TRUE
                    """,
                    (config_key,),
                )

                row = cur.fetchone()

                if row is None:
                    return None

                return row[0]
