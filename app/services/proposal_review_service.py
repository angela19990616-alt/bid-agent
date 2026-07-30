from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from psycopg.rows import dict_row

from app.config.settings import settings
from app.database.db import connect
from app.rules.engine import RuleDocument, RuleEngine
from app.services.provenance_service import (
    ProvenanceService,
    content_paragraphs,
    terms,
)
from app.workflows.controlled_pipeline import ControlledPipeline


UUID_PATTERN = re.compile(
    r"\b[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}\b"
)
INTERNAL_PATTERN = re.compile(
    r"\b(requirement_id|section_id|project_id|database_id|"
    r"source_chunk_id|workflow_run_id|debug|traceback)\b",
    re.IGNORECASE,
)
SECRET_PATTERN = re.compile(
    r"(api[_-]?key|access[_-]?token|secret)\s*[:=]\s*\S+",
    re.IGNORECASE,
)
class ProposalReviewService:
    def __init__(self, rule_engine: RuleEngine | None = None):
        self.rule_engine = rule_engine or RuleEngine()

    def prepare_for_export(self, project_id: UUID) -> dict[str, Any]:
        rules = self.rule_engine.load("compliance")
        pipeline = ControlledPipeline()
        try:
            run_id = pipeline.latest(project_id)
        except ValueError:
            run_id = pipeline.start(project_id)
        initial_input = self._load_review_input(project_id)
        if self._ensure_current_provenance(initial_input):
            initial_input = self._load_review_input(project_id)
        pipeline.record(
            run_id, "proposal_review", rule_snapshot=rules.snapshot()
        )
        initial = self.review(initial_input, rules, phase="initial")
        self._persist_review(project_id, initial)
        pipeline.record(run_id, "auto_fix")
        fixed_sections = {
            item["section_id"]: self.auto_fix(
                item["content"],
                item.get("provenance", []),
                rules,
            )
            for item in initial_input["sections"]
        }
        self._persist_auto_fixes(project_id, initial_input, fixed_sections)
        final_input = self._load_review_input(project_id)
        pipeline.record(run_id, "final_review")
        final = self.review(final_input, rules, phase="final")
        self._persist_review(project_id, final)
        pipeline.record(
            run_id,
            "deliverability_gate",
            details={
                "passed": final["overall"]["recommended_for_delivery"]
            },
        )
        return final

    @staticmethod
    def _ensure_current_provenance(data: dict[str, Any]) -> bool:
        requirement_by_public = {
            item["public_key"]: item for item in data["requirements"]
        }
        changed = False
        for section in data["sections"]:
            if (
                section.get("provenance")
                or not section.get("current_version_id")
                or not section.get("content")
            ):
                continue
            requirements = [
                requirement_by_public[key]
                for key in section.get("requirement_public_keys", [])
                if key in requirement_by_public
            ]
            records, usage = ProvenanceService.build(
                section_title=section["title"],
                content=section["content"],
                requirements=requirements,
                matches=[],
                origin="generated",
            )
            ProvenanceService.persist(
                section["current_version_id"], records, usage
            )
            changed = True
        return changed

    @classmethod
    def review(
        cls,
        data: dict[str, Any],
        rules: RuleDocument | None = None,
        *,
        phase: str = "final",
    ) -> dict[str, Any]:
        active = rules or RuleEngine().load_default("compliance")
        truth_rules = active.content.get("truth_review", {})
        language_rules = active.content.get("language_review", {})
        enterprise_patterns = tuple(
            truth_rules.get("high_risk_enterprise_facts", [])
        )
        project_specific_patterns = tuple(
            truth_rules.get("unverified_project_specifics", [])
        )
        ai_style_terms = tuple(
            language_rules.get("discouraged_slogans", [])
        )
        mechanical_labels = tuple(
            language_rules.get("mechanical_template_labels", [])
        )
        sections = data.get("sections", [])
        requirements = data.get("requirements", [])
        all_paragraphs = [
            (section, index, paragraph)
            for section in sections
            for index, paragraph in enumerate(
                content_paragraphs(section.get("content", ""))
            )
        ]
        provenance_by_section = {
            str(section.get("section_id")): section.get("provenance", [])
            for section in sections
        }
        requirement_coverage = []
        scoring_coverage = []
        for item in requirements:
            mapped = [
                section
                for section in sections
                if item.get("public_key") in section.get(
                    "requirement_public_keys", []
                )
            ]
            best_overlap = max(
                (
                    len(
                        terms(section.get("content", ""))
                        & terms(
                            f"{item.get('title', '')} "
                            f"{item.get('normalized_text', '')}"
                        )
                    )
                    for section in mapped
                ),
                default=0,
            )
            if not mapped:
                status = "not_covered"
            elif best_overlap >= 5:
                status = "fully_covered"
            elif best_overlap >= 3:
                status = "partially_covered"
            else:
                status = "weakly_covered"
            coverage_item = {
                "requirement": item.get("normalized_text")
                or item.get("title", "采购要求"),
                "source_location": item.get("source_location")
                or "采购文件来源已记录",
                "covered": status in {
                    "fully_covered", "partially_covered"
                },
                "generated_sections": [
                    section.get("title") for section in mapped
                ],
                "coverage_method": "章节映射与正文语义词项匹配",
                "coverage_status": status,
                "risk": (
                    "无明显缺口"
                    if status == "fully_covered"
                    else "响应可能不充分"
                ),
                "recommendation": (
                    "保持现有响应"
                    if status == "fully_covered"
                    else "补充采购要求中的可核验响应内容"
                ),
            }
            requirement_coverage.append(coverage_item)
            if item.get("type") in {"scoring", "scoring_requirement"}:
                score_match = re.search(
                    r"(\d+(?:\.\d+)?)\s*分",
                    f"{item.get('title', '')} {item.get('normalized_text', '')}",
                )
                scoring_coverage.append(
                    {
                        "scoring_item": coverage_item["requirement"],
                        "points": (
                            float(score_match.group(1))
                            if score_match
                            else None
                        ),
                        "scoring_requirement": item.get(
                            "normalized_text", ""
                        ),
                        "response_sections": coverage_item[
                            "generated_sections"
                        ],
                        "coverage_status": status,
                        "expected_score_basis": (
                            "正文已形成可追溯响应"
                            if status == "fully_covered"
                            else "当前依据不足，不能估计得分"
                        ),
                        "missing_content": (
                            ""
                            if status == "fully_covered"
                            else "需补充评分要求中的证明或响应内容"
                        ),
                        "risk_level": (
                            "low"
                            if status == "fully_covered"
                            else "high"
                        ),
                        "recommendation": coverage_item["recommendation"],
                    }
                )
        truth_privacy: list[dict[str, Any]] = []
        style_findings: list[dict[str, Any]] = []
        tracked_paragraphs = 0
        verified_enterprise = 0
        enterprise_total = 0
        knowledge_usage: list[dict[str, Any]] = []
        for section, index, paragraph in all_paragraphs:
            traces = [
                item
                for item in provenance_by_section.get(
                    str(section.get("section_id")), []
                )
                if item.get("paragraph_index") == index
            ]
            verified = any(
                item.get("verification_status")
                in {"verified", "user_confirmed"}
                for item in traces
            )
            if traces:
                tracked_paragraphs += 1
            for trace in traces:
                knowledge_usage.append(
                    {
                        "source_type": trace.get("source_type", "unknown"),
                        "source": trace.get("source_title", "来源未知"),
                        "usage_location": section.get("title"),
                        "usage_summary": trace.get(
                            "usage_description", "内容参考"
                        ),
                        "verification_status": trace.get(
                            "verification_status", "unverified"
                        ),
                        "allowed_in_final": trace.get(
                            "verification_status"
                        ) in {"verified", "user_confirmed"},
                    }
                )
            if UUID_PATTERN.search(paragraph):
                truth_privacy.append(
                    cls._risk(
                        "内部 UUID 泄露",
                        section.get("title"),
                        "内部系统标识",
                        "blocking",
                        True,
                        "删除内部标识并替换为人类可读来源名称",
                        "自动替换",
                    )
                )
            if INTERNAL_PATTERN.search(paragraph):
                truth_privacy.append(
                    cls._risk(
                        "内部系统字段泄露",
                        section.get("title"),
                        "内部系统",
                        "blocking",
                        True,
                        "删除数据库字段或调试信息",
                        "自动删除",
                    )
                )
            if SECRET_PATTERN.search(paragraph):
                truth_privacy.append(
                    cls._risk(
                        "疑似密钥或令牌泄露",
                        section.get("title"),
                        "敏感信息",
                        "blocking",
                        True,
                        "立即删除敏感内容并轮换凭据",
                        "自动删除",
                    )
                )
            enterprise_hits = [
                pattern
                for pattern in enterprise_patterns
                if pattern in paragraph
            ]
            if enterprise_hits:
                enterprise_total += 1
                if verified:
                    verified_enterprise += 1
                else:
                    truth_privacy.append(
                        cls._risk(
                            f"未经核验的企业事实：{enterprise_hits[0]}",
                            section.get("title"),
                            "来源未知或未核验",
                            "blocking",
                            True,
                            "删除，或由用户提供可信资料后确认",
                            "自动删除",
                        )
                    )
            for pattern in project_specific_patterns:
                if pattern in paragraph and not verified:
                    truth_privacy.append(
                        cls._risk(
                            f"无可靠来源的项目事实或承诺：{pattern}",
                            section.get("title"),
                            "模型推断",
                            "blocking",
                            True,
                            "删除或改为待确认风险项，不得补造来源",
                            "自动删除",
                        )
                    )
            symbol_count = sum(
                paragraph.count(symbol)
                for symbol in ("✅", "✔", "➡", "→", "★", "⭐", "🔹")
            )
            if symbol_count:
                style_findings.append(
                    cls._style(
                        section.get("title"),
                        "机器化装饰符号",
                        "删除 Emoji、箭头和对勾，改用正式文字。",
                    )
                )
            slogans = [term for term in ai_style_terms if term in paragraph]
            if slogans:
                style_findings.append(
                    cls._style(
                        section.get("title"),
                        f"口号化表达：{'、'.join(slogans)}",
                        "改为具体、可验证且克制的陈述。",
                    )
                )
        for section in sections:
            content = section.get("content", "")
            mechanical_count = sum(
                1 for label in mechanical_labels if label in content
            )
            if mechanical_count >= 4:
                style_findings.append(
                    cls._style(
                        section.get("title"),
                        "机械重复固定小节模板",
                        "根据章节内容改用工作目标、主要工作、阶段成果或配合事项等自然结构。",
                    )
                )
        total_requirements = len(requirement_coverage)
        covered_requirements = sum(
            item["covered"] for item in requirement_coverage
        )
        total_scoring = len(scoring_coverage)
        covered_scoring = sum(
            item["coverage_status"] == "fully_covered"
            for item in scoring_coverage
        )
        total_paragraphs = len(all_paragraphs)
        traceability_rate = (
            tracked_paragraphs / total_paragraphs
            if total_paragraphs
            else 0.0
        )
        enterprise_verification_rate = (
            verified_enterprise / enterprise_total
            if enterprise_total
            else 1.0
        )
        blocking = sum(
            item["blocks_delivery"] for item in truth_privacy
        )
        high_risk = sum(
            item["risk_level"] in {"blocking", "high"}
            for item in truth_privacy
        )
        gate = active.content.get("deliverability_gate", {})
        min_requirement = float(
            gate.get("minimum_requirement_coverage", 0.9)
        )
        min_scoring = float(
            gate.get("minimum_scoring_coverage", 1.0)
        )
        min_traceability = float(
            gate.get("minimum_traceability_rate", 0.8)
        )
        requirement_rate = (
            covered_requirements / total_requirements
            if total_requirements
            else 1.0
        )
        scoring_rate = (
            covered_scoring / total_scoring if total_scoring else 1.0
        )
        gate_checks = {
            "no_blocking_truth_risk": blocking == 0,
            "no_internal_identifier_leak": not any(
                item["risk_description"].startswith("内部")
                for item in truth_privacy
            ),
            "no_sensitive_information_leak": not any(
                "密钥" in item["risk_description"]
                for item in truth_privacy
            ),
            "no_unverified_high_risk_enterprise_fact": (
                enterprise_verification_rate == 1.0
            ),
            "critical_requirement_coverage": (
                requirement_rate >= min_requirement
            ),
            "mandatory_scoring_coverage": scoring_rate >= min_scoring,
            "traceability_threshold": (
                traceability_rate >= min_traceability
            ),
            "review_completed": True,
            "auto_fix_recheck_completed": phase == "final",
        }
        recommended = all(gate_checks.values())
        report = {
            "schema_version": "1.0",
            "phase": phase,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "overall": {
                "recommended_for_delivery": recommended,
                "has_blocking_risk": blocking > 0,
                "requirement_coverage_rate": round(requirement_rate, 4),
                "scoring_coverage_rate": round(scoring_rate, 4),
                "traceability_rate": round(traceability_rate, 4),
                "enterprise_fact_verification_rate": round(
                    enterprise_verification_rate, 4
                ),
                "unverified_assertion_count": sum(
                    item.get("verification_status") == "unverified"
                    for item in knowledge_usage
                ),
                "internal_identifier_leak_count": sum(
                    item["risk_description"].startswith("内部")
                    for item in truth_privacy
                ),
                "high_risk_count": high_risk,
                "blocking_risk_count": blocking,
            },
            "classification_quality": data.get(
                "classification_quality",
                {
                    "quality_rate": 1.0,
                    "total_count": len(data["requirements"]),
                    "high_confidence_ratio": 1.0,
                    "low_confidence_count": 0,
                    "unmapped_count": 0,
                    "conflict_count": 0,
                },
            ),
            "requirement_coverage": requirement_coverage,
            "scoring_coverage": scoring_coverage,
            "knowledge_usage": _deduplicate_usage(knowledge_usage),
            "truth_and_privacy_review": truth_privacy,
            "language_and_ai_style_review": style_findings,
            "deliverability_gate": {
                "checks": gate_checks,
                "passed": recommended,
                "thresholds": {
                    "minimum_requirement_coverage": min_requirement,
                    "minimum_scoring_coverage": min_scoring,
                    "minimum_traceability_rate": min_traceability,
                },
            },
        }
        return _remove_internal_ids(report)

    @staticmethod
    def auto_fix(
        content: str,
        provenance: list[dict[str, Any]],
        rules: RuleDocument | None = None,
    ) -> str:
        active = rules or RuleEngine().load_default("compliance")
        truth_rules = active.content.get("truth_review", {})
        language_rules = active.content.get("language_review", {})
        enterprise_patterns = tuple(
            truth_rules.get("high_risk_enterprise_facts", [])
        )
        project_specific_patterns = tuple(
            truth_rules.get("unverified_project_specifics", [])
        )
        ai_style_terms = tuple(
            language_rules.get("discouraged_slogans", [])
        )
        provenance_by_index: dict[int, list[dict[str, Any]]] = {}
        for item in provenance:
            provenance_by_index.setdefault(
                int(item.get("paragraph_index", -1)), []
            ).append(item)
        output: list[str] = []
        for index, line in enumerate(content_paragraphs(content)):
            traces = provenance_by_index.get(index, [])
            verified = any(
                item.get("verification_status")
                in {"verified", "user_confirmed"}
                for item in traces
            )
            risky = any(
                pattern in line
                for pattern in (
                    *enterprise_patterns,
                    *project_specific_patterns,
                )
            )
            if risky and not verified:
                continue
            line = UUID_PATTERN.sub("已记录来源", line)
            if INTERNAL_PATTERN.search(line) or SECRET_PATTERN.search(line):
                continue
            line = re.sub(r"[✅✔➡→★⭐🔹🚀📌]", "", line)
            line = re.sub(r"^\s*#{1,6}\s*", "", line)
            line = line.replace("**", "").replace("__", "")
            line = re.sub(r"^\s*[-*]\s+", "", line)
            for phrase in ai_style_terms:
                line = line.replace(phrase, "")
            line = re.sub(r"\s{2,}", " ", line).strip()
            if line:
                output.append(line)
        return "\n".join(output).strip()

    def latest(self, project_id: UUID) -> dict[str, Any]:
        with connect() as conn:
            with conn.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    """
                    SELECT report
                    FROM proposal_reviews
                    WHERE project_id = %s
                    ORDER BY created_at DESC LIMIT 1
                    """,
                    (project_id,),
                )
                row = cursor.fetchone()
        if row is None:
            raise ValueError("方案尚未生成审查报告。")
        return dict(row["report"])

    def report_files(self, project_id: UUID) -> tuple[Path, Path]:
        with connect() as conn:
            with conn.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    """
                    SELECT json_storage_key, readable_storage_key
                    FROM proposal_reviews
                    WHERE project_id = %s
                    ORDER BY created_at DESC LIMIT 1
                    """,
                    (project_id,),
                )
                row = cursor.fetchone()
        if row is None:
            raise ValueError("方案尚未生成审查报告。")
        root = Path(settings.export_root).resolve()
        return (
            (root / row["json_storage_key"]).resolve(),
            (root / row["readable_storage_key"]).resolve(),
        )

    def _persist_review(
        self, project_id: UUID, report: dict[str, Any]
    ) -> UUID:
        review_id = uuid4()
        relative_root = Path(str(project_id)) / "reviews"
        if report["phase"] == "final":
            json_key = relative_root / "proposal_review.json"
            md_key = relative_root / "Proposal_Review.md"
        else:
            json_key = relative_root / "proposal_review_initial.json"
            md_key = relative_root / "Proposal_Review_initial.md"
        root = Path(settings.export_root).resolve()
        json_path = (root / json_key).resolve()
        md_path = (root / md_key).resolve()
        if root not in json_path.parents or root not in md_path.parents:
            raise ValueError("非法审查报告路径")
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        md_path.write_text(_to_markdown(report), encoding="utf-8")
        with connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO proposal_reviews (
                        id, project_id, phase, status, deliverable, report,
                        json_storage_key, readable_storage_key
                    )
                    VALUES (
                        %s, %s, %s, 'completed', %s, %s::jsonb, %s, %s
                    )
                    """,
                    (
                        review_id,
                        project_id,
                        report["phase"],
                        report["overall"]["recommended_for_delivery"],
                        json.dumps(report, ensure_ascii=False),
                        str(json_key),
                        str(md_key),
                    ),
                )
        return review_id

    def _load_review_input(self, project_id: UUID) -> dict[str, Any]:
        with connect() as conn:
            with conn.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    "SELECT name FROM projects WHERE id = %s",
                    (project_id,),
                )
                project = cursor.fetchone()
                if project is None:
                    raise ValueError("方案不存在。")
                cursor.execute(
                    """
                    SELECT s.id AS section_id, s.title, s.status,
                           s.current_version_id, sv.content
                    FROM sections s
                    LEFT JOIN section_versions sv
                      ON sv.id = s.current_version_id
                    WHERE s.project_id = %s
                    ORDER BY s.sort_order, s.created_at
                    """,
                    (project_id,),
                )
                sections = [dict(row) for row in cursor.fetchall()]
                cursor.execute(
                    """
                    SELECT r.id, r.requirement_type AS type, r.title,
                           r.normalized_text, r.quote
                    FROM requirements r
                    WHERE r.project_id = %s
                      AND r.need_generation = TRUE
                      AND r.status <> 'rejected'
                    ORDER BY r.created_at
                    """,
                    (project_id,),
                )
                requirements = [dict(row) for row in cursor.fetchall()]
                cursor.execute(
                    """
                    SELECT
                        COUNT(*) AS total_count,
                        COUNT(*) FILTER (
                            WHERE classification_confidence >= 0.8
                        ) AS high_confidence_count,
                        COUNT(*) FILTER (
                            WHERE classification_confidence < 0.6
                        ) AS low_confidence_count,
                        COUNT(*) FILTER (
                            WHERE need_generation = TRUE
                              AND proposal_chapter IS NULL
                        ) AS unmapped_count,
                        COUNT(*) FILTER (
                            WHERE classification_conflict = TRUE
                        ) AS conflict_count
                    FROM requirements
                    WHERE project_id = %s AND status <> 'rejected'
                    """,
                    (project_id,),
                )
                classification_counts = dict(cursor.fetchone())
                cursor.execute(
                    """
                    SELECT sr.section_id, sr.requirement_id
                    FROM section_requirements sr
                    JOIN sections s ON s.id = sr.section_id
                    WHERE s.project_id = %s
                    """,
                    (project_id,),
                )
                mappings = cursor.fetchall()
                cursor.execute(
                    """
                    SELECT cp.section_version_id, cp.paragraph_index,
                           cp.source_type, cp.source_title,
                           cp.source_location, cp.usage_description,
                           cp.verification_status, cp.confidence
                    FROM content_provenance cp
                    JOIN section_versions sv
                      ON sv.id = cp.section_version_id
                    JOIN sections s ON s.current_version_id = sv.id
                    WHERE s.project_id = %s
                    ORDER BY cp.paragraph_index, cp.created_at
                    """,
                    (project_id,),
                )
                provenance = cursor.fetchall()
        public_keys = {
            item["id"]: f"R{index + 1:04d}"
            for index, item in enumerate(requirements)
        }
        section_keys: dict[UUID, list[str]] = {}
        for item in mappings:
            section_keys.setdefault(item["section_id"], []).append(
                public_keys[item["requirement_id"]]
            )
        provenance_by_version: dict[UUID, list[dict[str, Any]]] = {}
        for item in provenance:
            provenance_by_version.setdefault(
                item["section_version_id"], []
            ).append(dict(item))
        source_locations = self._requirement_locations(project_id)
        total = int(classification_counts["total_count"])
        high = int(classification_counts["high_confidence_count"])
        low = int(classification_counts["low_confidence_count"])
        unmapped = int(classification_counts["unmapped_count"])
        conflicts = int(classification_counts["conflict_count"])
        penalty = low + (unmapped * 2) + conflicts
        classification_quality = {
            "quality_rate": round(
                max(0.0, 1 - penalty / max(total, 1)), 4
            ),
            "total_count": total,
            "high_confidence_ratio": round(
                high / total if total else 1.0, 4
            ),
            "low_confidence_count": low,
            "unmapped_count": unmapped,
            "conflict_count": conflicts,
        }
        return {
            "project_name": project["name"],
            "classification_quality": classification_quality,
            "requirements": [
                {
                    "public_key": public_keys[item["id"]],
                    "type": item["type"],
                    "title": item["title"],
                    "normalized_text": item["normalized_text"],
                    "quote": item["quote"],
                    "source_location": source_locations.get(item["id"]),
                }
                for item in requirements
            ],
            "sections": [
                {
                    **item,
                    "requirement_public_keys": section_keys.get(
                        item["section_id"], []
                    ),
                    "provenance": provenance_by_version.get(
                        item["current_version_id"], []
                    ),
                }
                for item in sections
            ],
        }

    @staticmethod
    def _requirement_locations(project_id: UUID) -> dict[UUID, str]:
        with connect() as conn:
            with conn.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    """
                    SELECT DISTINCT ON (r.id)
                           r.id, d.filename, sc.locator_kind,
                           sc.page_no, sc.paragraph_start, sc.paragraph_end
                    FROM requirements r
                    JOIN requirement_sources rs ON rs.requirement_id = r.id
                    JOIN source_chunks sc ON sc.id = rs.source_chunk_id
                    JOIN documents d ON d.id = sc.document_id
                    WHERE r.project_id = %s
                    ORDER BY r.id, sc.chunk_index
                    """,
                    (project_id,),
                )
                rows = cursor.fetchall()
        result = {}
        for row in rows:
            if row["locator_kind"] == "page":
                suffix = f"第 {row['page_no']} 页"
            else:
                start, end = (
                    row["paragraph_start"], row["paragraph_end"]
                )
                suffix = (
                    f"第 {start} 段"
                    if start == end
                    else f"第 {start}-{end} 段"
                )
            result[row["id"]] = f"{row['filename']}，{suffix}"
        return result

    def _persist_auto_fixes(
        self,
        project_id: UUID,
        data: dict[str, Any],
        fixed_sections: dict[UUID, str],
    ) -> None:
        requirement_by_public = {
            item["public_key"]: item for item in data["requirements"]
        }
        for section in data["sections"]:
            fixed = fixed_sections[section["section_id"]]
            if fixed == section.get("content", ""):
                continue
            requirements = [
                requirement_by_public[key]
                for key in section["requirement_public_keys"]
                if key in requirement_by_public
            ]
            provenance, case_usage = ProvenanceService.build(
                section_title=section["title"],
                content=fixed,
                requirements=requirements,
                matches=[],
                origin="generated",
            )
            with connect() as conn:
                with conn.cursor(row_factory=dict_row) as cursor:
                    cursor.execute(
                        """
                        SELECT COALESCE(MAX(version_no), 0) + 1 AS version_no
                        FROM section_versions WHERE section_id = %s
                        """,
                        (section["section_id"],),
                    )
                    version_no = cursor.fetchone()["version_no"]
                    cursor.execute(
                        """
                        SELECT rule_snapshot, knowledge_snapshot
                        FROM section_versions WHERE id = %s
                        """,
                        (section["current_version_id"],),
                    )
                    snapshot = cursor.fetchone() or {
                        "rule_snapshot": {},
                        "knowledge_snapshot": [],
                    }
                    cursor.execute(
                        """
                        INSERT INTO section_versions (
                            section_id, version_no, content, origin,
                            input_snapshot, rule_snapshot,
                            knowledge_snapshot
                        )
                        VALUES (
                            %s, %s, %s, 'auto_fixed',
                            '{"auto_fix": true}'::jsonb, %s::jsonb, %s::jsonb
                        )
                        RETURNING id
                        """,
                        (
                            section["section_id"],
                            version_no,
                            fixed,
                            json.dumps(
                                snapshot["rule_snapshot"] or {},
                                ensure_ascii=False,
                            ),
                            json.dumps(
                                snapshot["knowledge_snapshot"] or [],
                                ensure_ascii=False,
                            ),
                        ),
                    )
                    version_id = cursor.fetchone()["id"]
                    cursor.execute(
                        """
                        UPDATE sections SET current_version_id = %s,
                            updated_at = NOW()
                        WHERE id = %s AND project_id = %s
                        """,
                        (version_id, section["section_id"], project_id),
                    )
            ProvenanceService.persist(version_id, provenance, case_usage)

    @staticmethod
    def _risk(
        description: str,
        location: str,
        source: str,
        level: str,
        blocks: bool,
        action: str,
        auto_result: str,
    ) -> dict[str, Any]:
        return {
            "risk_description": description,
            "location": location,
            "source": source,
            "risk_level": level,
            "blocks_delivery": blocks,
            "recommended_action": action,
            "automatic_action_result": auto_result,
        }

    @staticmethod
    def _style(
        location: str, description: str, recommendation: str
    ) -> dict[str, str]:
        return {
            "location": location,
            "description": description,
            "recommendation": recommendation,
        }


def _deduplicate_usage(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = set()
    result = []
    for item in items:
        key = (
            item["source_type"],
            item["source"],
            item["usage_location"],
            item["usage_summary"],
        )
        if key not in seen:
            seen.add(key)
            result.append(item)
    return result


def _remove_internal_ids(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _remove_internal_ids(item)
            for key, item in value.items()
            if key not in {
                "id", "source_id", "requirement_id", "section_id",
                "project_id", "knowledge_id", "version_id",
            }
        }
    if isinstance(value, list):
        return [_remove_internal_ids(item) for item in value]
    if isinstance(value, str):
        return UUID_PATTERN.sub("内部来源已记录", value)
    return value


def _to_markdown(report: dict[str, Any]) -> str:
    overall = report["overall"]
    classification = report.get("classification_quality", {})
    lines = [
        "# Proposal Review",
        "",
        "## 总体结论",
        "",
        f"- 建议正式交付：{'是' if overall['recommended_for_delivery'] else '否'}",
        f"- 阻断性风险：{overall['blocking_risk_count']} 项",
        f"- 需求覆盖率：{overall['requirement_coverage_rate']:.1%}",
        f"- 评分点覆盖率：{overall['scoring_coverage_rate']:.1%}",
        f"- 来源可追溯率：{overall['traceability_rate']:.1%}",
        f"- 企业事实核验率：{overall['enterprise_fact_verification_rate']:.1%}",
        f"- 未验证断言：{overall['unverified_assertion_count']} 项",
        f"- 内部标识泄露：{overall['internal_identifier_leak_count']} 项",
        "",
        "## Classification Quality",
        "",
        f"- 分类质量：{classification.get('quality_rate', 1):.1%}",
        f"- Requirement 数量：{classification.get('total_count', 0)}",
        f"- 高置信分类比例：{classification.get('high_confidence_ratio', 1):.1%}",
        f"- 低置信分类：{classification.get('low_confidence_count', 0)} 项",
        f"- 未映射章节：{classification.get('unmapped_count', 0)} 项",
        f"- 分类冲突：{classification.get('conflict_count', 0)} 项",
        "",
        "## Requirement Coverage",
        "",
    ]
    for item in report["requirement_coverage"]:
        lines.extend(
            [
                f"### {item['requirement']}",
                f"- 来源位置：{item['source_location']}",
                f"- 覆盖状态：{item['coverage_status']}",
                f"- 对应章节：{'、'.join(item['generated_sections']) or '无'}",
                f"- 风险：{item['risk']}",
                f"- 建议：{item['recommendation']}",
                "",
            ]
        )
    lines.extend(["## Scoring Coverage", ""])
    for item in report["scoring_coverage"]:
        lines.extend(
            [
                f"### {item['scoring_item']}",
                f"- 分值：{item['points'] if item['points'] is not None else '未明确'}",
                f"- 覆盖状态：{item['coverage_status']}",
                f"- 当前章节：{'、'.join(item['response_sections']) or '无'}",
                f"- 缺失内容：{item['missing_content'] or '无明显缺失'}",
                f"- 改进建议：{item['recommendation']}",
                "",
            ]
        )
    lines.extend(["## Knowledge Usage", ""])
    counts = Counter(
        item["source_type"] for item in report["knowledge_usage"]
    )
    for source_type, count in sorted(counts.items()):
        lines.append(f"- {source_type}: {count} 条")
    for item in report["knowledge_usage"]:
        lines.append(
            f"- {item['source']}｜{item['usage_location']}｜"
            f"{item['verification_status']}｜"
            f"{'允许进入' if item['allowed_in_final'] else '不得进入'}"
        )
    lines.extend(["", "## Truth and Privacy Review", ""])
    if not report["truth_and_privacy_review"]:
        lines.append("- 未发现真实性或隐私风险。")
    for item in report["truth_and_privacy_review"]:
        lines.append(
            f"- [{item['risk_level']}] {item['risk_description']}｜"
            f"{item['location']}｜{item['recommended_action']}"
        )
    lines.extend(["", "## Language and AI Style Review", ""])
    if not report["language_and_ai_style_review"]:
        lines.append("- 未发现明显机器化表达。")
    for item in report["language_and_ai_style_review"]:
        lines.append(
            f"- {item['location']}：{item['description']}；"
            f"{item['recommendation']}"
        )
    lines.extend(["", "## Deliverability Gate", ""])
    for key, passed in report["deliverability_gate"]["checks"].items():
        lines.append(f"- {key}: {'通过' if passed else '未通过'}")
    return "\n".join(lines) + "\n"
