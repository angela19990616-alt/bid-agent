from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Callable
from uuid import UUID

from psycopg.rows import dict_row

from app.core.scoring_evidence import ScoringEvidencePlanner
from app.database.db import connect


class BidReadinessError(ValueError):
    pass


class BidReadinessService:
    """Build persistent human-review gates around deterministic bid analysis."""

    CATEGORIES = {
        "outline",
        "format",
        "commercial_deviation",
        "scoring_evidence",
        "qualification_material",
    }
    REVIEW_KEY_PREFIXES = {
        "outline": "outline:",
        "format": "format:",
        "commercial_deviation": "deviation:",
        "scoring_evidence": "evidence:",
        "qualification_material": "material:",
    }
    DEVIATION_TERMS = (
        "商务条款偏离表",
        "商务偏离表",
        "商务偏离",
        "无偏离",
        "偏离说明",
    )

    def __init__(
        self,
        *,
        decision_loader: (
            Callable[[UUID], dict[str, dict[str, Any]]] | None
        ) = None,
    ):
        self._decision_loader = decision_loader or self._load_decisions

    def build(
        self,
        *,
        project_id: UUID,
        profile: Any,
        sections: list[dict[str, Any]],
        requirements: list[dict[str, Any]],
        knowledge: list[dict[str, Any]],
        format_requirements: list[dict[str, Any]],
        qualification_responses: list[dict[str, Any]],
        rules: dict[str, Any],
    ) -> dict[str, Any]:
        decisions = self._decision_loader(project_id)
        route = self._compilation_route(profile)
        outline = self._outline_gate(
            profile=profile,
            sections=sections,
            route=route,
            decisions=decisions,
        )
        formats = [
            self._review_item(
                review_key=f"format:{item['requirement_id']}",
                category="format",
                title=item["title"],
                instruction=(
                    "按采购文件原格式复核标题、表格、字体、页眉页脚和固定文字。"
                ),
                payload={
                    "instruction": item.get("instruction"),
                    "fidelity": item.get("fidelity"),
                    "source_text": item.get("source_text"),
                    "sources": item.get("sources") or [],
                },
                decisions=decisions,
                confirmable=True,
                blocking_scope="正式交付",
            )
            for item in format_requirements
            if item.get("manual_check_required")
        ]
        if route["mode"] == "strict_template":
            descriptor = getattr(profile, "template_descriptor", {}) or {}
            formats.insert(
                0,
                self._review_item(
                    review_key="format:template-fidelity",
                    category="format",
                    title="原投标文件格式保真",
                    instruction=(
                        "抽查导出预览中的目录、表格、字体、页眉页脚、分页和固定文字。"
                    ),
                    payload={
                        "mode": "strict_template",
                        "fidelity": descriptor.get("fidelity"),
                        "outline": descriptor.get("outline") or [],
                        "table_count": descriptor.get("table_count", 0),
                        "fonts": descriptor.get("fonts") or [],
                        "header_count": descriptor.get("header_count", 0),
                        "footer_count": descriptor.get("footer_count", 0),
                    },
                    decisions=decisions,
                    confirmable=True,
                    blocking_scope="正式交付",
                ),
            )
        deviations = self._commercial_deviations(
            requirements, decisions
        )
        evidence_plans = ScoringEvidencePlanner.plan(
            requirements, knowledge, rules
        )
        evidence_reviews = []
        grouped_plans: dict[str, list[dict[str, Any]]] = {}
        for plan in evidence_plans:
            grouped_plans.setdefault(plan["criterion_type"], []).append(plan)
        for criterion_type, plans in grouped_plans.items():
            ready = all(
                plan["readiness"] == "ready_for_review" for plan in plans
            )
            blockers = list(dict.fromkeys(
                blocker
                for plan in plans
                if (blocker := self._evidence_blocker(plan))
            ))
            selected_count = sum(
                plan["selected_count"] for plan in plans
            )
            minimum_count = sum(plan["minimum_count"] for plan in plans)
            label = plans[0]["criterion_label"]
            evidence_reviews.append(
                self._review_item(
                    review_key=f"evidence:{criterion_type}",
                    category="scoring_evidence",
                    title=f"{label}（{len(plans)} 个评分事项）",
                    instruction=(
                        f"统一核验本组 {selected_count} 份候选材料及来源；"
                        f"各项满分最低数量合计 {minimum_count} 份，"
                        "实际材料会按评分事项分别去重装配。"
                    ),
                    payload={"criterion_type": criterion_type, "plans": plans},
                    decisions=decisions,
                    confirmable=ready,
                    blocking_scope="本组评分响应",
                    blocker="；".join(blockers) if blockers else None,
                )
            )
        material_reviews = []
        evidence_requirement_ids = {
            plan["requirement_id"] for plan in evidence_plans
        }
        for item in qualification_responses:
            if item["requirement_id"] in evidence_requirement_ids:
                continue
            verified = item.get("status") == "matched_verified"
            material_reviews.append(
                self._review_item(
                    review_key=f"material:{item['requirement_id']}",
                    category="qualification_material",
                    title=item["requirement"],
                    instruction="核验系统匹配的资格或证明材料及原文件位置。",
                    payload={
                        "requirement": item["requirement"],
                        "status": item.get("status"),
                        "matches": item.get("matches") or [],
                    },
                    decisions=decisions,
                    confirmable=verified,
                    blocking_scope="对应资格响应或附件",
                    blocker=(
                        None
                        if verified
                        else "尚未找到同时具备真实文件、来源定位和企业事实核验的材料。"
                    ),
                )
            )
        review_items = [
            outline,
            *formats,
            *deviations,
            *evidence_reviews,
            *material_reviews,
        ]
        writing_blockers = self._writing_blockers(route, outline)
        delivery_blockers = list(writing_blockers)
        for item in review_items:
            if item["category"] == "outline":
                continue
            if item.get("blocker"):
                delivery_blockers.append(item["blocker"])
            elif item["status"] != "confirmed":
                delivery_blockers.append(f"待审核：{item['title']}")
        delivery_blockers = list(dict.fromkeys(delivery_blockers))
        return {
            "compilation_route": route,
            "outline_gate": outline,
            "commercial_deviations": deviations,
            "scoring_evidence_plans": evidence_plans,
            "review_items": review_items,
            "writing_gate": {
                "ready": not writing_blockers,
                "blockers": writing_blockers,
            },
            "delivery_gate": {
                "ready": not delivery_blockers,
                "blockers": delivery_blockers,
                "confirmed": sum(
                    item["status"] == "confirmed" for item in review_items
                ),
                "total": len(review_items),
            },
        }

    def review(
        self,
        project_id: UUID,
        *,
        review_key: str,
        content_hash: str,
        category: str,
        action: str,
        note: str | None = None,
        reviewed_by: str = "workspace_user",
    ) -> None:
        self._validate_review_request(
            review_key, content_hash, category, action
        )
        if action == "reset":
            status = "pending"
            reviewed_at = None
        else:
            status = "confirmed" if action == "confirm" else "rejected"
            reviewed_at = "NOW()"
        with connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    f"""
                    INSERT INTO project_business_reviews (
                        project_id, review_key, content_hash, category,
                        status, decision_note, reviewed_by, reviewed_at
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, {reviewed_at or 'NULL'}
                    )
                    ON CONFLICT (project_id, review_key) DO UPDATE SET
                        content_hash = EXCLUDED.content_hash,
                        category = EXCLUDED.category,
                        status = EXCLUDED.status,
                        decision_note = EXCLUDED.decision_note,
                        reviewed_by = EXCLUDED.reviewed_by,
                        reviewed_at = EXCLUDED.reviewed_at,
                        updated_at = NOW()
                    """,
                    (
                        project_id,
                        review_key,
                        content_hash,
                        category,
                        status,
                        (note or "").strip() or None,
                        reviewed_by,
                    ),
                )

    @classmethod
    def _validate_review_request(
        cls,
        review_key: str,
        content_hash: str,
        category: str,
        action: str,
    ) -> None:
        if category not in cls.CATEGORIES:
            raise BidReadinessError("未知业务审核类型。")
        if not review_key.startswith(cls.REVIEW_KEY_PREFIXES[category]):
            raise BidReadinessError("业务审核事项与类型不匹配。")
        if not re.fullmatch(r"[a-f0-9]{64}", content_hash):
            raise BidReadinessError("业务审核内容校验值无效。")
        if action not in {"confirm", "reset", "reject"}:
            raise BidReadinessError("未知业务审核操作。")

    @staticmethod
    def _compilation_route(profile: Any) -> dict[str, Any]:
        mode = getattr(profile, "generation_mode", "planned")
        if mode == "strict_template":
            return {
                "mode": mode,
                "writer": "strict_template_writer",
                "title": "按采购文件原格式回填",
                "description": "沿用原目录、表格和版式，只写入已核验内容。",
                "source": "采购文件投标文件格式",
            }
        if mode in {"template_conversion_required", "pdf_template_manual_fill"}:
            return {
                "mode": mode,
                "writer": None,
                "title": "PDF 模板转换与结构确认",
                "description": "检测到 PDF 响应格式，须先形成可靠的可编辑模板。",
                "source": "采购文件 PDF 响应格式",
            }
        return {
            "mode": "planned",
            "writer": "planned_proposal_writer",
            "title": "无指定模板，生成响应目录",
            "description": "根据技术要求、评分点和已授权历史结构生成目录。",
            "source": "技术要求与评分办法",
        }

    def _outline_gate(
        self,
        *,
        profile: Any,
        sections: list[dict[str, Any]],
        route: dict[str, Any],
        decisions: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        descriptor = getattr(profile, "template_descriptor", {}) or {}
        template_outline = descriptor.get("outline") or []
        outline = template_outline or [
            {
                "title": section.get("title"),
                "sort_order": section.get("sort_order", index),
            }
            for index, section in enumerate(sections, start=1)
        ]
        structure_available = bool(outline) or route["mode"] == "strict_template"
        return self._review_item(
            review_key="outline:structure",
            category="outline",
            title=(
                "确认采购文件原目录与表格结构"
                if route["mode"] == "strict_template"
                else "确认投标文件目录"
            ),
            instruction=(
                "业务人员确认目录、表格结构和顺序后，系统才能开始编制。"
                if route["mode"] == "strict_template"
                else "业务人员确认目录层级和顺序后，系统才能开始正文编制。"
            ),
            payload={
                "route": route,
                "outline": outline,
                "table_count": descriptor.get("table_count", 0),
                "field_count": descriptor.get("field_count", 0),
            },
            decisions=decisions,
            confirmable=structure_available and route["writer"] is not None,
            blocking_scope="正文编制与正式交付",
            blocker=(
                None
                if structure_available and route["writer"] is not None
                else "尚未形成可确认的投标文件目录。"
            ),
        )

    def _commercial_deviations(
        self,
        requirements: list[dict[str, Any]],
        decisions: dict[str, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        result = []
        for item in requirements:
            text = " ".join(
                str(item.get(key) or "")
                for key in ("title", "normalized_text", "quote")
            )
            if not any(term in text for term in self.DEVIATION_TERMS):
                continue
            result.append(
                self._review_item(
                    review_key=f"deviation:{item['id']}",
                    category="commercial_deviation",
                    title=item.get("title") or "商务条款偏离表",
                    instruction=(
                        "系统建议按“无偏离”准备，但必须由业务人员根据实际履约能力确认。"
                    ),
                    payload={
                        "recommendation": "无偏离（待人工确认）",
                        "source_text": item.get("quote") or text,
                        "sources": item.get("sources") or [],
                    },
                    decisions=decisions,
                    confirmable=True,
                    blocking_scope="商务响应与正式交付",
                )
            )
        return result

    @staticmethod
    def _evidence_blocker(plan: dict[str, Any]) -> str | None:
        if plan["readiness"] == "verified_material_insufficient":
            return (
                f"{plan['title']}：可核验证明材料不足，"
                f"需要至少 {plan['minimum_count']} 份。"
            )
        if plan["readiness"] == "approval_required":
            return f"{plan['title']}：使用合同全页前需完成业务发展部审批。"
        return None

    @staticmethod
    def _writing_blockers(
        route: dict[str, Any], outline: dict[str, Any]
    ) -> list[str]:
        blockers = []
        if route["writer"] is None:
            blockers.append("PDF 响应格式尚未完成可靠转换和结构确认。")
        if outline.get("blocker"):
            blockers.append(outline["blocker"])
        elif outline["status"] != "confirmed":
            blockers.append("投标文件目录尚未人工确认。")
        return list(dict.fromkeys(blockers))

    def _review_item(
        self,
        *,
        review_key: str,
        category: str,
        title: str,
        instruction: str,
        payload: dict[str, Any],
        decisions: dict[str, dict[str, Any]],
        confirmable: bool,
        blocking_scope: str,
        blocker: str | None = None,
    ) -> dict[str, Any]:
        content_hash = self._content_hash(payload)
        stored = decisions.get(review_key) or {}
        status = (
            stored.get("status", "pending")
            if stored.get("content_hash") == content_hash
            else "pending"
        )
        if not confirmable:
            status = "pending"
        return {
            "review_key": review_key,
            "category": category,
            "title": title,
            "instruction": instruction,
            "content_hash": content_hash,
            "status": status,
            "confirmable": confirmable,
            "blocking_scope": blocking_scope,
            "blocker": blocker,
            "decision_note": (
                stored.get("decision_note")
                if stored.get("content_hash") == content_hash else None
            ),
        }

    @staticmethod
    def _content_hash(payload: dict[str, Any]) -> str:
        canonical = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            default=str,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @staticmethod
    def _load_decisions(project_id: UUID) -> dict[str, dict[str, Any]]:
        with connect() as conn:
            with conn.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    """
                    SELECT review_key, content_hash, category, status,
                           decision_note, reviewed_by, reviewed_at
                    FROM project_business_reviews
                    WHERE project_id = %s
                    """,
                    (project_id,),
                )
                return {
                    row["review_key"]: dict(row)
                    for row in cursor.fetchall()
                }
