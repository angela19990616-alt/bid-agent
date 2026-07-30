from __future__ import annotations

import json
from uuid import UUID

from psycopg.types.json import Jsonb

from app.database.db import connect


class RequirementCheckpointService:
    """Stores completed extraction batches so retries resume without rework."""

    @staticmethod
    def load(project_id: UUID, batch_fingerprint: str) -> list[dict] | None:
        with connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT result
                    FROM requirement_extraction_batches
                    WHERE project_id = %s AND batch_fingerprint = %s
                    """,
                    (project_id, batch_fingerprint),
                )
                row = cursor.fetchone()
        if row is None:
            return None
        payload = row[0]
        if isinstance(payload, str):
            payload = json.loads(payload)
        return payload if isinstance(payload, list) else None

    @staticmethod
    def save(
        project_id: UUID,
        batch_fingerprint: str,
        rule_checksum: str,
        result: list[dict],
    ) -> None:
        with connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO requirement_extraction_batches (
                        project_id, batch_fingerprint, rule_checksum,
                        result, item_count
                    )
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (project_id, batch_fingerprint)
                    DO UPDATE SET
                        result = EXCLUDED.result,
                        item_count = EXCLUDED.item_count,
                        created_at = NOW()
                    """,
                    (
                        project_id,
                        batch_fingerprint,
                        rule_checksum,
                        Jsonb(result),
                        len(result),
                    ),
                )
