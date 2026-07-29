from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID, uuid4

from psycopg.rows import dict_row

from app.database.db import connect


WORKSPACE_PIPELINE_JOB = "workspace_pipeline"


@dataclass(frozen=True)
class WorkspaceJob:
    id: UUID
    workspace_id: UUID
    document_id: UUID
    workflow_run_id: UUID


class WorkspaceJobService:
    """Durable PostgreSQL queue for long-running workspace processing."""

    def enqueue(
        self,
        workspace_id: UUID,
        document_id: UUID,
        workflow_run_id: UUID,
    ) -> UUID:
        job_id = uuid4()
        snapshot = json.dumps(
            {
                "document_id": str(document_id),
                "workflow_run_id": str(workflow_run_id),
            }
        )
        with connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO processing_jobs (
                        id, project_id, job_type, status, progress,
                        input_snapshot
                    )
                    VALUES (%s, %s, %s, 'queued', 0, %s::jsonb)
                    """,
                    (
                        job_id,
                        workspace_id,
                        WORKSPACE_PIPELINE_JOB,
                        snapshot,
                    ),
                )
        return job_id

    def claim_next(self) -> WorkspaceJob | None:
        with connect() as conn:
            with conn.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    """
                    WITH candidate AS (
                        SELECT id
                        FROM processing_jobs
                        WHERE job_type = %s AND status = 'queued'
                        ORDER BY created_at
                        FOR UPDATE SKIP LOCKED
                        LIMIT 1
                    )
                    UPDATE processing_jobs AS jobs
                    SET status = 'running', progress = 5,
                        updated_at = NOW()
                    FROM candidate
                    WHERE jobs.id = candidate.id
                    RETURNING jobs.id, jobs.project_id,
                              jobs.input_snapshot
                    """,
                    (WORKSPACE_PIPELINE_JOB,),
                )
                row = cursor.fetchone()
        if row is None:
            return None
        snapshot = row["input_snapshot"]
        return WorkspaceJob(
            id=row["id"],
            workspace_id=row["project_id"],
            document_id=UUID(snapshot["document_id"]),
            workflow_run_id=UUID(snapshot["workflow_run_id"]),
        )

    def succeed(self, job_id: UUID) -> None:
        with connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE processing_jobs
                    SET status = 'succeeded', progress = 100,
                        finished_at = NOW(), updated_at = NOW()
                    WHERE id = %s
                    """,
                    (job_id,),
                )

    def fail(self, job_id: UUID, exc: Exception) -> None:
        with connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE processing_jobs
                    SET status = 'failed', progress = 0,
                        error_code = %s, error_message = %s,
                        finished_at = NOW(), updated_at = NOW()
                    WHERE id = %s
                    """,
                    (type(exc).__name__, str(exc)[:1000], job_id),
                )

    def recover_stale(self, *, after: timedelta = timedelta(minutes=30)) -> int:
        with connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE processing_jobs
                    SET status = 'queued', progress = 0,
                        error_code = NULL, error_message = NULL,
                        updated_at = NOW()
                    WHERE job_type = %s
                      AND status = 'running'
                      AND updated_at < NOW() - %s
                    """,
                    (WORKSPACE_PIPELINE_JOB, after),
                )
                return cursor.rowcount
