from __future__ import annotations

from collections import defaultdict
from typing import Any
from uuid import UUID

from psycopg.rows import dict_row

from app.database.db import connect
from app.knowledge.engine import EnterpriseKnowledgeEngine
from app.services.provenance_service import content_paragraphs
from app.services.requirement_service import RequirementService
from app.services.section_service import SectionService


class ResponseSupportService:
    """Builds user-facing response support views from audited source data."""

    STRICT_FORMAT_TERMS = (
        "不得修改", "严格按照", "原格式", "格式不变", "固定格式",
        "按附件", "模板填写", "不得增删", "不得改变",
    )
    TABLE_FORMAT_TERMS = (
        "表格", "表头", "附件", "响应表", "报价表", "一览表",
    )

    def __init__(
        self,
        requirement_service: RequirementService | None = None,
        knowledge_engine: EnterpriseKnowledgeEngine | None = None,
        section_service: SectionService | None = None,
    ):
        self.requirement_service = requirement_service or RequirementService()
        self.knowledge_engine = knowledge_engine or EnterpriseKnowledgeEngine()
        self.section_service = section_service or SectionService()

    def overview(self, project_id: UUID) -> dict[str, Any]:
        requirements = self.requirement_service.list(project_id)
        return {
            "response_groups": self._groups(requirements),
            "format_requirements": self._format_requirements(requirements),
            "qualification_responses": self._qualification_responses(
                project_id, requirements
            ),
            "traceability": self._traceability(project_id, requirements),
        }

    @staticmethod
    def _groups(requirements: list[dict]) -> list[dict[str, Any]]:
        grouped: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
        for item in requirements:
            chapter = item.get("proposal_mapping") or "不进入技术正文"
            key = (item["response_action"], item["type"], chapter)
            grouped[key].append(item)
        result = []
        for (action, requirement_type, chapter), items in grouped.items():
            result.append(
                {
                    "group_key": "|".join((action, requirement_type, chapter)),
                    "response_action": action,
                    "requirement_type": requirement_type,
                    "target_chapter": (
                        None if chapter == "不进入技术正文" else chapter
                    ),
                    "item_count": len(items),
                    "requirement_ids": [str(item["id"]) for item in items],
                    "titles": [item["title"] for item in items],
                    "highest_priority": min(
                        (item.get("priority", "P3") for item in items),
                        key=lambda value: int(value[1]),
                    ),
                    "max_proposal_value": max(
                        (item.get("proposal_value", 0) for item in items),
                        default=0,
                    ),
                }
            )
        return sorted(
            result,
            key=lambda item: (
                int(item["highest_priority"][1]),
                -item["max_proposal_value"],
                item["target_chapter"] or "末尾",
            ),
        )

    def _format_requirements(self, requirements: list[dict]) -> list[dict]:
        items = []
        for requirement in requirements:
            text = (
                f"{requirement.get('normalized_text', '')} "
                f"{requirement.get('quote', '')}"
            )
            is_format = requirement["type"] in {
                "format_requirement", "document_structure_requirement"
            } or any(term in text for term in self.TABLE_FORMAT_TERMS)
            if not is_format:
                continue
            strict = any(term in text for term in self.STRICT_FORMAT_TERMS)
            items.append(
                {
                    "requirement_id": str(requirement["id"]),
                    "title": requirement["title"],
                    "instruction": requirement["normalized_text"],
                    "fidelity": (
                        "exact_template" if strict else "structure_preserved"
                    ),
                    "manual_check_required": strict,
                    "source_text": requirement["quote"],
                    "sources": requirement.get("sources", []),
                }
            )
        return items

    def _qualification_responses(
        self,
        project_id: UUID,
        requirements: list[dict],
    ) -> list[dict]:
        qualification_items = [
            item for item in requirements
            if item["type"] == "qualification_requirement"
            or item["response_action"] == "provide_attachment"
        ]
        if not qualification_items:
            return []
        context = self.knowledge_engine.access_context(project_id)
        knowledge = [
            item for item in self.knowledge_engine.list_active(context)
            if item["category"] in {"qualification", "expert_experience"}
        ]
        result = []
        for requirement in qualification_items:
            requirement_terms = self.knowledge_engine._terms(
                f"{requirement['title']} {requirement['normalized_text']}"
            )
            matches = []
            for item in knowledge:
                overlap = requirement_terms & self.knowledge_engine._terms(
                    f"{item['title']} {item['content']}"
                )
                if not overlap:
                    continue
                metadata = dict(item.get("metadata") or {})
                matches.append(
                    {
                        "knowledge_id": str(item["id"]),
                        "title": item["title"],
                        "category": item["category"],
                        "score": round(
                            min(1.0, len(overlap) / max(3, len(requirement_terms))),
                            4,
                        ),
                        "verified": bool(
                            metadata.get("verified_enterprise_fact", False)
                        ),
                        "holder": metadata.get("holder"),
                        "valid_until": metadata.get("valid_until"),
                        "asset_reference": metadata.get("asset_reference"),
                        "rationale": "匹配字段：" + "、".join(sorted(overlap)[:6]),
                    }
                )
            matches.sort(key=lambda item: item["score"], reverse=True)
            result.append(
                {
                    "requirement_id": str(requirement["id"]),
                    "requirement": requirement["normalized_text"],
                    "source_text": requirement["quote"],
                    "sources": requirement.get("sources", []),
                    "status": (
                        "matched_verified"
                        if any(item["verified"] for item in matches)
                        else "manual_material_required"
                    ),
                    "matches": matches[:5],
                }
            )
        return result

    def _traceability(
        self,
        project_id: UUID,
        requirements: list[dict],
    ) -> dict[str, Any]:
        sections = self.section_service.list(project_id)
        requirement_sections: dict[str, list[str]] = defaultdict(list)
        paragraphs = []
        for section in sections:
            for requirement_id in section.get("requirement_ids", []):
                requirement_sections[str(requirement_id)].append(section["title"])
            version = section.get("current_version")
            if not version:
                continue
            provenance = self._load_provenance(version.get("id"))
            provenance_by_paragraph: dict[int, list[dict]] = defaultdict(list)
            for source in provenance:
                provenance_by_paragraph[source["paragraph_index"]].append(
                    source
                )
            for index, text in enumerate(content_paragraphs(version["content"])):
                paragraphs.append(
                    {
                        "section_id": str(section["id"]),
                        "section_title": section["title"],
                        "paragraph_index": index,
                        "generated_text": text,
                        "origin": version["origin"],
                        "sources": provenance_by_paragraph.get(index, []),
                    }
                )
        return {
            "requirements": [
                {
                    "requirement_id": str(item["id"]),
                    "title": item["title"],
                    "source_text": item["quote"],
                    "sources": item.get("sources", []),
                    "response_action": item["response_action"],
                    "generated_sections": requirement_sections.get(
                        str(item["id"]), []
                    ),
                }
                for item in requirements
            ],
            "generated_paragraphs": paragraphs,
        }

    @staticmethod
    def _load_provenance(version_id: UUID | None) -> list[dict]:
        if version_id is None:
            return []
        with connect() as conn:
            with conn.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    """
                    SELECT paragraph_index, source_type, source_title,
                           source_location, source_excerpt,
                           usage_description, verification_status,
                           confidence
                    FROM content_provenance
                    WHERE section_version_id = %s
                    ORDER BY paragraph_index, created_at
                    """,
                    (version_id,),
                )
                return [dict(row) for row in cursor.fetchall()]
