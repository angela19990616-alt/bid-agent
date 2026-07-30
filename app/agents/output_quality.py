from __future__ import annotations

import re
from dataclasses import dataclass, replace

from app.agents.requirement_classifier import ClassifiedRequirement


INTERNAL_TOKEN = re.compile(
    r"(?:requirement[_\s-]?id|source[_\s-]?id|"
    r"project[_\s-]?id|workflow[_\s-]?id|"
    r"\bREQ[-_]\d+\b|"
    r"\b[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\b)",
    re.IGNORECASE,
)
PROMPT_MARKER = re.compile(
    r"^\s*[\[【(（]?\s*(?:要求|requirement)\s*"
    r"(?:代码|编号|id)?\s*[:：#]?\s*[\w-]*\s*[\]】)）]?\s*",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class QualityFinding:
    code: str
    message: str
    field: str


class OutputReviewAgent:
    """Bounded, deterministic review of user-visible requirement content."""

    @staticmethod
    def review(item: ClassifiedRequirement) -> list[QualityFinding]:
        findings: list[QualityFinding] = []
        for field in ("title", "normalized_text"):
            value = getattr(item.item, field)
            if INTERNAL_TOKEN.search(value):
                findings.append(
                    QualityFinding(
                        "internal_identifier",
                        "用户可见内容包含内部标识。",
                        field,
                    )
                )
            if PROMPT_MARKER.match(value):
                findings.append(
                    QualityFinding(
                        "prompt_marker",
                        "用户可见内容包含无意义的要求标签。",
                        field,
                    )
                )
        if (
            item.requirement_type not in {
                "qualification_requirement", "commercial_requirement"
            }
            and item.proposal_chapter is None
        ):
            findings.append(
                QualityFinding(
                    "missing_chapter",
                    "需要响应的要求没有方案章节映射。",
                    "proposal_chapter",
                )
            )
        return findings


class OutputDebugAgent:
    """Applies only safe mechanical fixes, then returns for re-review."""

    @staticmethod
    def fix(
        item: ClassifiedRequirement,
        findings: list[QualityFinding],
    ) -> ClassifiedRequirement:
        fields = {finding.field for finding in findings}
        source = item.item
        changes = {}
        for field in ("title", "normalized_text"):
            if field not in fields:
                continue
            value = getattr(source, field)
            value = PROMPT_MARKER.sub("", value)
            value = INTERNAL_TOKEN.sub("", value)
            value = re.sub(r"\s{2,}", " ", value).strip(" ：:，,;-")
            changes[field] = value or "招标文件响应要求"
        if changes:
            source = replace(source, **changes)
        return replace(item, item=source)


class ReviewedDebugPipeline:
    """Review -> safe debug -> re-review; no autonomous loop."""

    def run(
        self,
        items: list[ClassifiedRequirement],
    ) -> list[ClassifiedRequirement]:
        output: list[ClassifiedRequirement] = []
        for item in items:
            findings = OutputReviewAgent.review(item)
            fixed = OutputDebugAgent.fix(item, findings)
            remaining = OutputReviewAgent.review(fixed)
            notes = fixed.rationale
            if findings:
                notes += f" 自检修复 {len(findings) - len(remaining)} 项。"
            if remaining:
                notes += f" 仍有 {len(remaining)} 项需人工关注。"
            output.append(
                replace(
                    fixed,
                    rationale=notes.strip(),
                    conflict=fixed.conflict or bool(remaining),
                )
            )
        return output
