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
        replace_source_pairs: bool = False,
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
                if replace_source_pairs:
                    source_pairs = sorted(
                        {
                            str(item["pattern"].get("source_pair_checksum"))
                            for item in prepared
                            if item["pattern"].get("source_pair_checksum")
                        }
                    )
                    if source_pairs:
                        cursor.execute(
                            """
                            UPDATE proposal_memory
                            SET review_status = 'retired', updated_at = NOW()
                            WHERE organization_key = %s
                              AND pattern->>'source_pair_checksum' = ANY(%s)
                            """,
                            (access_context.organization_key, source_pairs),
                        )
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
            context_terms = self._terms(
                f"{item['project_type']} {item['industry']}"
            )
            structure_terms = self._terms(
                f"{item['chapter_title']} {pattern_text}"
            )
            context_overlap = query_terms & context_terms
            structure_overlap = query_terms & structure_terms
            overlap = context_overlap | structure_overlap
            if not overlap:
                continue
            context_score = min(
                1.0,
                len(context_overlap) / max(2, min(len(context_terms), 12)),
            )
            structure_score = min(
                1.0,
                len(structure_overlap) / max(3, min(len(query_terms), 24)),
            )
            generic_penalty = (
                0.08 if item["chapter_title"] == "通用响应章节" else 0
            )
            proposal_query = bool(
                query_terms
                & self._terms(
                    "方案 实施 计划 组织 进度 质量 验收 培训 运维 安全"
                )
            )
            evidence_penalty = (
                0.22
                if proposal_query
                and item["chapter_title"]
                in {
                    "响应函", "授权委托", "报价文件", "资格证明",
                    "业绩证明", "人员材料", "资质证明", "证明材料",
                    "企业介绍", "商务响应表", "技术响应表",
                }
                else 0
            )
            core_proposal_bonus = (
                0.08
                if proposal_query
                and item["chapter_title"]
                in {
                    "方案正文", "项目理解", "总体思路", "技术方案",
                    "实施计划", "进度安排", "组织管理", "人员配置",
                    "质量保障", "验收方案", "培训方案", "运维服务",
                    "安全方案", "应急预案",
                }
                else 0
            )
            peripheral_penalty = (
                0.12
                if proposal_query
                and not structure_overlap
                and item["chapter_title"]
                in {"保密承诺", "服务承诺", "其他响应材料"}
                else 0
            )
            score = round(
                context_score * 0.5
                + structure_score * 0.3
                + float(item["quality_score"]) * 0.2
                + core_proposal_bonus
                - generic_penalty
                - evidence_penalty
                - peripheral_penalty,
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
        ranked = sorted(matches, key=lambda item: item.score, reverse=True)
        deduplicated: list[ProposalMemoryMatch] = []
        seen: set[str] = set()
        for match in ranked:
            signature = "|".join(
                (
                    str(match.pattern.get("source_pair_checksum") or ""),
                    match.chapter_title,
                )
            )
            if signature in seen:
                continue
            seen.add(signature)
            deduplicated.append(match)
        if not deduplicated:
            return []
        relative_floor = deduplicated[0].score * 0.75
        relevant = [
            item for item in deduplicated if item.score >= relative_floor
        ]
        return relevant[: max(0, min(limit, 5))]

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
