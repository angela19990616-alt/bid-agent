from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from app.config.settings import settings
from app.database.db import connect


class ModelBudgetExceeded(RuntimeError):
    pass


@dataclass(frozen=True)
class ModelReservation:
    event_id: int
    reserved_tokens: int


class ModelBudgetService:
    """Atomically reserves a bounded workflow model budget."""

    @staticmethod
    def reserve(
        workflow_run_id: UUID,
        *,
        task: str,
        model: str,
        estimated_tokens: int,
    ) -> ModelReservation:
        reserved = max(1, estimated_tokens)
        with connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT pg_advisory_xact_lock(hashtext(%s))",
                    (str(workflow_run_id),),
                )
                cursor.execute(
                    """
                    SELECT COUNT(*),
                           COALESCE(SUM(
                               COALESCE(actual_tokens, reserved_tokens)
                           ), 0)
                    FROM model_usage_events
                    WHERE workflow_run_id = %s
                    """,
                    (workflow_run_id,),
                )
                calls, tokens = cursor.fetchone()
                if calls >= settings.max_model_calls_per_workflow:
                    raise ModelBudgetExceeded(
                        "本方案已达到模型调用次数上限，已有结果已保留。"
                    )
                if (
                    tokens + reserved
                    > settings.max_model_tokens_per_workflow
                ):
                    raise ModelBudgetExceeded(
                        "本方案已达到 Token 预算上限，已有结果已保留。"
                    )
                cursor.execute(
                    """
                    INSERT INTO model_usage_events (
                        workflow_run_id, task, model, reserved_tokens
                    )
                    VALUES (%s, %s, %s, %s)
                    RETURNING id
                    """,
                    (workflow_run_id, task, model, reserved),
                )
                event_id = cursor.fetchone()[0]
        return ModelReservation(event_id, reserved)

    @staticmethod
    def finish(
        reservation: ModelReservation,
        *,
        actual_tokens: int | None,
        error_type: str | None = None,
    ) -> None:
        with connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE model_usage_events
                    SET actual_tokens = %s,
                        status = %s,
                        error_type = %s,
                        finished_at = NOW()
                    WHERE id = %s
                    """,
                    (
                        actual_tokens,
                        "failed" if error_type else "succeeded",
                        error_type,
                        reservation.event_id,
                    ),
                )

    @staticmethod
    def estimate(messages: list[dict[str, str]], max_tokens: int) -> int:
        characters = sum(
            len(str(message.get("content", "")))
            for message in messages
        )
        estimated_input = max(1, (characters + 1) // 2)
        return estimated_input + max_tokens

    @staticmethod
    def summary_for_project(project_id: UUID) -> dict[str, int]:
        with connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT COUNT(e.id),
                           COALESCE(SUM(
                               COALESCE(e.actual_tokens, e.reserved_tokens)
                           ), 0)
                    FROM (
                        SELECT id FROM workflow_runs
                        WHERE project_id = %s
                        ORDER BY created_at DESC
                        LIMIT 1
                    ) run
                    LEFT JOIN model_usage_events e
                      ON e.workflow_run_id = run.id
                    """,
                    (project_id,),
                )
                calls, tokens = cursor.fetchone()
        return {
            "model_calls_used": int(calls),
            "model_calls_limit": settings.max_model_calls_per_workflow,
            "model_tokens_used": int(tokens),
            "model_tokens_limit": settings.max_model_tokens_per_workflow,
        }
