from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from app.database.db import connect
from app.knowledge.engine import KnowledgeMatch


SOURCE_TYPES = {
    "procurement_document",
    "requirement",
    "scoring_criterion",
    "enterprise_knowledge",
    "historical_case",
    "regulation_policy",
    "user_confirmed",
    "model_inference",
    "unknown",
}


@dataclass(frozen=True)
class ProvenanceRecord:
    paragraph_id: str
    paragraph_index: int
    source_type: str
    source_id: str | None
    source_title: str
    source_location: str | None
    source_excerpt: str | None
    usage_description: str
    verification_status: str
    confidence: float
    generated_section: str


def content_paragraphs(content: str) -> list[str]:
    return [
        line.strip()
        for line in content.splitlines()
        if line.strip() and not re.fullmatch(r"[-*_]{3,}", line.strip())
    ]


def paragraph_key(index: int, text: str) -> str:
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
    return f"P{index + 1:04d}-{digest}"


def terms(value: str) -> set[str]:
    compact = re.sub(r"\s+", "", value.lower())
    latin = set(re.findall(r"[a-z0-9][a-z0-9_-]{1,}", compact))
    chinese = re.findall(r"[\u4e00-\u9fff]{2,}", compact)
    return latin | {
        token[index : index + size]
        for token in chinese
        for size in (2, 3, 4)
        for index in range(max(0, len(token) - size + 1))
    }


class ProvenanceService:
    @staticmethod
    def build(
        *,
        section_title: str,
        content: str,
        requirements: list[dict],
        matches: list[KnowledgeMatch],
        origin: str = "generated",
    ) -> tuple[list[ProvenanceRecord], list[dict[str, Any]]]:
        records: list[ProvenanceRecord] = []
        case_usage: list[dict[str, Any]] = []
        seen_cases: set[UUID] = set()
        for index, paragraph in enumerate(content_paragraphs(content)):
            paragraph_id = paragraph_key(index, paragraph)
            paragraph_terms = terms(paragraph)
            linked = False
            for item in requirements:
                evidence = (
                    f"{item.get('title', '')} "
                    f"{item.get('normalized_text', '')} "
                    f"{item.get('quote', '')}"
                )
                overlap = paragraph_terms & terms(evidence)
                if len(overlap) < 2:
                    continue
                requirement_type = item.get("type", "technical")
                source_type = (
                    "scoring_criterion"
                    if requirement_type in {
                        "scoring", "scoring_requirement"
                    }
                    else "requirement"
                )
                records.append(
                    ProvenanceRecord(
                        paragraph_id=paragraph_id,
                        paragraph_index=index,
                        source_type=source_type,
                        source_id=str(item.get("id")) if item.get("id") else None,
                        source_title=item.get("title")
                        or item.get("normalized_text", "采购要求")[:80],
                        source_location=_requirement_location(item),
                        source_excerpt=item.get("quote", "")[:500] or None,
                        usage_description="响应采购要求",
                        verification_status="verified",
                        confidence=min(0.99, 0.65 + len(overlap) * 0.03),
                        generated_section=section_title,
                    )
                )
                linked = True
            for match in matches:
                overlap = paragraph_terms & terms(
                    f"{match.title} {match.content}"
                )
                if len(overlap) < 3:
                    continue
                historical = match.category in {
                    "historical_bid", "case_study"
                }
                verified = bool(
                    match.metadata.get("verified_enterprise_fact", False)
                )
                records.append(
                    ProvenanceRecord(
                        paragraph_id=paragraph_id,
                        paragraph_index=index,
                        source_type=(
                            "historical_case"
                            if historical
                            else "enterprise_knowledge"
                        ),
                        source_id=str(match.knowledge_id),
                        source_title=match.title,
                        source_location=match.metadata.get("source_location"),
                        source_excerpt=match.content[:500],
                        usage_description=(
                            "历史案例结构或表达参考"
                            if historical
                            else "企业知识内容引用"
                        ),
                        verification_status=(
                            "verified" if verified else "unverified"
                        ),
                        confidence=match.score,
                        generated_section=section_title,
                    )
                )
                linked = True
                if historical and match.knowledge_id not in seen_cases:
                    seen_cases.add(match.knowledge_id)
                    case_usage.append(
                        {
                            "knowledge_id": match.knowledge_id,
                            "case_title": match.title,
                            "section_title": section_title,
                            "content_summary": paragraph[:300],
                            "usage_type": "structure_reference",
                            "adapted_for_current_project": True,
                            "contains_enterprise_fact": (
                                _looks_like_enterprise_fact(paragraph)
                            ),
                            "enterprise_fact_verified": verified,
                            "allowed_in_final": not _looks_like_enterprise_fact(
                                paragraph
                            ),
                        }
                    )
            if not linked:
                records.append(
                    ProvenanceRecord(
                        paragraph_id=paragraph_id,
                        paragraph_index=index,
                        source_type=(
                            "user_confirmed"
                            if origin == "edited"
                            else "model_inference"
                        ),
                        source_id=None,
                        source_title=(
                            "用户人工编辑"
                            if origin == "edited"
                            else "模型生成内容"
                        ),
                        source_location=None,
                        source_excerpt=None,
                        usage_description=(
                            "用户确认的人工内容"
                            if origin == "edited"
                            else "未直接匹配到输入证据的生成内容"
                        ),
                        verification_status=(
                            "user_confirmed"
                            if origin == "edited"
                            else "unverified"
                        ),
                        confidence=1.0 if origin == "edited" else 0.35,
                        generated_section=section_title,
                    )
                )
        return records, case_usage

    @staticmethod
    def persist(
        version_id: UUID,
        records: list[ProvenanceRecord],
        case_usage: list[dict[str, Any]],
    ) -> None:
        with connect() as conn:
            with conn.cursor() as cursor:
                cursor.executemany(
                    """
                    INSERT INTO content_provenance (
                        section_version_id, paragraph_id, paragraph_index,
                        source_type, source_id, source_title,
                        source_location, source_excerpt, usage_description,
                        verification_status, confidence, generated_section
                    )
                    VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                    )
                    ON CONFLICT DO NOTHING
                    """,
                    [
                        (
                            version_id,
                            item.paragraph_id,
                            item.paragraph_index,
                            item.source_type,
                            item.source_id,
                            item.source_title,
                            item.source_location,
                            item.source_excerpt,
                            item.usage_description,
                            item.verification_status,
                            item.confidence,
                            item.generated_section,
                        )
                        for item in records
                    ],
                )
                cursor.executemany(
                    """
                    INSERT INTO historical_case_usage (
                        section_version_id, knowledge_id, case_title,
                        section_title, content_summary, usage_type,
                        adapted_for_current_project, contains_enterprise_fact,
                        enterprise_fact_verified, allowed_in_final
                    )
                    VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                    )
                    """,
                    [
                        (
                            version_id,
                            item["knowledge_id"],
                            item["case_title"],
                            item["section_title"],
                            item["content_summary"],
                            item["usage_type"],
                            item["adapted_for_current_project"],
                            item["contains_enterprise_fact"],
                            item["enterprise_fact_verified"],
                            item["allowed_in_final"],
                        )
                        for item in case_usage
                    ],
                )


def _requirement_location(item: dict) -> str | None:
    if item.get("source_location"):
        return str(item["source_location"])
    sources = item.get("sources") or []
    if not sources:
        return None
    source = sources[0]
    locator = source.get("locator", {})
    if locator.get("kind") == "page":
        return f"{source.get('filename', '采购文件')}，第 {locator.get('page')} 页"
    start = locator.get("paragraph_start")
    end = locator.get("paragraph_end")
    suffix = f"第 {start} 段" if start == end else f"第 {start}-{end} 段"
    return f"{source.get('filename', '采购文件')}，{suffix}"


def _looks_like_enterprise_fact(value: str) -> bool:
    patterns = (
        "法定代表人", "成立于", "注册资本", "员工", "项目数量",
        "合同金额", "中标", "获奖", "市场排名", "我公司拥有",
    )
    return any(item in value for item in patterns)
