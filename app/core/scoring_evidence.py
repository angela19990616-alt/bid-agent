from __future__ import annotations

import math
import re
from typing import Any


class ScoringEvidencePlanner:
    """Turn material-based score items into auditable evidence bundles.

    This layer never treats a historical bid as a current enterprise fact.
    It ranks only authorized knowledge and marks incomplete evidence instead
    of asking a model to invent or silently infer missing materials.
    """

    @classmethod
    def plan(
        cls,
        requirements: list[dict[str, Any]],
        knowledge: list[dict[str, Any]],
        rules: dict[str, Any],
    ) -> list[dict[str, Any]]:
        markers = tuple(rules.get("material_scoring_markers") or ())
        plans = []
        for requirement in requirements:
            text = cls._requirement_text(requirement)
            if (
                requirement.get("scoring_impact") != "score_item"
                or not any(marker in text for marker in markers)
            ):
                continue
            criterion_type = cls._criterion_type(text, rules)
            formula = cls._score_formula(text)
            constraints = cls._constraints(text, rules)
            candidates = cls._rank_candidates(
                text,
                criterion_type,
                constraints,
                knowledge,
                rules,
            )
            unique_candidates = cls._deduplicate(
                candidates,
                criterion_type,
                constraints,
            )
            minimum = formula["minimum_count"]
            buffer_size = min(
                int((rules.get("selection_buffers") or {}).get(
                    criterion_type, 1
                )),
                int((rules.get("selection_buffers") or {}).get(
                    "maximum_extra", 3
                )),
            )
            target = minimum + buffer_size if minimum else 1
            eligible = [item for item in unique_candidates if item["eligible"]]
            selected = eligible[:target]
            approval_pending = any(
                item["approval_status"] == "required"
                for item in selected
            )
            if len(selected) < minimum:
                readiness = "verified_material_insufficient"
            elif approval_pending:
                readiness = "approval_required"
            else:
                readiness = "ready_for_review"
            plans.append({
                "requirement_id": str(requirement["id"]),
                "title": requirement.get("title") or "评分材料事项",
                "source_text": requirement.get("quote") or text,
                "sources": requirement.get("sources") or [],
                "criterion_type": criterion_type,
                "criterion_label": {
                    "business_case": "企业业绩材料",
                    "person_certificate": "人员证书材料",
                    "organization_qualification": "企业资质材料",
                }.get(criterion_type, "评分证明材料"),
                **formula,
                "recommended_count": target,
                "constraints": constraints,
                "candidate_count": len(unique_candidates),
                "eligible_count": len(eligible),
                "selected_count": len(selected),
                "selected_candidates": selected,
                "readiness": readiness,
                "matching_steps": cls._matching_steps(
                    criterion_type, constraints
                ),
            })
        return plans

    @staticmethod
    def _requirement_text(requirement: dict[str, Any]) -> str:
        return " ".join(str(requirement.get(key) or "") for key in (
            "title", "normalized_text", "quote",
        ))

    @staticmethod
    def _criterion_type(text: str, rules: dict[str, Any]) -> str:
        definitions = rules.get("criterion_types") or {}
        scores = {
            kind: sum(keyword in text for keyword in keywords)
            for kind, keywords in definitions.items()
        }
        return max(scores, key=scores.get) if any(scores.values()) else "other"

    @staticmethod
    def _score_formula(text: str) -> dict[str, Any]:
        per_item_match = re.search(
            r"每(?:个|项|份|人|个证书)[^。；;，,]{0,18}?"
            r"(?:得|加)?\s*(\d+(?:\.\d+)?)\s*分",
            text,
        )
        max_score_match = re.search(
            r"(?:最高|满分)(?:得|为)?\s*(\d+(?:\.\d+)?)\s*分",
            text,
        )
        points = float(per_item_match.group(1)) if per_item_match else None
        maximum = float(max_score_match.group(1)) if max_score_match else None
        minimum = (
            math.ceil(maximum / points)
            if points and maximum and points > 0 else 1
        )
        return {
            "points_per_item": points,
            "maximum_score": maximum,
            "minimum_count": minimum,
        }

    @staticmethod
    def _constraints(text: str, rules: dict[str, Any]) -> list[dict[str, str]]:
        labels = {
            "government_client": "政府方客户",
            "ppp_service": "PPP相关服务类型",
            "certificate_types": "限定证书类别",
            "employment_relation": "人员所属投标单位",
            "one_person_one_score": "一人多证只计一次",
        }
        result = []
        for key, keywords in (rules.get("constraint_groups") or {}).items():
            hits = [keyword for keyword in keywords if keyword in text]
            if hits:
                result.append({
                    "key": key,
                    "label": labels.get(key, key),
                    "value": "、".join(hits),
                })
        return result

    @classmethod
    def _rank_candidates(
        cls,
        requirement_text: str,
        criterion_type: str,
        constraints: list[dict[str, str]],
        knowledge: list[dict[str, Any]],
        rules: dict[str, Any],
    ) -> list[dict[str, Any]]:
        allowed_categories = {
            "business_case": {"case_study"},
            "person_certificate": {"qualification", "expert_experience"},
            "organization_qualification": {"qualification"},
        }.get(criterion_type, set())
        requirement_terms = cls._terms(requirement_text)
        result = []
        for item in knowledge:
            metadata = dict(item.get("metadata") or {})
            content = f"{item.get('title', '')} {item.get('content', '')}"
            overlap = requirement_terms & cls._terms(content)
            verified = metadata.get("verified_enterprise_fact") is True
            evidence_location = (
                metadata.get("evidence_location")
                or metadata.get("source_location")
            )
            asset_reference = metadata.get("asset_reference")
            category_allowed = item.get("category") in allowed_categories
            constraint_failures = cls._constraint_failures(
                content, metadata, constraints, rules
            )
            eligible = bool(
                category_allowed
                and verified
                and evidence_location
                and asset_reference
                and not constraint_failures
            )
            if not overlap and not eligible:
                continue
            score = min(
                1.0,
                len(overlap) / max(4, len(requirement_terms))
                + (0.35 if category_allowed else 0)
                + (0.2 if verified else 0),
            )
            approval_status = cls._approval_status(metadata, rules)
            result.append({
                "title": str(item.get("title") or "企业证明材料"),
                "category": str(item.get("category") or "unknown"),
                "score": round(score, 4),
                "eligible": eligible,
                "verified": verified,
                "holder": metadata.get("holder"),
                "organization": metadata.get("organization"),
                "contract_number": metadata.get("contract_number"),
                "source_file": (
                    metadata.get("evidence_title")
                    or metadata.get("source_filename")
                    or item.get("title")
                ),
                "source_location": evidence_location,
                "source_page": metadata.get("source_page"),
                "source_excerpt": metadata.get("evidence_excerpt"),
                "asset_kind": metadata.get("asset_kind") or "document",
                "approval_status": approval_status,
                "exclusion_reasons": constraint_failures + [
                    reason for condition, reason in (
                        (not category_allowed, "资料类型不符合评分条件"),
                        (not verified, "企业事实尚未核验"),
                        (not asset_reference, "尚未关联真实材料文件"),
                        (not evidence_location, "尚缺原文件定位"),
                    ) if condition
                ],
                "match_basis": "、".join(sorted(overlap)[:8]),
            })
        return sorted(
            result,
            key=lambda item: (
                not item["eligible"],
                item["approval_status"] == "required",
                -item["score"],
                item["title"],
            ),
        )

    @staticmethod
    def _constraint_failures(
        content: str,
        metadata: dict[str, Any],
        constraints: list[dict[str, str]],
        rules: dict[str, Any],
    ) -> list[str]:
        keys = {item["key"] for item in constraints}
        failures = []
        if "government_client" in keys and not (
            metadata.get("client_type") == "government"
            or any(keyword in content for keyword in (
                rules.get("constraint_groups") or {}
            ).get("government_client", ()))
        ):
            failures.append("无法证明客户属于政府方")
        if "ppp_service" in keys and not any(
            keyword in content for keyword in (
                rules.get("constraint_groups") or {}
            ).get("ppp_service", ())
        ):
            failures.append("服务内容不满足PPP业务范围")
        if "employment_relation" in keys and not (
            metadata.get("employment_verified") is True
            or metadata.get("social_security_verified") is True
        ):
            failures.append("未核验人员与投标单位的劳动或社保关系")
        return failures

    @staticmethod
    def _approval_status(
        metadata: dict[str, Any], rules: dict[str, Any]
    ) -> str:
        scope = str(metadata.get("document_scope") or "")
        approval = str(metadata.get("approval_status") or "")
        markers = (rules.get("approval_policy") or {}).get(
            "full_contract_markers", ()
        )
        full_contract = scope == "full_contract" or any(
            marker in scope for marker in markers
        )
        if full_contract and approval != "approved":
            return "required"
        return "approved" if full_contract else "not_required"

    @staticmethod
    def _deduplicate(
        candidates: list[dict[str, Any]],
        criterion_type: str,
        constraints: list[dict[str, str]],
    ) -> list[dict[str, Any]]:
        one_person = any(
            item["key"] == "one_person_one_score" for item in constraints
        )
        seen = set()
        result = []
        for item in candidates:
            if criterion_type == "person_certificate" and one_person:
                key = item.get("holder") or item["title"]
            elif criterion_type == "business_case":
                key = item.get("contract_number") or item["title"]
            else:
                key = item["title"]
            if key in seen:
                continue
            seen.add(key)
            result.append(item)
        return result

    @staticmethod
    def _matching_steps(
        criterion_type: str, constraints: list[dict[str, str]]
    ) -> list[str]:
        keys = {item["key"] for item in constraints}
        if criterion_type == "business_case":
            steps = ["按业务类型筛选项目合同台账"]
            if "government_client" in keys:
                steps.append("核验合同甲方是否为政府方")
            steps.extend(["按合同编号关联证明材料", "去重并检查满分数量"])
            return steps
        if criterion_type == "person_certificate":
            steps = ["按限定证书类别筛选人员"]
            if "employment_relation" in keys:
                steps.append("核验人员所属单位或社保关系")
            steps.extend(["按人员去重", "检查证书有效性和满分数量"])
            return steps
        return ["按评分条件筛选已核验企业资料", "检查来源和数量"]

    @staticmethod
    def _terms(text: str) -> set[str]:
        compact = re.sub(r"\s+", "", text.lower())
        words = set(re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]{2,8}", compact))
        chinese = "".join(re.findall(r"[\u4e00-\u9fff]", compact))
        words.update(
            chinese[index:index + size]
            for size in (2, 3, 4)
            for index in range(max(0, len(chinese) - size + 1))
        )
        return words
