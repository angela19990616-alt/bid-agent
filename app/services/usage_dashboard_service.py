from __future__ import annotations

from psycopg.rows import dict_row

from app.database.db import connect


class UsageDashboardService:
    """Read-only aggregate usage metrics without customer content or IDs."""

    def summary(self) -> dict:
        with connect() as conn:
            with conn.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    """
                    SELECT
                        (SELECT COUNT(*) FROM projects) AS projects,
                        (SELECT COUNT(*) FROM documents) AS documents,
                        (SELECT COUNT(*) FROM requirements) AS requirements,
                        (SELECT COUNT(*) FROM sections
                         WHERE status = 'approved') AS approved_sections,
                        (SELECT COUNT(*) FROM export_records
                         WHERE status = 'succeeded') AS exports,
                        (SELECT COUNT(*) FROM processing_jobs
                         WHERE status = 'succeeded') AS jobs_succeeded,
                        (SELECT COUNT(*) FROM processing_jobs
                         WHERE status = 'failed') AS jobs_failed,
                        (SELECT COUNT(*) FROM model_usage_events) AS calls,
                        (SELECT COALESCE(SUM(COALESCE(
                            actual_tokens, reserved_tokens
                        )), 0) FROM model_usage_events) AS tokens
                    """
                )
                totals = dict(cursor.fetchone())
                cursor.execute(
                    """
                    SELECT
                        model,
                        task,
                        COUNT(*) AS calls,
                        COUNT(*) FILTER (
                            WHERE status = 'succeeded'
                        ) AS succeeded,
                        COUNT(*) FILTER (
                            WHERE status = 'failed'
                        ) AS failed,
                        COALESCE(SUM(COALESCE(
                            actual_tokens, reserved_tokens
                        )), 0) AS tokens,
                        COALESCE(ROUND((
                            AVG(EXTRACT(EPOCH FROM (
                                finished_at - created_at
                            ))) FILTER (
                                WHERE finished_at IS NOT NULL
                            )
                        )::numeric, 1), 0) AS avg_seconds
                    FROM model_usage_events
                    GROUP BY model, task
                    ORDER BY calls DESC, model, task
                    """
                )
                models = [dict(row) for row in cursor.fetchall()]
                cursor.execute(
                    """
                    WITH days AS (
                        SELECT generate_series(
                            CURRENT_DATE - INTERVAL '13 days',
                            CURRENT_DATE,
                            INTERVAL '1 day'
                        )::date AS day
                    )
                    SELECT
                        days.day,
                        (SELECT COUNT(*) FROM projects p
                         WHERE p.created_at::date = days.day) AS projects,
                        (SELECT COUNT(*) FROM processing_jobs j
                         WHERE j.finished_at::date = days.day
                           AND j.status = 'succeeded') AS jobs_succeeded,
                        (SELECT COUNT(*) FROM processing_jobs j
                         WHERE j.finished_at::date = days.day
                           AND j.status = 'failed') AS jobs_failed,
                        (SELECT COUNT(*) FROM export_records e
                         WHERE e.created_at::date = days.day
                           AND e.status = 'succeeded') AS exports,
                        (SELECT COUNT(*) FROM model_usage_events m
                         WHERE m.created_at::date = days.day) AS calls,
                        (SELECT COALESCE(SUM(COALESCE(
                            m.actual_tokens, m.reserved_tokens
                        )), 0) FROM model_usage_events m
                         WHERE m.created_at::date = days.day) AS tokens
                    FROM days
                    ORDER BY days.day DESC
                    """
                )
                daily = [dict(row) for row in cursor.fetchall()]
                cursor.execute(
                    """
                    SELECT status, COUNT(*) AS count
                    FROM processing_jobs
                    GROUP BY status
                    ORDER BY status
                    """
                )
                jobs = [dict(row) for row in cursor.fetchall()]
        completed = totals["jobs_succeeded"] + totals["jobs_failed"]
        totals["job_success_rate"] = (
            round(totals["jobs_succeeded"] * 100 / completed, 1)
            if completed
            else 0
        )
        return {
            "totals": totals,
            "models": models,
            "daily": daily,
            "jobs": jobs,
        }
