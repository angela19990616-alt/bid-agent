from __future__ import annotations

from itertools import combinations
from uuid import UUID

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.core.conflict_detection import ConflictDetectionEngine
from app.database.db import connect


class ConflictNotFoundError(Exception):
    pass


class ConflictResolutionError(Exception):
    pass


class ConflictService:
    ROLE_MARKERS = {
        "amendment": ("补遗", "补充通知"),
        "clarification": ("澄清", "答疑"),
        "change_notice": ("变更公告", "更正公告"),
        "scoring_method": ("评分办法", "评审标准", "评分标准"),
        "qualification_review": ("资格审查", "资格条件"),
        "compliance_review": ("符合性审查", "实质性响应"),
        "procurement_requirement": ("采购需求", "技术要求", "服务内容"),
        "contract": ("合同条款", "合同草案", "违约责任", "付款条件"),
    }
    AUTHORITY = {
        "amendment": 1, "clarification": 1, "change_notice": 1,
        "scoring_method": 2, "qualification_review": 2,
        "compliance_review": 2, "procurement_requirement": 3,
        "contract": 3, "unknown": 9,
    }

    @classmethod
    def _role(cls, filename: str, text: str) -> str:
        haystack = f"{filename} {text}"
        for role, markers in cls.ROLE_MARKERS.items():
            if any(marker in haystack for marker in markers):
                return role
        return "unknown"

    def analyze_project(self, project_id: UUID) -> int:
        with connect() as conn:
            with conn.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    """
                    SELECT DISTINCT ON (r.id)
                           r.id, r.title, r.normalized_text, r.quote,
                           r.target_chapter, d.filename, d.document_role,
                           sc.locator_kind, sc.page_no,
                           sc.paragraph_start, sc.paragraph_end
                    FROM requirements r
                    JOIN requirement_sources rs ON rs.requirement_id = r.id
                    JOIN source_chunks sc ON sc.id = rs.source_chunk_id
                    JOIN documents d ON d.id = sc.document_id
                    WHERE r.project_id = %s AND r.status <> 'rejected'
                    ORDER BY r.id, sc.chunk_index
                    """,
                    (project_id,),
                )
                items = cursor.fetchall()
                cursor.execute(
                    """
                    DELETE FROM requirement_conflicts
                    WHERE project_id = %s
                      AND resolution_status = 'pending'
                      AND resolution_choice IS NULL
                    """,
                    (project_id,),
                )
                created = 0
                for left, right in combinations(items, 2):
                    text_a = f"{left['title']} {left['normalized_text']} {left['quote']}"
                    text_b = f"{right['title']} {right['normalized_text']} {right['quote']}"
                    role_a = (
                        left["document_role"]
                        if left["document_role"] != "unknown"
                        else self._role(left["filename"], text_a)
                    )
                    role_b = (
                        right["document_role"]
                        if right["document_role"] != "unknown"
                        else self._role(right["filename"], text_b)
                    )
                    result = ConflictDetectionEngine.compare(
                        text_a=text_a, text_b=text_b,
                        role_a=role_a, role_b=role_b,
                    )
                    if result is None:
                        continue
                    source_a = {
                        "requirement_id": str(left["id"]),
                        "document": left["filename"], "role": role_a,
                        "text": left["quote"],
                    }
                    source_b = {
                        "requirement_id": str(right["id"]),
                        "document": right["filename"], "role": role_b,
                        "text": right["quote"],
                    }
                    location_a = self._location(left)
                    location_b = self._location(right)
                    cursor.execute(
                        """
                        INSERT INTO requirement_conflicts (
                            project_id, topic, conflict_type,
                            requirement_a_id, requirement_b_id,
                            source_a, source_b,
                            source_a_location, source_b_location,
                            source_a_authority_level,
                            source_b_authority_level,
                            description, risk_priority
                        )
                        VALUES (
                            %s, %s, %s, %s, %s, %s, %s, %s, %s,
                            %s, %s, %s, %s
                        )
                        ON CONFLICT DO NOTHING
                        """,
                        (
                            project_id, result.topic, result.conflict_type,
                            left["id"], right["id"],
                            Jsonb(source_a), Jsonb(source_b),
                            Jsonb(location_a), Jsonb(location_b),
                            self.AUTHORITY[role_a], self.AUTHORITY[role_b],
                            result.description, result.risk_priority,
                        ),
                    )
                    created += cursor.rowcount
                return created

    @staticmethod
    def _location(row: dict) -> dict:
        if row["locator_kind"] == "page":
            return {"kind": "page", "page": row["page_no"]}
        return {
            "kind": "paragraph",
            "paragraph_start": row["paragraph_start"],
            "paragraph_end": row["paragraph_end"],
        }

    def list(self, project_id: UUID) -> list[dict]:
        with connect() as conn:
            with conn.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    """
                    SELECT rc.*,
                           COALESCE(array_agg(DISTINCT s.title)
                             FILTER (WHERE s.title IS NOT NULL),
                             ARRAY[]::text[]) AS affected_sections
                    FROM requirement_conflicts rc
                    LEFT JOIN section_requirements sr
                      ON sr.requirement_id IN (
                          rc.requirement_a_id, rc.requirement_b_id
                      )
                    LEFT JOIN sections s ON s.id = sr.section_id
                    WHERE rc.project_id = %s
                    GROUP BY rc.conflict_id
                    ORDER BY
                      CASE rc.risk_priority
                        WHEN 'P0' THEN 0 WHEN 'P1' THEN 1
                        WHEN 'P2' THEN 2 ELSE 3 END,
                      rc.created_at
                    """,
                    (project_id,),
                )
                return [dict(row) for row in cursor.fetchall()]

    def resolve(
        self,
        project_id: UUID,
        conflict_id: UUID,
        *,
        choice: str,
        resolved_by: str,
        note: str | None = None,
    ) -> dict:
        with connect() as conn:
            with conn.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    """
                    SELECT conflict_id FROM requirement_conflicts
                    WHERE project_id = %s AND conflict_id = %s
                    FOR UPDATE
                    """,
                    (project_id, conflict_id),
                )
                if cursor.fetchone() is None:
                    raise ConflictNotFoundError(str(conflict_id))
                cursor.execute(
                    """
                    SELECT COALESCE(MAX(version), 0) + 1 AS version
                    FROM conflict_decisions WHERE conflict_id = %s
                    """,
                    (conflict_id,),
                )
                version = cursor.fetchone()["version"]
                cursor.execute(
                    """
                    INSERT INTO conflict_decisions (
                        conflict_id, version, resolution_choice,
                        decided_by, decision_note
                    )
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (conflict_id, version, choice, resolved_by, note),
                )
                status = (
                    "pending"
                    if choice == "request_clarification"
                    else "resolved"
                )
                cursor.execute(
                    """
                    UPDATE requirement_conflicts
                    SET resolution_status = %s, resolution_choice = %s,
                        resolved_by = %s, resolved_time = NOW(),
                        updated_at = NOW()
                    WHERE conflict_id = %s
                    """,
                    (status, choice, resolved_by, conflict_id),
                )
        return next(
            item for item in self.list(project_id)
            if item["conflict_id"] == conflict_id
        )

    @staticmethod
    def assert_section_unblocked(project_id: UUID, section_id: UUID) -> None:
        with connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT rc.topic
                    FROM requirement_conflicts rc
                    JOIN section_requirements sr
                      ON sr.requirement_id IN (
                          rc.requirement_a_id, rc.requirement_b_id
                      )
                    WHERE rc.project_id = %s AND sr.section_id = %s
                      AND rc.conflict_type = 'true_conflict'
                      AND rc.resolution_status = 'pending'
                      AND rc.resolution_choice = 'request_clarification'
                    LIMIT 1
                    """,
                    (project_id, section_id),
                )
                row = cursor.fetchone()
        if row:
            raise ConflictResolutionError(
                f"本章节涉及待澄清事项“{row[0]}”，解决后才能生成。"
            )

    @staticmethod
    def assert_export_ready(project_id: UUID) -> None:
        with connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT COUNT(*)
                    FROM requirement_conflicts
                    WHERE project_id = %s
                      AND conflict_type = 'true_conflict'
                      AND resolution_status = 'pending'
                    """,
                    (project_id,),
                )
                pending = cursor.fetchone()[0]
        if pending:
            raise ConflictResolutionError(
                f"仍有 {pending} 项招标文件真实冲突未解决，不能正式导出。"
            )

    @staticmethod
    def pending_true_conflict_count(project_id: UUID) -> int:
        with connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT COUNT(*)
                    FROM requirement_conflicts
                    WHERE project_id = %s
                      AND conflict_type = 'true_conflict'
                      AND resolution_status = 'pending'
                    """,
                    (project_id,),
                )
                return int(cursor.fetchone()[0])
