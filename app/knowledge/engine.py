from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

from psycopg.rows import dict_row

from app.database.db import connect
from app.services.document_service import extract_text, parse_document
from app.rules.engine import RuleDocument, RuleEngine


KNOWLEDGE_CATEGORIES = {
    "company_profile",
    "qualification",
    "product_capability",
    "technical_capability",
    "case_study",
    "standard_template",
    "expert_experience",
    "historical_bid",
    "common_chapter",
}


@dataclass(frozen=True)
class KnowledgeMatch:
    knowledge_id: UUID
    category: str
    title: str
    content: str
    score: float
    rationale: str
    metadata: dict[str, Any]

    def snapshot(self) -> dict[str, Any]:
        return {
            "knowledge_id": str(self.knowledge_id),
            "category": self.category,
            "title": self.title,
            "score": self.score,
            "rationale": self.rationale,
        }


class KnowledgeValidationError(ValueError):
    pass


class EnterpriseKnowledgeEngine:
    """Loads all eligible private knowledge before deterministic matching."""

    def list_active(self) -> list[dict]:
        with connect() as conn:
            with conn.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    """
                    SELECT enterprise_knowledge.id,
                           enterprise_knowledge.category,
                           enterprise_knowledge.title,
                           enterprise_knowledge.content,
                           enterprise_knowledge.metadata,
                           enterprise_knowledge.source_document_id,
                           documents.project_id AS source_project_id,
                           enterprise_knowledge.permission_scope,
                           enterprise_knowledge.version,
                           enterprise_knowledge.checksum
                    FROM enterprise_knowledge
                    LEFT JOIN documents
                      ON documents.id = enterprise_knowledge.source_document_id
                    WHERE enterprise_knowledge.organization_key = 'default'
                      AND enterprise_knowledge.status = 'active'
                      AND enterprise_knowledge.permission_scope =
                          'organization_private'
                    ORDER BY enterprise_knowledge.category,
                             enterprise_knowledge.updated_at DESC
                    """
                )
                return [dict(row) for row in cursor.fetchall()]

    def list_summaries(self) -> list[dict]:
        return [
            {
                key: item[key]
                for key in (
                    "id",
                    "category",
                    "title",
                    "metadata",
                    "permission_scope",
                    "version",
                    "checksum",
                )
            }
            | {"text_chars": len(item["content"])}
            for item in self.list_active()
        ]

    def add(
        self,
        category: str,
        title: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict:
        if category not in KNOWLEDGE_CATEGORIES:
            raise KnowledgeValidationError("不支持的企业知识分类。")
        clean_title = title.strip()
        clean_content = content.strip()
        if not clean_title or len(clean_content) < 10:
            raise KnowledgeValidationError("企业知识标题或内容过短。")
        checksum = hashlib.sha256(clean_content.encode()).hexdigest()
        with connect() as conn:
            with conn.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    """
                    INSERT INTO enterprise_knowledge (
                        category, title, content, metadata, checksum
                    )
                    VALUES (%s, %s, %s, %s::jsonb, %s)
                    RETURNING id, category, title, content, metadata,
                              permission_scope, status, version,
                              checksum, created_at, updated_at
                    """,
                    (
                        category,
                        clean_title,
                        clean_content,
                        json.dumps(
                            metadata or {}, ensure_ascii=False
                        ),
                        checksum,
                    ),
                )
                return dict(cursor.fetchone())

    def import_document(
        self,
        filename: str,
        content: bytes,
        *,
        source_role: str = "response_content",
    ) -> dict:
        clean_filename = Path(filename).name
        if len(content) > 20 * 1024 * 1024:
            raise KnowledgeValidationError("历史知识文件超过20MB。")
        source_sha256 = hashlib.sha256(content).hexdigest()
        segments = parse_document(clean_filename, content)
        text = extract_text(clean_filename, content)
        if len(text) > 500_000:
            raise KnowledgeValidationError("历史知识文档正文超过50万字。")
        with connect() as conn:
            with conn.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    """
                    SELECT id, category, title, metadata, permission_scope,
                           status, version, checksum,
                           LENGTH(content) AS text_chars
                    FROM enterprise_knowledge
                    WHERE organization_key = 'default'
                      AND metadata->>'source_sha256' = %s
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                    (source_sha256,),
                )
                existing = cursor.fetchone()
                if existing:
                    return {
                        **dict(existing),
                        "segment_count": len(segments),
                        "import_status": "duplicate",
                    }
                metadata = {
                    "origin": "uploaded_private_document",
                    "usage": "private_rag_only",
                    "public_training": False,
                    "verified_enterprise_fact": False,
                    "source_sha256": source_sha256,
                    "source_extension": Path(clean_filename).suffix.lower(),
                    "source_role": source_role,
                }
                checksum = hashlib.sha256(text.encode()).hexdigest()
                cursor.execute(
                    """
                    INSERT INTO enterprise_knowledge (
                        category, title, content, metadata, checksum
                    )
                    VALUES (
                        'historical_bid', %s, %s, %s::jsonb, %s
                    )
                    RETURNING id, category, title, metadata,
                              permission_scope, status, version, checksum,
                              LENGTH(content) AS text_chars
                    """,
                    (
                        Path(clean_filename).stem,
                        text,
                        json.dumps(metadata, ensure_ascii=False),
                        checksum,
                    ),
                )
                return {
                    **dict(cursor.fetchone()),
                    "segment_count": len(segments),
                    "import_status": "created",
                }

    def match(
        self,
        *,
        section_title: str,
        requirements: list[dict],
        limit: int = 8,
        exclude_document_ids: set[UUID] | None = None,
        exclude_project_id: UUID | None = None,
        rules: RuleDocument | None = None,
    ) -> list[KnowledgeMatch]:
        # Loading is intentionally completed before matching/writing.
        active = rules or RuleEngine().load("knowledge")
        matching = active.content["matching"]
        limit = min(limit, int(matching["max_matches"]))
        knowledge_items = self.list_active()
        query = " ".join(
            [
                section_title,
                *[
                    f"{item.get('title', '')} "
                    f"{item.get('normalized_text', '')}"
                    for item in requirements
                ],
            ]
        )
        query_terms = self._terms(query)
        matches: list[KnowledgeMatch] = []
        for item in knowledge_items:
            source_document_id = (
                item.get("source_document_id")
                or item["metadata"].get("document_id")
            )
            if source_document_id and exclude_document_ids:
                if str(source_document_id) in {
                    str(value) for value in exclude_document_ids
                }:
                    continue
            if (
                exclude_project_id
                and item.get("source_project_id") == exclude_project_id
            ):
                continue
            item_terms = self._terms(
                f"{item['title']} {item['content']}"
            )
            overlap = query_terms & item_terms
            if not overlap:
                continue
            query_coverage = min(
                1.0,
                len(overlap)
                / max(
                    4,
                    min(
                        len(query_terms),
                        int(matching["query_term_cap"]),
                    ),
                ),
            )
            item_coverage = min(
                1.0,
                len(overlap)
                / max(
                    4,
                    min(
                        len(item_terms),
                        int(matching["item_term_cap"]),
                    ),
                ),
            )
            source_role = item["metadata"].get(
                "source_role", "unspecified"
            )
            chapter_keywords = matching[
                "source_role_chapter_keywords"
            ].get(
                source_role,
                matching["source_role_chapter_keywords"]["unspecified"],
            )
            if "*" not in chapter_keywords and not any(
                keyword in section_title for keyword in chapter_keywords
            ):
                continue
            role_weight = float(
                matching["source_role_weights"].get(
                    source_role,
                    matching["source_role_weights"]["unspecified"],
                )
            )
            score = (
                query_coverage
                * float(matching["query_coverage_weight"])
                + item_coverage
                * float(matching["item_coverage_weight"])
            ) * role_weight
            if score < float(matching["minimum_score"]):
                continue
            matches.append(
                KnowledgeMatch(
                    knowledge_id=item["id"],
                    category=item["category"],
                    title=item["title"],
                    content=item["content"],
                    score=round(score, 4),
                    rationale=(
                        "匹配术语：" + "、".join(sorted(overlap)[:8])
                    ),
                    metadata=dict(item["metadata"]),
                )
            )
        return sorted(matches, key=lambda item: item.score, reverse=True)[
            :limit
        ]

    @staticmethod
    def _terms(value: str) -> set[str]:
        compact = re.sub(r"\s+", "", value.lower())
        latin = set(re.findall(r"[a-z0-9][a-z0-9_-]{1,}", compact))
        chinese = re.findall(r"[\u4e00-\u9fff]{2,}", compact)
        ngrams = {
            token[index : index + size]
            for token in chinese
            for size in (2, 3, 4)
            for index in range(max(0, len(token) - size + 1))
        }
        return latin | ngrams


class KnowledgeMatchRepository:
    @staticmethod
    def save(
        workflow_run_id: UUID,
        section_id: UUID,
        requirements: list[dict],
        matches: list[KnowledgeMatch],
    ) -> None:
        with connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    DELETE FROM knowledge_matches
                    WHERE workflow_run_id = %s AND section_id = %s
                    """,
                    (workflow_run_id, section_id),
                )
                rows = []
                for match in matches:
                    linked = [
                        item["id"]
                        for item in requirements
                        if EnterpriseKnowledgeEngine._terms(
                            f"{item.get('title', '')} "
                            f"{item.get('normalized_text', '')}"
                        )
                        & EnterpriseKnowledgeEngine._terms(
                            f"{match.title} {match.content}"
                        )
                    ] or [None]
                    rows.extend(
                        (
                            workflow_run_id,
                            section_id,
                            requirement_id,
                            match.knowledge_id,
                            match.score,
                            match.rationale,
                        )
                        for requirement_id in linked
                    )
                cursor.executemany(
                    """
                    INSERT INTO knowledge_matches (
                        workflow_run_id, section_id, requirement_id,
                        knowledge_id, score, rationale
                    )
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT DO NOTHING
                    """,
                    rows,
                )
