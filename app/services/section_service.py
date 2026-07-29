from __future__ import annotations

import json
from dataclasses import dataclass
from uuid import UUID, uuid4

from psycopg.rows import dict_row

from app.core.model_client import ModelClient
from app.database.db import connect
from app.knowledge.engine import (
    EnterpriseKnowledgeEngine,
    KnowledgeMatch,
    KnowledgeMatchRepository,
)
from app.rules.engine import RuleDocument, RuleEngine
from app.services.provenance_service import ProvenanceService
from app.workflows.controlled_pipeline import ControlledPipeline


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
    def __init__(
        self,
        model_client: ModelClient | None = None,
        rule_engine: RuleEngine | None = None,
        knowledge_engine: EnterpriseKnowledgeEngine | None = None,
    ):
        self.model_client = model_client
        self.rule_engine = rule_engine or RuleEngine()
        self.knowledge_engine = (
            knowledge_engine or EnterpriseKnowledgeEngine()
        )

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
                      AND status <> 'rejected'
                      AND need_generation = TRUE
                    """,
                    (project_id, unique_ids),
                )
                eligible = {row["id"] for row in cursor.fetchall()}
                if eligible != set(unique_ids):
                    raise SectionValidationError(
                        "章节只能关联当前项目中与技术方案相关的要求。"
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
                      AND EXISTS (
                          SELECT 1
                          FROM section_requirements
                          JOIN requirements
                            ON requirements.id =
                               section_requirements.requirement_id
                          WHERE section_requirements.section_id = sections.id
                            AND requirements.status <> 'rejected'
                            AND requirements.need_generation = TRUE
                      )
                    ORDER BY sort_order ASC, created_at ASC
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
        pipeline = ControlledPipeline()
        try:
            workflow_run_id = pipeline.latest(project_id)
        except ValueError:
            workflow_run_id = pipeline.start(project_id)
        pipeline.record(workflow_run_id, "load_enterprise_knowledge")
        matches = self.knowledge_engine.match(
            section_title=section["title"],
            requirements=requirements,
            exclude_document_ids=set(section["document_ids"]),
            exclude_project_id=project_id,
        )
        KnowledgeMatchRepository.save(
            workflow_run_id, section_id, requirements, matches
        )
        pipeline.record(
            workflow_run_id,
            "knowledge_matching",
            knowledge_snapshot=[item.snapshot() for item in matches],
            details={"match_count": len(matches)},
        )
        writing_rules = self.rule_engine.load("writing")
        pipeline.record(
            workflow_run_id,
            "load_writing_rules",
            rule_snapshot=writing_rules.snapshot(),
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
            "writing_rule": writing_rules.snapshot(),
            "knowledge_matches": [item.snapshot() for item in matches],
        }
        self._create_job(
            project_id, job_id, snapshot, workflow_run_id
        )
        pipeline.record(workflow_run_id, "chapter_writer")
        try:
            client = self.model_client or ModelClient()
            content = client.chat(
                self._messages(
                    section["title"],
                    requirements,
                    matches,
                    writing_rules,
                ),
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

        compliance_rules = self.rule_engine.load("compliance")
        pipeline.record(
            workflow_run_id,
            "compliance_checker",
            rule_snapshot=compliance_rules.snapshot(),
        )
        findings = self.review(content, compliance_rules)
        provenance, case_usage = ProvenanceService.build(
            section_title=section["title"],
            content=content,
            requirements=requirements,
            matches=matches,
        )
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
                        input_snapshot, rule_snapshot, knowledge_snapshot
                    )
                    VALUES (
                        %s, %s, %s, 'generated', %s::jsonb,
                        %s::jsonb, %s::jsonb
                    )
                    RETURNING id
                    """,
                    (
                        section_id,
                        version_no,
                        content,
                        json.dumps(snapshot, ensure_ascii=False),
                        json.dumps(
                            {
                                "writing": writing_rules.snapshot(),
                                "compliance": compliance_rules.snapshot(),
                            },
                            ensure_ascii=False,
                        ),
                        json.dumps(
                            [item.snapshot() for item in matches],
                            ensure_ascii=False,
                        ),
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
        ProvenanceService.persist(version_id, provenance, case_usage)
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
        compliance_rules = self.rule_engine.load("compliance")
        pipeline = ControlledPipeline()
        workflow_run_id = pipeline.latest(project_id)
        pipeline.record(
            workflow_run_id,
            "compliance_checker",
            rule_snapshot=compliance_rules.snapshot(),
            details={"origin": "edited"},
        )
        with connect() as conn:
            with conn.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    """
                    SELECT
                        sections.current_version_id,
                        sections.title,
                        section_versions.rule_snapshot,
                        section_versions.knowledge_snapshot
                    FROM sections
                    LEFT JOIN section_versions
                      ON section_versions.id = sections.current_version_id
                    WHERE sections.project_id = %s
                      AND sections.id = %s
                    FOR UPDATE OF sections
                    """,
                    (project_id, section_id),
                )
                section = cursor.fetchone()
                if section is None:
                    raise SectionNotFoundError(str(section_id))
                if section["current_version_id"] != base_version_id:
                    raise SectionVersionConflictError(str(section_id))
                provenance, case_usage = ProvenanceService.build(
                    section_title=section.get("title")
                    or "人工编辑章节",
                    content=content,
                    requirements=[],
                    matches=[],
                    origin="edited",
                )
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
                        rule_snapshot, knowledge_snapshot
                    )
                    VALUES (
                        %s, %s, %s, 'edited', %s::jsonb, %s::jsonb
                    )
                    RETURNING id
                    """,
                    (
                        section_id,
                        version_no,
                        content.strip(),
                        json.dumps(
                            {
                                **dict(section["rule_snapshot"] or {}),
                                "compliance": (
                                    compliance_rules.snapshot()
                                ),
                            },
                            ensure_ascii=False,
                        ),
                        json.dumps(
                            section["knowledge_snapshot"] or [],
                            ensure_ascii=False,
                        ),
                    ),
                )
                version_id = cursor.fetchone()["id"]
                self._insert_findings(
                    cursor,
                    version_id,
                    self.review(
                        content,
                        compliance_rules,
                    ),
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
        ProvenanceService.persist(version_id, provenance, case_usage)
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
                        sections.status, sections.sort_order,
                        sections.is_recommended, sections.created_at,
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
            "sort_order": row["sort_order"],
            "is_recommended": row["is_recommended"],
            "requirement_ids": requirement_ids,
            "current_version": version,
            "findings": findings,
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    @staticmethod
    def review(
        content: str,
        rules: RuleDocument | None = None,
    ) -> list[ReviewFinding]:
        active = rules or RuleEngine().load_default("compliance")
        findings: list[ReviewFinding] = []
        for check in active.content["checks"]:
            kind = check["kind"]
            value = check["value"]
            matched = (
                kind == "min_length" and len(content.strip()) < int(value)
            ) or (
                kind in {"contains", "forbidden_patterns"}
                and any(pattern in content for pattern in value)
            )
            if matched:
                findings.append(
                    ReviewFinding(
                        check["key"],
                        check["severity"],
                        check["message"],
                    )
                )
        return findings

    @staticmethod
    def _messages(
        title: str,
        requirements: list[dict],
        matches: list[KnowledgeMatch] | None = None,
        rules: RuleDocument | None = None,
    ) -> list[dict[str, str]]:
        active = rules or RuleEngine().load_default("writing")
        matched_items = matches or []
        evidence = "\n\n".join(
            f"[要求 {item['id']}]\n"
            f"规范描述：{item['normalized_text']}\n"
            f"原文证据：{item['quote']}"
            for item in requirements
        )
        knowledge = "\n\n".join(
            f"[企业知识 {item.knowledge_id}｜{item.category}]\n"
            f"标题：{item.title}\n元数据："
            f"{json.dumps(item.metadata, ensure_ascii=False)}\n"
            f"内容：{item.content}"
            for item in matched_items
        ) or "无匹配企业知识；涉及企业事实时必须使用规则中的待补充占位符。"
        return [
            {
                "role": "system",
                "content": (
                    active.content["model_instruction"]
                    + "\n本次已加载的版本化写作规则：\n"
                    + json.dumps(active.content, ensure_ascii=False)
                ),
            },
            {
                "role": "user",
                "content": (
                    active.content["user_template"].format(
                        section_title=title
                    )
                    + f"\n\nRequirements:\n{evidence}"
                    + f"\n\nMatched Knowledge:\n{knowledge}"
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
                        requirements.title,
                        requirements.requirement_type AS type,
                        requirements.normalized_text,
                        requirements.quote
                    FROM requirements
                    JOIN section_requirements
                        ON section_requirements.requirement_id =
                           requirements.id
                    WHERE section_requirements.section_id = %s
                      AND requirements.status <> 'rejected'
                      AND requirements.need_generation = TRUE
                    ORDER BY requirements.id
                    """,
                    (section_id,),
                )
                requirements = cursor.fetchall()
                cursor.execute(
                    """
                    SELECT id
                    FROM documents
                    WHERE project_id = %s
                    """,
                    (project_id,),
                )
                section["document_ids"] = [
                    item["id"] for item in cursor.fetchall()
                ]
        if not requirements:
            raise SectionValidationError("章节没有可用于技术方案生成的要求。")
        return section, requirements

    @staticmethod
    def _create_job(
        project_id: UUID,
        job_id: UUID,
        snapshot: dict,
        workflow_run_id: UUID,
    ) -> None:
        with connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO processing_jobs (
                        id, project_id, job_type, status, progress,
                        input_snapshot, workflow_run_id
                    )
                    VALUES (
                        %s, %s, 'section_generate', 'running', 10,
                        %s::jsonb, %s
                    )
                    """,
                    (
                        job_id,
                        project_id,
                        json.dumps(snapshot, ensure_ascii=False),
                        workflow_run_id,
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
