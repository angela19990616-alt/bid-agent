from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from psycopg.rows import dict_row

from app.database.db import connect


_CLEAN_SAMPLE_QUERY = """
    SELECT
        EXTRACT(EPOCH FROM (pj.finished_at - pj.created_at))
            AS duration_seconds,
        COUNT(DISTINCT sc.id)::INTEGER AS source_count
    FROM workflow_runs wr
    JOIN processing_jobs pj
      ON pj.project_id = wr.project_id
     AND pj.job_type = 'workspace_pipeline'
     AND pj.input_snapshot->>'workflow_run_id' = wr.id::TEXT
    JOIN projects p ON p.id = wr.project_id
    JOIN documents d ON d.project_id = p.id
    JOIN source_chunks sc ON sc.document_id = d.id
    WHERE p.id <> %s
      AND wr.status = 'succeeded'
      AND wr.finished_at IS NOT NULL
      AND pj.status = 'succeeded'
      AND pj.finished_at IS NOT NULL
      AND wr.finished_at >= NOW() - INTERVAL '30 days'
      AND NOT EXISTS (
          SELECT 1 FROM workflow_runs failed_wr
          WHERE failed_wr.project_id = p.id
            AND failed_wr.status = 'failed'
      )
      AND NOT EXISTS (
          SELECT 1 FROM processing_jobs failed_job
          WHERE failed_job.project_id = p.id
            AND failed_job.status = 'failed'
      )
    GROUP BY wr.id, pj.id, pj.created_at, pj.finished_at
    HAVING EXTRACT(EPOCH FROM (pj.finished_at - pj.created_at))
               BETWEEN 10 AND 7200
    ORDER BY pj.finished_at DESC
    LIMIT 12
"""


@dataclass(frozen=True)
class ProcessingEstimate:
    remaining_seconds_low: int | None
    remaining_seconds_high: int | None
    sample_count: int
    basis: str


class ProcessingEtaService:
    """Estimates from completed local workloads; never uses invented timings."""

    @staticmethod
    def estimate(
        workspace_id: UUID,
        *,
        status: str,
        created_at: datetime,
        source_count: int,
    ) -> ProcessingEstimate:
        if status in {"outline_ready", "writing", "ready_to_export", "exported"}:
            return ProcessingEstimate(0, 0, 0, "completed")
        samples = ProcessingEtaService._samples(workspace_id)
        if not samples or source_count <= 0:
            return ProcessingEstimate(
                None, None, len(samples), "insufficient_history"
            )
        normalized = [
            duration / max(1, workload) ** 0.7
            for duration, workload in samples
            if duration > 0 and workload > 0
        ]
        if not normalized:
            return ProcessingEstimate(
                None, None, 0, "insufficient_history"
            )
        predicted_totals = sorted(
            value * max(1, source_count) ** 0.7 for value in normalized
        )
        low_total = _percentile(predicted_totals, 0.25)
        high_total = _percentile(predicted_totals, 0.75)
        if len(predicted_totals) < 4:
            low_total = min(predicted_totals)
            high_total = max(predicted_totals)
        elapsed = max(
            0,
            (
                datetime.now(timezone.utc)
                - _as_utc(created_at)
            ).total_seconds(),
        )
        low = max(0, math.ceil(low_total - elapsed))
        high = max(low, math.ceil(high_total - elapsed))
        return ProcessingEstimate(
            low,
            high,
            len(predicted_totals),
            "historical_completed_workloads",
        )

    @staticmethod
    def _samples(exclude_workspace_id: UUID) -> list[tuple[float, int]]:
        with connect() as conn:
            with conn.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    _CLEAN_SAMPLE_QUERY,
                    (exclude_workspace_id,),
                )
                return [
                    (float(row["duration_seconds"]), row["source_count"])
                    for row in cursor.fetchall()
                ]


def _percentile(values: list[float], percentile: float) -> float:
    if len(values) == 1:
        return values[0]
    position = (len(values) - 1) * percentile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return values[lower]
    return (
        values[lower] * (upper - position)
        + values[upper] * (position - lower)
    )


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
