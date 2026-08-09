from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID, uuid4

from psycopg.rows import dict_row

from app.database.db import connect


WORKSPACE_PIPELINE_JOB = "workspace_pipeline"
AUTONOMOUS_DRAFT_JOB = "autonomous_draft"
SECTION_GENERATION_JOB = "section_generation"


@dataclass(frozen=True)
class WorkspaceJob:
    id: UUID
    workspace_id: UUID
    job_type: str
    input_snapshot: dict

    @property
    def document_id(self) -> UUID | None:
        value = self.input_snapshot.get("document_id")
        return UUID(value) if value else None

    @property
    def workflow_run_id(self) -> UUID | None:
        value = self.input_snapshot.get("workflow_run_id")
        return UUID(value) if value else None

    @property
    def section_id(self) -> UUID | None:
        value = self.input_snapshot.get("section_id")
        return UUID(value) if value else None


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

    def enqueue_autonomous_draft(self, workspace_id: UUID) -> UUID:
        with connect() as conn:
            with conn.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    """
                    SELECT id FROM processing_jobs
                    WHERE project_id = %s AND job_type = %s
                      AND status IN ('queued', 'running')
                    ORDER BY created_at DESC LIMIT 1
                    """,
                    (workspace_id, AUTONOMOUS_DRAFT_JOB),
                )
                existing = cursor.fetchone()
                if existing:
                    return existing["id"]
                job_id = uuid4()
                cursor.execute(
                    """
                    INSERT INTO processing_jobs (
                        id, project_id, job_type, status, progress,
                        input_snapshot
                    )
                    VALUES (%s, %s, %s, 'queued', 0, '{}'::jsonb)
                    """,
                    (job_id, workspace_id, AUTONOMOUS_DRAFT_JOB),
                )
                cursor.execute(
                    """
                    UPDATE projects SET status = 'writing', updated_at = NOW()
                    WHERE id = %s
                    """,
                    (workspace_id,),
                )
        return job_id

    def enqueue_section_generation(
        self,
        workspace_id: UUID,
        section_id: UUID,
        *,
        instruction: str | None,
        case_reference_mode: str,
        min_chars: int,
        max_chars: int,
    ) -> UUID:
        snapshot = json.dumps({
            "section_id": str(section_id),
            "instruction": instruction,
            "case_reference_mode": case_reference_mode,
            "min_chars": min_chars,
            "max_chars": max_chars,
        }, ensure_ascii=False)
        with connect() as conn:
            with conn.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    """
                    SELECT id FROM processing_jobs
                    WHERE project_id = %s AND job_type = %s
                      AND status IN ('queued', 'running')
                    ORDER BY created_at DESC LIMIT 1
                    """,
                    (workspace_id, SECTION_GENERATION_JOB),
                )
                existing = cursor.fetchone()
                if existing:
                    return existing["id"]
                job_id = uuid4()
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
                        SECTION_GENERATION_JOB,
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
                        WHERE job_type = ANY(%s) AND status = 'queued'
                        ORDER BY created_at
                        FOR UPDATE SKIP LOCKED
                        LIMIT 1
                    )
                    UPDATE processing_jobs AS jobs
                    SET status = 'running', progress = 5,
                        updated_at = NOW()
                    FROM candidate
                    WHERE jobs.id = candidate.id
                    RETURNING jobs.id, jobs.project_id, jobs.job_type,
                              jobs.input_snapshot
                    """,
                    ([
                        WORKSPACE_PIPELINE_JOB,
                        AUTONOMOUS_DRAFT_JOB,
                        SECTION_GENERATION_JOB,
                    ],),
                )
                row = cursor.fetchone()
        if row is None:
            return None
        snapshot = row["input_snapshot"]
        return WorkspaceJob(
            id=row["id"],
            workspace_id=row["project_id"],
            job_type=row["job_type"],
            input_snapshot=snapshot,
        )

    @staticmethod
    def update_progress(job_id: UUID, progress: int) -> None:
        with connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE processing_jobs
                    SET progress = %s, updated_at = NOW()
                    WHERE id = %s AND status = 'running'
                    """,
                    (max(5, min(95, progress)), job_id),
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

    @staticmethod
    def latest_status(workspace_id: UUID) -> dict | None:
        with connect() as conn:
            with conn.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    """
                    SELECT status, progress, job_type,
                           error_code, error_message
                    FROM processing_jobs
                    WHERE project_id = %s
                      AND job_type = ANY(%s)
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                    (
                        workspace_id,
                        [
                            WORKSPACE_PIPELINE_JOB,
                            AUTONOMOUS_DRAFT_JOB,
                            SECTION_GENERATION_JOB,
                        ],
                    ),
                )
                row = cursor.fetchone()
        return dict(row) if row is not None else None

    def recover_stale(self, *, after: timedelta = timedelta(minutes=30)) -> int:
        with connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE processing_jobs
                    SET status = 'queued', progress = 0,
                        error_code = NULL, error_message = NULL,
                        updated_at = NOW()
                    WHERE job_type = ANY(%s)
                      AND status = 'running'
                      AND updated_at < NOW() - %s
                    """,
                    ([
                        WORKSPACE_PIPELINE_JOB,
                        AUTONOMOUS_DRAFT_JOB,
                        SECTION_GENERATION_JOB,
                    ], after),
                )
                return cursor.rowcount
