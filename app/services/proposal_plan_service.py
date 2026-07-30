from __future__ import annotations

from uuid import UUID

from psycopg.rows import dict_row

from app.agents.proposal_planner import ProposalPlanner
from app.database.db import connect
from app.rules.engine import RuleDocument, RuleEngine
from app.services.section_service import SectionService


class ProposalPlanError(Exception):
    pass


class ProposalPlanService:
    def __init__(
        self,
        planner: ProposalPlanner | None = None,
        rule_engine: RuleEngine | None = None,
    ):
        self.planner = planner or ProposalPlanner()
        self.rule_engine = rule_engine or RuleEngine()

    def create_recommended_outline(
        self,
        project_id: UUID,
        rules: RuleDocument | None = None,
    ) -> list[dict]:
        with connect() as conn:
            with conn.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    """
                    SELECT id, proposal_chapter, target_chapter,
                           need_generation
                    FROM requirements
                    WHERE project_id = %s
                      AND status <> 'rejected'
                      AND need_generation = TRUE
                    ORDER BY created_at, id
                    """,
                    (project_id,),
                )
                active_rules = rules or self.rule_engine.load("writing")
                chapters = self.planner.plan(
                    cursor.fetchall(), active_rules
                )
                if not chapters:
                    raise ProposalPlanError(
                        "未提取到可用于技术方案撰写的要求。"
                    )
                cursor.execute(
                    """
                    DELETE FROM sections
                    WHERE project_id = %s
                      AND current_version_id IS NULL
                    """,
                    (project_id,),
                )
                for chapter in chapters:
                    cursor.execute(
                        """
                        INSERT INTO sections (
                            project_id, title, sort_order, is_recommended
                        )
                        VALUES (%s, %s, %s, TRUE)
                        RETURNING id
                        """,
                        (project_id, chapter.title, chapter.sort_order),
                    )
                    section_id = cursor.fetchone()["id"]
                    cursor.executemany(
                        """
                        INSERT INTO section_requirements (
                            section_id, requirement_id
                        )
                        VALUES (%s, %s)
                        """,
                        [
                            (section_id, requirement_id)
                            for requirement_id in chapter.requirement_ids
                        ],
                    )
                cursor.execute(
                    """
                    UPDATE projects
                    SET status = 'outline_ready', updated_at = NOW()
                    WHERE id = %s
                    """,
                    (project_id,),
                )
        return SectionService().list(project_id)

    def replace_outline(
        self,
        project_id: UUID,
        chapters: list[dict],
    ) -> list[dict]:
        with connect() as conn:
            with conn.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    """
                    SELECT 1 FROM sections
                    WHERE project_id = %s AND current_version_id IS NOT NULL
                    LIMIT 1
                    """,
                    (project_id,),
                )
                if cursor.fetchone():
                    raise ProposalPlanError(
                        "已有章节开始生成，不能整体替换目录。"
                    )
                requirement_ids = [
                    requirement_id
                    for chapter in chapters
                    for requirement_id in chapter["requirement_ids"]
                ]
                if not requirement_ids:
                    raise ProposalPlanError("目录至少需要关联一条技术要求。")
                cursor.execute(
                    """
                    SELECT id FROM requirements
                    WHERE project_id = %s
                      AND id = ANY(%s)
                      AND status <> 'rejected'
                      AND need_generation = TRUE
                    """,
                    (project_id, list(dict.fromkeys(requirement_ids))),
                )
                eligible = {row["id"] for row in cursor.fetchall()}
                if eligible != set(requirement_ids):
                    raise ProposalPlanError(
                        "目录包含无效或不参与技术方案生成的要求。"
                    )
                cursor.execute(
                    "DELETE FROM sections WHERE project_id = %s",
                    (project_id,),
                )
                for index, chapter in enumerate(chapters, start=1):
                    cursor.execute(
                        """
                        INSERT INTO sections (
                            project_id, title, sort_order, is_recommended
                        )
                        VALUES (%s, %s, %s, FALSE)
                        RETURNING id
                        """,
                        (project_id, chapter["title"].strip(), index),
                    )
                    section_id = cursor.fetchone()["id"]
                    cursor.executemany(
                        """
                        INSERT INTO section_requirements (
                            section_id, requirement_id
                        )
                        VALUES (%s, %s)
                        """,
                        [
                            (section_id, requirement_id)
                            for requirement_id in dict.fromkeys(
                                chapter["requirement_ids"]
                            )
                        ],
                    )
        return SectionService().list(project_id)
