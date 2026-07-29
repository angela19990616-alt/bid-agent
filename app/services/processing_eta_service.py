from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from psycopg.rows import dict_row

from app.database.db import connect


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
                    """
                    SELECT
                        EXTRACT(EPOCH FROM (
                            MIN(s.created_at) - wr.created_at
                        )) AS duration_seconds,
                        COUNT(DISTINCT sc.id)::INTEGER AS source_count
                    FROM workflow_runs wr
                    JOIN projects p ON p.id = wr.project_id
                    JOIN sections s ON s.project_id = p.id
                                      AND s.is_recommended = TRUE
                    JOIN documents d ON d.project_id = p.id
                    JOIN source_chunks sc ON sc.document_id = d.id
                    WHERE p.id <> %s
                    GROUP BY wr.id, wr.created_at
                    HAVING MIN(s.created_at) > wr.created_at
                       AND EXTRACT(EPOCH FROM (
                           MIN(s.created_at) - wr.created_at
                       )) BETWEEN 10 AND 7200
                    ORDER BY wr.created_at DESC
                    LIMIT 30
                    """,
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
