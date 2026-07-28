from __future__ import annotations

import json
import re
from dataclasses import dataclass
from uuid import UUID, uuid4

from psycopg.rows import dict_row

from app.core.model_client import ModelClient
from app.database.db import connect


class SectionNotFoundError(Exception):
    pass


class SectionValidationError(Exception):
    pass


class SectionVersionConflictError(Exception):
    pass


class SectionGenerationError(Exception):
    def __init__(self, job_id: UUID, message: str):
        super().__init__(message)
        self.job_id = job_id


@dataclass(frozen=True)
class ReviewFinding:
    finding_type: str
    severity: str
    message: str


class SectionService:
    def __init__(self, model_client: ModelClient | None = None):
        self.model_client = model_client

    def create(
        self,
        project_id: UUID,
        title: str,
        requirement_ids: list[UUID],
    ) -> dict:
        unique_ids = list(dict.fromkeys(requirement_ids))
        with connect() as conn:
            with conn.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    """
                    SELECT id
                    FROM requirements
                    WHERE project_id = %s
                      AND id = ANY(%s)
                      AND status = 'confirmed'
                    """,
                    (project_id, unique_ids),
                )
                confirmed = {row["id"] for row in cursor.fetchall()}
                if confirmed != set(unique_ids):
                    raise SectionValidationError(
                        "章节只能关联当前项目中已确认的要求。"
                    )
                cursor.execute(
                    """
                    INSERT INTO sections (project_id, title)
                    VALUES (%s, %s)
                    RETURNING id
                    """,
                    (project_id, title.strip()),
                )
                section_id = cursor.fetchone()["id"]
                cursor.executemany(
                    """
                    INSERT INTO section_requirements (
                        section_id, requirement_id
                    )
                    VALUES (%s, %s)
                    """,
                    [(section_id, item) for item in unique_ids],
                )
                cursor.execute(
                    """
                    UPDATE projects
                    SET status = 'writing', updated_at = NOW()
                    WHERE id = %s
                    """,
                    (project_id,),
                )
        return self.get(project_id, section_id)

    def list(self, project_id: UUID) -> list[dict]:
        with connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id
                    FROM sections
                    WHERE project_id = %s
                    ORDER BY updated_at DESC
                    """,
                    (project_id,),
                )
                section_ids = [row[0] for row in cursor.fetchall()]
        return [self.get(project_id, item) for item in section_ids]

    def generate(self, project_id: UUID, section_id: UUID) -> dict:
        section, requirements = self._load_generation_input(
            project_id,
            section_id,
        )
        job_id = uuid4()
        snapshot = {
            "section_id": str(section_id),
            "title": section["title"],
            "requirements": [
                {
                    "id": str(item["id"]),
                    "text": item["normalized_text"],
                    "quote": item["quote"],
                }
                for item in requirements
            ],
        }
        self._create_job(project_id, job_id, snapshot)
        try:
            client = self.model_client or ModelClient()
            content = client.chat(
                self._messages(section["title"], requirements),
                temperature=0.2,
                max_tokens=5000,
            ).strip()
            if not content:
                raise RuntimeError("模型返回空内容")
        except Exception as exc:
            self._fail_job(job_id, section_id, type(exc).__name__)
            raise SectionGenerationError(
                job_id,
                "章节生成失败，请检查模型配置或稍后重试。",
            ) from exc

        findings = self.review(content)
        with connect() as conn:
            with conn.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    """
                    SELECT COALESCE(MAX(version_no), 0) + 1 AS next_version
                    FROM section_versions
                    WHERE section_id = %s
                    """,
                    (section_id,),
                )
                version_no = cursor.fetchone()["next_version"]
                cursor.execute(
                    """
                    INSERT INTO section_versions (
                        section_id, version_no, content, origin,
                        input_snapshot
                    )
                    VALUES (%s, %s, %s, 'generated', %s::jsonb)
                    RETURNING id
                    """,
                    (
                        section_id,
                        version_no,
                        content,
                        json.dumps(snapshot, ensure_ascii=False),
                    ),
                )
                version_id = cursor.fetchone()["id"]
                self._insert_findings(cursor, version_id, findings)
                cursor.execute(
                    """
                    UPDATE sections
                    SET current_version_id = %s,
                        status = 'generated',
                        updated_at = NOW()
                    WHERE id = %s
                    """,
                    (version_id, section_id),
                )
                cursor.execute(
                    """
                    UPDATE processing_jobs
                    SET status = 'succeeded', progress = 100,
                        finished_at = NOW(), updated_at = NOW()
                    WHERE id = %s
                    """,
                    (job_id,),
                )
        result = self.get(project_id, section_id)
        result["job_id"] = job_id
        return result

    def save_content(
        self,
        project_id: UUID,
        section_id: UUID,
        base_version_id: UUID,
        content: str,
    ) -> dict:
        with connect() as conn:
            with conn.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    """
                    SELECT current_version_id
                    FROM sections
                    WHERE project_id = %s AND id = %s
                    FOR UPDATE
                    """,
                    (project_id, section_id),
                )
                section = cursor.fetchone()
                if section is None:
                    raise SectionNotFoundError(str(section_id))
                if section["current_version_id"] != base_version_id:
                    raise SectionVersionConflictError(str(section_id))
                cursor.execute(
                    """
                    SELECT COALESCE(MAX(version_no), 0) + 1 AS next_version
                    FROM section_versions
                    WHERE section_id = %s
                    """,
                    (section_id,),
                )
                version_no = cursor.fetchone()["next_version"]
                cursor.execute(
                    """
                    INSERT INTO section_versions (
                        section_id, version_no, content, origin
                    )
                    VALUES (%s, %s, %s, 'edited')
                    RETURNING id
                    """,
                    (section_id, version_no, content.strip()),
                )
                version_id = cursor.fetchone()["id"]
                self._insert_findings(
                    cursor,
                    version_id,
                    self.review(content),
                )
                cursor.execute(
                    """
                    UPDATE sections
                    SET current_version_id = %s,
                        status = 'edited',
                        updated_at = NOW()
                    WHERE id = %s
                    """,
                    (version_id, section_id),
                )
        return self.get(project_id, section_id)

    def approve(self, project_id: UUID, section_id: UUID) -> dict:
        section = self.get(project_id, section_id)
        if section["current_version"] is None:
            raise SectionValidationError("章节尚无可确认版本。")
        if any(
            item["severity"] == "blocking"
            for item in section["findings"]
        ):
            raise SectionValidationError("章节仍有阻断级校核问题。")
        with connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE sections
                    SET status = 'approved', updated_at = NOW()
                    WHERE project_id = %s AND id = %s
                    """,
                    (project_id, section_id),
                )
                cursor.execute(
                    """
                    UPDATE projects
                    SET status = 'ready_to_export', updated_at = NOW()
                    WHERE id = %s
                    """,
                    (project_id,),
                )
        return self.get(project_id, section_id)

    def get(self, project_id: UUID, section_id: UUID) -> dict:
        with connect() as conn:
            with conn.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    """
                    SELECT
                        sections.id, sections.project_id, sections.title,
                        sections.status, sections.created_at,
                        sections.updated_at, sections.current_version_id,
                        section_versions.version_no,
                        section_versions.content,
                        section_versions.origin,
                        section_versions.created_at AS version_created_at
                    FROM sections
                    LEFT JOIN section_versions
                        ON section_versions.id = sections.current_version_id
                    WHERE sections.project_id = %s AND sections.id = %s
                    """,
                    (project_id, section_id),
                )
                row = cursor.fetchone()
                if row is None:
                    raise SectionNotFoundError(str(section_id))
                cursor.execute(
                    """
                    SELECT requirement_id
                    FROM section_requirements
                    WHERE section_id = %s
                    ORDER BY requirement_id
                    """,
                    (section_id,),
                )
                requirement_ids = [
                    item["requirement_id"] for item in cursor.fetchall()
                ]
                findings = []
                if row["current_version_id"]:
                    cursor.execute(
                        """
                        SELECT id, finding_type AS type, severity, message
                        FROM review_findings
                        WHERE section_version_id = %s
                        ORDER BY severity DESC, id
                        """,
                        (row["current_version_id"],),
                    )
                    findings = cursor.fetchall()
        version = None
        if row["current_version_id"]:
            version = {
                "id": row["current_version_id"],
                "version_no": row["version_no"],
                "content": row["content"],
                "origin": row["origin"],
                "created_at": row["version_created_at"],
            }
        return {
            "id": row["id"],
            "project_id": row["project_id"],
            "title": row["title"],
            "status": row["status"],
            "requirement_ids": requirement_ids,
            "current_version": version,
            "findings": findings,
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    @staticmethod
    def review(content: str) -> list[ReviewFinding]:
        findings: list[ReviewFinding] = []
        if len(content.strip()) < 200:
            findings.append(
                ReviewFinding(
                    "content_too_short",
                    "warning",
                    "章节内容较短，请人工检查是否充分响应要求。",
                )
            )
        if re.search(r"(我公司拥有|成功案例|国家级资质|百分之百保证)", content):
            findings.append(
                ReviewFinding(
                    "unsupported_claim",
                    "blocking",
                    "检测到可能缺少依据的能力、案例或保证性表述。",
                )
            )
        if "待补充" in content:
            findings.append(
                ReviewFinding(
                    "placeholder",
                    "warning",
                    "章节包含待补充内容，请在确认前完善。",
                )
            )
        return findings

    @staticmethod
    def _messages(title: str, requirements: list[dict]) -> list[dict[str, str]]:
        evidence = "\n\n".join(
            f"[要求 {item['id']}]\n"
            f"规范描述：{item['normalized_text']}\n"
            f"原文证据：{item['quote']}"
            for item in requirements
        )
        return [
            {
                "role": "system",
                "content": (
                    "你是技术投标方案撰写助手。只能依据给定要求和原文证据写作；"
                    "不得虚构案例、资质、参数、人员、产品能力或承诺。"
                    "缺少企业事实时明确写“【待补充：需要的事实】”。"
                    "输出中文 Markdown 正文，不输出分析过程。"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"请撰写章节《{title}》。逐项响应下列要求，结构清晰、"
                    f"内容可执行，并避免超出证据。\n\n{evidence}"
                ),
            },
        ]

    @staticmethod
    def _load_generation_input(project_id: UUID, section_id: UUID):
        with connect() as conn:
            with conn.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    """
                    SELECT id, title
                    FROM sections
                    WHERE project_id = %s AND id = %s
                    """,
                    (project_id, section_id),
                )
                section = cursor.fetchone()
                if section is None:
                    raise SectionNotFoundError(str(section_id))
                cursor.execute(
                    """
                    SELECT
                        requirements.id,
                        requirements.normalized_text,
                        requirements.quote
                    FROM requirements
                    JOIN section_requirements
                        ON section_requirements.requirement_id =
                           requirements.id
                    WHERE section_requirements.section_id = %s
                      AND requirements.status = 'confirmed'
                    ORDER BY requirements.id
                    """,
                    (section_id,),
                )
                requirements = cursor.fetchall()
        if not requirements:
            raise SectionValidationError("章节没有已确认要求。")
        return section, requirements

    @staticmethod
    def _create_job(project_id: UUID, job_id: UUID, snapshot: dict) -> None:
        with connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO processing_jobs (
                        id, project_id, job_type, status, progress,
                        input_snapshot
                    )
                    VALUES (
                        %s, %s, 'section_generate', 'running', 10, %s::jsonb
                    )
                    """,
                    (
                        job_id,
                        project_id,
                        json.dumps(snapshot, ensure_ascii=False),
                    ),
                )

    @staticmethod
    def _fail_job(job_id: UUID, section_id: UUID, error_code: str) -> None:
        with connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE processing_jobs
                    SET status = 'failed', error_code = %s,
                        error_message = '章节生成失败',
                        finished_at = NOW(), updated_at = NOW()
                    WHERE id = %s
                    """,
                    (error_code, job_id),
                )
                cursor.execute(
                    """
                    UPDATE sections
                    SET status = 'generation_failed', updated_at = NOW()
                    WHERE id = %s
                    """,
                    (section_id,),
                )

    @staticmethod
    def _insert_findings(cursor, version_id: UUID, findings) -> None:
        cursor.executemany(
            """
            INSERT INTO review_findings (
                section_version_id, finding_type, severity, message
            )
            VALUES (%s, %s, %s, %s)
            """,
            [
                (
                    version_id,
                    item.finding_type,
                    item.severity,
                    item.message,
                )
                for item in findings
            ],
        )
