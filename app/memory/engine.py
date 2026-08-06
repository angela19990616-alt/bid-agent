from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from psycopg.rows import dict_row

from app.database.db import connect
from app.knowledge.permissions import (
    KnowledgeAccessContext,
    KnowledgePermissionFilter,
)


@dataclass(frozen=True)
class ProposalMemoryMatch:
    memory_id: UUID
    chapter_title: str
    pattern: dict[str, Any]
    score: float
    rationale: str

    def snapshot(self) -> dict[str, Any]:
        return {
            "memory_id": str(self.memory_id),
            "chapter_title": self.chapter_title,
            "pattern": self.pattern,
            "score": self.score,
            "rationale": self.rationale,
            "fact_usage": "prohibited",
        }


class ProposalMemoryValidationError(ValueError):
    pass


class ProposalMemoryEngine:
    """Matches reviewed writing patterns without exposing source prose."""

    def add_pattern(
        self,
        *,
        access_context: KnowledgeAccessContext,
        project_type: str,
        industry: str,
        chapter_title: str,
        pattern: dict[str, Any],
        quality_score: float,
        source_knowledge_id: UUID | None = None,
    ) -> UUID:
        return self.add_patterns(
            access_context=access_context,
            items=[
                {
                    "project_type": project_type,
                    "industry": industry,
                    "chapter_title": chapter_title,
                    "pattern": pattern,
                    "quality_score": quality_score,
                    "source_knowledge_id": source_knowledge_id,
                }
            ],
        )[0]

    def add_patterns(
        self,
        *,
        access_context: KnowledgeAccessContext,
        items: list[dict[str, Any]],
    ) -> list[UUID]:
        """Validate the full batch, then persist it in one transaction."""
        prepared: list[dict[str, Any]] = []
        for item in items:
            pattern = item["pattern"]
            quality_score = float(item["quality_score"])
            if pattern.get("prohibited_fact_copy") is not True:
                raise ProposalMemoryValidationError(
                    "方案记忆必须明确禁止复制历史事实。"
                )
            if not 0 <= quality_score <= 1:
                raise ProposalMemoryValidationError("方案记忆质量分无效。")
            canonical = json.dumps(
                pattern, ensure_ascii=False, sort_keys=True
            )
            prepared.append(
                {
                    **item,
                    "quality_score": quality_score,
                    "canonical": canonical,
                    "checksum": hashlib.sha256(
                        canonical.encode()
                    ).hexdigest(),
                }
            )
        if not prepared:
            return []

        ids: list[UUID] = []
        with connect() as conn:
            with conn.cursor() as cursor:
                for item in prepared:
                    cursor.execute(
                        """
                        INSERT INTO proposal_memory (
                            organization_key, project_type, industry,
                            chapter_title, pattern, source_knowledge_id,
                            quality_score, checksum
                        )
                        VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s, %s)
                        ON CONFLICT (organization_key, checksum) DO UPDATE SET
                            quality_score = GREATEST(
                                proposal_memory.quality_score,
                                EXCLUDED.quality_score
                            ),
                            review_status = 'approved',
                            updated_at = NOW()
                        RETURNING id
                        """,
                        (
                            access_context.organization_key,
                            str(item["project_type"]).strip(),
                            str(item["industry"]).strip(),
                            str(item["chapter_title"]).strip(),
                            item["canonical"],
                            item.get("source_knowledge_id"),
                            item["quality_score"],
                            item["checksum"],
                        ),
                    )
                    ids.append(cursor.fetchone()[0])
        return ids

    def match(
        self,
        *,
        access_context: KnowledgeAccessContext,
        section_title: str,
        requirements: list[dict],
        limit: int = 3,
    ) -> list[ProposalMemoryMatch]:
        permission = KnowledgePermissionFilter(access_context)
        organization_key, allowed_scopes = permission.sql_params
        with connect() as conn:
            with conn.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    """
                    SELECT id, organization_key, project_type, industry,
                           chapter_title, pattern, permission_scope,
                           quality_score
                    FROM proposal_memory
                    WHERE organization_key = %s
                      AND permission_scope = ANY(%s)
                      AND review_status = 'approved'
                    ORDER BY quality_score DESC, updated_at DESC
                    """,
                    (organization_key, allowed_scopes),
                )
                items = [
                    dict(row)
                    for row in cursor.fetchall()
                    if permission.allows(dict(row))
                ]
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
        matches: list[ProposalMemoryMatch] = []
        for item in items:
            pattern_text = json.dumps(
                item["pattern"], ensure_ascii=False
            )
            item_terms = self._terms(
                f"{item['project_type']} {item['industry']} "
                f"{item['chapter_title']} {pattern_text}"
            )
            overlap = query_terms & item_terms
            if not overlap:
                continue
            semantic_score = min(
                1.0,
                len(overlap) / max(3, min(len(query_terms), 40)),
            )
            score = round(
                semantic_score * 0.7
                + float(item["quality_score"]) * 0.3,
                4,
            )
            matches.append(
                ProposalMemoryMatch(
                    memory_id=item["id"],
                    chapter_title=item["chapter_title"],
                    pattern=dict(item["pattern"]),
                    score=score,
                    rationale=(
                        "匹配写作维度："
                        + "、".join(sorted(overlap)[:6])
                    ),
                )
            )
        return sorted(
            matches, key=lambda item: item.score, reverse=True
        )[: max(0, min(limit, 5))]

    @staticmethod
    def _terms(value: str) -> set[str]:
        compact = re.sub(r"\s+", "", value.lower())
        latin = set(re.findall(r"[a-z0-9][a-z0-9_-]{1,}", compact))
        chinese = re.findall(r"[\u4e00-\u9fff]{2,}", compact)
        return latin | {
            token[index : index + size]
            for token in chinese
            for size in (2, 3, 4)
            for index in range(max(0, len(token) - size + 1))
        }
