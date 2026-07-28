from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from psycopg.rows import dict_row

from app.database.db import connect


TRIGGER_WORDS = (
    "应",
    "须",
    "要求",
    "评分",
    "分值",
    "不得",
    "需要",
    "提供",
    "提交",
    "具备",
    "包含",
)
SENTENCE_SPLIT = re.compile(r"(?<=[。；;！？!?])|\n+")


@dataclass(frozen=True)
class Candidate:
    source_id: UUID
    text: str
    requirement_type: str
    importance: str
    confidence: float
    fingerprint: str


class RequirementNotFoundError(Exception):
    pass


class RequirementValidationError(Exception):
    pass


class RequirementService:
    def extract(
        self,
        project_id: UUID,
        document_ids: list[UUID],
    ) -> tuple[int, int]:
        sources = self._load_sources(project_id, document_ids)
        if not sources:
            raise RequirementValidationError(
                "没有找到可用于提取的已解析文件。"
            )
        candidates: list[Candidate] = []
        seen: set[str] = set()
        for source in sources:
            for sentence in SENTENCE_SPLIT.split(source["content"]):
                text = " ".join(sentence.split()).strip(" -—\t")
                if not self._is_candidate(text):
                    continue
                text = text[:1000]
                fingerprint = hashlib.sha256(text.encode()).hexdigest()
                if fingerprint in seen:
                    continue
                seen.add(fingerprint)
                candidates.append(
                    Candidate(
                        source_id=source["id"],
                        text=text,
                        requirement_type=self._classify(text),
                        importance=self._importance(text),
                        confidence=self._confidence(text),
                        fingerprint=fingerprint,
                    )
                )
                if len(candidates) >= 200:
                    break
            if len(candidates) >= 200:
                break

        created = 0
        skipped = 0
        with connect() as conn:
            with conn.cursor() as cursor:
                for candidate in candidates:
                    cursor.execute(
                        """
                        INSERT INTO requirements (
                            project_id, requirement_type, title,
                            normalized_text, quote, importance, confidence,
                            fingerprint
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (project_id, fingerprint) DO NOTHING
                        RETURNING id
                        """,
                        (
                            project_id,
                            candidate.requirement_type,
                            candidate.text[:80],
                            candidate.text,
                            candidate.text,
                            candidate.importance,
                            candidate.confidence,
                            candidate.fingerprint,
                        ),
                    )
                    row = cursor.fetchone()
                    if row is None:
                        skipped += 1
                        continue
                    cursor.execute(
                        """
                        INSERT INTO requirement_sources (
                            requirement_id, source_chunk_id
                        )
                        VALUES (%s, %s)
                        """,
                        (row[0], candidate.source_id),
                    )
                    created += 1
                cursor.execute(
                    """
                    UPDATE projects
                    SET status = 'reviewing_requirements', updated_at = NOW()
                    WHERE id = %s
                    """,
                    (project_id,),
                )
        return created, skipped

    def list(
        self,
        project_id: UUID,
        *,
        status: str | None = None,
        requirement_type: str | None = None,
        document_id: UUID | None = None,
    ) -> list[dict]:
        filters = ["requirements.project_id = %s"]
        params: list[object] = [project_id]
        if status:
            filters.append("requirements.status = %s")
            params.append(status)
        if requirement_type:
            filters.append("requirements.requirement_type = %s")
            params.append(requirement_type)
        if document_id:
            filters.append("documents.public_id = %s")
            params.append(document_id)
        sql = self._select_sql() + " WHERE " + " AND ".join(filters)
        sql += " ORDER BY requirements.updated_at DESC"
        with connect() as conn:
            with conn.cursor(row_factory=dict_row) as cursor:
                cursor.execute(sql, params)
                return self._group_rows(cursor.fetchall())

    def update(
        self,
        project_id: UUID,
        requirement_id: UUID,
        changes: dict,
    ) -> dict:
        allowed = {
            "title": "title",
            "normalized_text": "normalized_text",
            "type": "requirement_type",
            "importance": "importance",
            "status": "status",
        }
        values = {
            allowed[key]: value.strip() if isinstance(value, str) else value
            for key, value in changes.items()
            if value is not None and key in allowed
        }
        if values.get("status") == "confirmed":
            with connect() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT 1
                        FROM requirement_sources
                        JOIN requirements
                            ON requirements.id =
                               requirement_sources.requirement_id
                        WHERE requirements.project_id = %s
                          AND requirements.id = %s
                        """,
                        (project_id, requirement_id),
                    )
                    if cursor.fetchone() is None:
                        raise RequirementValidationError(
                            "没有有效原文来源的要求不能确认。"
                        )
        if values:
            assignments = ", ".join(f"{key} = %s" for key in values)
            params = [*values.values(), project_id, requirement_id]
            with connect() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        f"""
                        UPDATE requirements
                        SET {assignments}, updated_at = NOW()
                        WHERE project_id = %s AND id = %s
                        """,
                        params,
                    )
                    if cursor.rowcount == 0:
                        raise RequirementNotFoundError(str(requirement_id))
        return self.get(project_id, requirement_id)

    def reject(self, project_id: UUID, requirement_id: UUID) -> None:
        with connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE requirements
                    SET status = 'rejected', updated_at = NOW()
                    WHERE project_id = %s AND id = %s
                    """,
                    (project_id, requirement_id),
                )
                if cursor.rowcount == 0:
                    raise RequirementNotFoundError(str(requirement_id))

    def get(self, project_id: UUID, requirement_id: UUID) -> dict:
        with connect() as conn:
            with conn.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    self._select_sql()
                    + """
                    WHERE requirements.project_id = %s
                      AND requirements.id = %s
                    """,
                    (project_id, requirement_id),
                )
                rows = cursor.fetchall()
        if not rows:
            raise RequirementNotFoundError(str(requirement_id))
        return self._group_rows(rows)[0]

    @staticmethod
    def _load_sources(project_id: UUID, document_ids: list[UUID]):
        with connect() as conn:
            with conn.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    """
                    SELECT source_chunks.id, source_chunks.content
                    FROM source_chunks
                    JOIN documents
                        ON documents.id = source_chunks.document_id
                    WHERE documents.project_id = %s
                      AND documents.public_id = ANY(%s)
                      AND documents.status = 'parsed'
                    ORDER BY documents.id, source_chunks.chunk_index
                    """,
                    (project_id, document_ids),
                )
                return cursor.fetchall()

    @staticmethod
    def _is_candidate(text: str) -> bool:
        return 8 <= len(text) <= 1000 and any(
            word in text for word in TRIGGER_WORDS
        )

    @staticmethod
    def _classify(text: str) -> str:
        if any(word in text for word in ("评分", "得分", "分值", "加分")):
            return "scoring"
        if any(word in text for word in ("资格", "资质", "证书", "业绩")):
            return "qualification"
        if any(word in text for word in ("交付", "工期", "提交", "验收")):
            return "delivery"
        return "technical"

    @staticmethod
    def _importance(text: str) -> str:
        if any(word in text for word in ("必须", "不得", "否决", "评分", "分值")):
            return "high"
        if any(word in text for word in ("应", "须", "要求")):
            return "medium"
        return "low"

    @staticmethod
    def _confidence(text: str) -> float:
        score = 0.55
        score += 0.15 if any(word in text for word in ("必须", "须", "不得")) else 0
        score += 0.1 if any(word in text for word in ("评分", "分值", "要求")) else 0
        return min(score, 0.9)

    @staticmethod
    def _select_sql() -> str:
        return """
            SELECT
                requirements.id,
                requirements.project_id,
                requirements.requirement_type AS type,
                requirements.title,
                requirements.normalized_text,
                requirements.quote,
                requirements.importance,
                requirements.confidence,
                requirements.status,
                requirements.created_at,
                requirements.updated_at,
                source_chunks.id AS source_id,
                documents.public_id AS document_id,
                documents.filename,
                source_chunks.locator_kind,
                source_chunks.page_no,
                source_chunks.paragraph_start,
                source_chunks.paragraph_end
            FROM requirements
            JOIN requirement_sources
                ON requirement_sources.requirement_id = requirements.id
            JOIN source_chunks
                ON source_chunks.id =
                   requirement_sources.source_chunk_id
            JOIN documents
                ON documents.id = source_chunks.document_id
        """

    @staticmethod
    def _group_rows(rows) -> list[dict]:
        grouped: dict[UUID, dict] = {}
        for row in rows:
            item = grouped.setdefault(
                row["id"],
                {
                    "id": row["id"],
                    "project_id": row["project_id"],
                    "type": row["type"],
                    "title": row["title"],
                    "normalized_text": row["normalized_text"],
                    "quote": row["quote"],
                    "importance": row["importance"],
                    "confidence": float(
                        row["confidence"]
                        if isinstance(row["confidence"], Decimal)
                        else row["confidence"]
                    ),
                    "status": row["status"],
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                    "sources": [],
                },
            )
            item["sources"].append(
                {
                    "id": row["source_id"],
                    "document_id": row["document_id"],
                    "filename": row["filename"],
                    "locator": {
                        "kind": row["locator_kind"],
                        "page": row["page_no"],
                        "paragraph_start": row["paragraph_start"],
                        "paragraph_end": row["paragraph_end"],
                    },
                }
            )
        return list(grouped.values())
