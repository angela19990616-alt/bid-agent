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
    def limits_for_text(text_chars: int) -> tuple[int, int]:
        normalized = max(0, text_chars)
        return (
            min(
                settings.max_model_calls_per_workflow,
                max(12, (normalized + 699) // 700 + 8),
            ),
            min(
                settings.max_model_tokens_per_workflow,
                max(80000, normalized * 12),
            ),
        )

    @staticmethod
    def configure_for_document(
        workflow_run_id: UUID,
        document_id: UUID,
    ) -> dict[str, int]:
        """Scale within hard caps for tenders up to and beyond 20k chars."""
        with connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT COALESCE(SUM(length(source_chunks.content)), 0)
                    FROM source_chunks
                    JOIN documents
                      ON documents.id = source_chunks.document_id
                    WHERE documents.public_id = %s
                    """,
                    (document_id,),
                )
                text_chars = int(cursor.fetchone()[0])
                call_limit, token_limit = (
                    ModelBudgetService.limits_for_text(text_chars)
                )
                cursor.execute(
                    """
                    UPDATE workflow_runs
                    SET model_call_limit = %s,
                        model_token_limit = %s,
                        updated_at = NOW()
                    WHERE id = %s
                    """,
                    (call_limit, token_limit, workflow_run_id),
                )
        return {
            "model_call_limit": call_limit,
            "model_token_limit": token_limit,
            "document_text_chars": text_chars,
        }

    @staticmethod
    def configure_limits(
        workflow_run_id: UUID,
        *,
        call_limit: int,
        token_limit: int,
    ) -> dict[str, int]:
        bounded_calls = min(
            settings.max_model_calls_per_workflow,
            max(1, call_limit),
        )
        bounded_tokens = min(
            settings.max_model_tokens_per_workflow,
            max(1000, token_limit),
        )
        with connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE workflow_runs
                    SET model_call_limit = %s,
                        model_token_limit = %s,
                        updated_at = NOW()
                    WHERE id = %s
                    """,
                    (
                        bounded_calls,
                        bounded_tokens,
                        workflow_run_id,
                    ),
                )
        return {
            "model_call_limit": bounded_calls,
            "model_token_limit": bounded_tokens,
        }

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
                    SELECT COALESCE(model_call_limit, %s),
                           COALESCE(model_token_limit, %s)
                    FROM workflow_runs
                    WHERE id = %s
                    """,
                    (
                        settings.max_model_calls_per_workflow,
                        settings.max_model_tokens_per_workflow,
                        workflow_run_id,
                    ),
                )
                limits = cursor.fetchone()
                if limits is None:
                    raise ModelBudgetExceeded(
                        "未找到当前处理任务的模型预算配置。"
                    )
                call_limit, token_limit = limits
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
                if calls >= call_limit:
                    raise ModelBudgetExceeded(
                        "本轮处理已达到模型调用次数上限，"
                        "已完成的抽取批次已保存，可继续处理。"
                    )
                if tokens + reserved > token_limit:
                    raise ModelBudgetExceeded(
                        "本轮处理已达到 Token 安全上限，"
                        "已完成的抽取批次已保存，可继续处理。"
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
                           ), 0),
                           COALESCE(run.model_call_limit, %s),
                           COALESCE(run.model_token_limit, %s)
                    FROM (
                        SELECT id, model_call_limit, model_token_limit
                        FROM workflow_runs
                        WHERE project_id = %s
                        ORDER BY created_at DESC
                        LIMIT 1
                    ) run
                    LEFT JOIN model_usage_events e
                      ON e.workflow_run_id = run.id
                    GROUP BY run.model_call_limit, run.model_token_limit
                    """,
                    (
                        settings.max_model_calls_per_workflow,
                        settings.max_model_tokens_per_workflow,
                        project_id,
                    ),
                )
                row = cursor.fetchone()
        calls, tokens, call_limit, token_limit = (
            row
            if row is not None
            else (
                0,
                0,
                settings.max_model_calls_per_workflow,
                settings.max_model_tokens_per_workflow,
            )
        )
        return {
            "model_calls_used": int(calls),
            "model_calls_limit": int(call_limit),
            "model_tokens_used": int(tokens),
            "model_tokens_limit": int(token_limit),
        }
