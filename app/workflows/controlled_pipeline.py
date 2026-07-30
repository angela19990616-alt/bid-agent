from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import UUID, uuid4

from psycopg.rows import dict_row

from app.database.db import connect


STAGES = (
    "document_upload",
    "document_validator",
    "load_extraction_rules",
    "parser",
    "document_ingestion",
    "model_budget",
    "requirement_extractor",
    "response_item_normalizer",
    "proposal_classification",
    "load_enterprise_knowledge",
    "knowledge_matching",
    "load_proposal_memory",
    "proposal_memory_matching",
    "load_writing_rules",
    "proposal_planner",
    "chapter_writer",
    "compliance_checker",
    "chapter_review",
    "proposal_review",
    "auto_fix",
    "final_review",
    "deliverability_gate",
    "export",
)


class ControlledPipeline:
    """Persists a finite stage trace; it has no autonomous transitions."""

    def start(
        self,
        project_id: UUID,
        initial_stage: str = "document_upload",
    ) -> UUID:
        if initial_stage not in STAGES:
            raise ValueError(f"未知工作流阶段：{initial_stage}")
        run_id = uuid4()
        with connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO workflow_runs (
                        id, project_id, current_stage, stage_trace
                    )
                    VALUES (%s, %s, %s, '[]'::jsonb)
                    """,
                    (run_id, project_id, initial_stage),
                )
        self.record(run_id, initial_stage)
        return run_id

    def record(
        self,
        run_id: UUID,
        stage: str,
        *,
        rule_snapshot: dict | None = None,
        knowledge_snapshot: list[dict] | None = None,
        details: dict | None = None,
    ) -> None:
        if stage not in STAGES:
            raise ValueError(f"未知工作流阶段：{stage}")
        trace_item = {
            "stage": stage,
            "at": datetime.now(timezone.utc).isoformat(),
            "details": details or {},
        }
        rule_patch = (
            {stage: rule_snapshot} if rule_snapshot is not None else {}
        )
        knowledge_patch = (
            {stage: knowledge_snapshot}
            if knowledge_snapshot is not None
            else {}
        )
        with connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE workflow_runs
                    SET current_stage = %s,
                        stage_trace = stage_trace || %s::jsonb,
                        rule_snapshot = rule_snapshot || %s::jsonb,
                        knowledge_snapshot = knowledge_snapshot || %s::jsonb,
                        updated_at = NOW()
                    WHERE id = %s AND status = 'running'
                    """,
                    (
                        stage,
                        json.dumps([trace_item], ensure_ascii=False),
                        json.dumps(rule_patch, ensure_ascii=False),
                        json.dumps(knowledge_patch, ensure_ascii=False),
                        run_id,
                    ),
                )

    def succeed(self, run_id: UUID, final_stage: str) -> None:
        self.record(run_id, final_stage)
        with connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE workflow_runs
                    SET status = 'succeeded', finished_at = NOW(),
                        updated_at = NOW()
                    WHERE id = %s
                    """,
                    (run_id,),
                )

    @staticmethod
    def fail(run_id: UUID, code: str, message: str) -> None:
        with connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE workflow_runs
                    SET status = 'failed', error_code = %s,
                        error_message = %s, finished_at = NOW(),
                        updated_at = NOW()
                    WHERE id = %s
                    """,
                    (code, message[:1000], run_id),
                )

    @staticmethod
    def latest(project_id: UUID) -> UUID:
        with connect() as conn:
            with conn.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    """
                    SELECT id FROM workflow_runs
                    WHERE project_id = %s
                    ORDER BY created_at DESC LIMIT 1
                    """,
                    (project_id,),
                )
                row = cursor.fetchone()
        if row is None:
            raise ValueError("项目没有工作流运行记录。")
        return row["id"]
