from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.services.document_service import SourceSegment
from app.rules.engine import RuleDocument, RuleEngine


@dataclass(frozen=True)
class DocumentValidation:
    is_valid: bool
    score: float
    reason: str
    parse_quality: float


class DocumentValidator:
    """Deterministic gate driven by the loaded extraction rule."""
    def validate(
        self,
        filename: str,
        segments: list[SourceSegment],
        rules: RuleDocument | None = None,
    ) -> DocumentValidation:
        active = rules or RuleEngine().load("extraction")
        config = active.content["document_validation"]
        extension_ok = (
            Path(filename).suffix.lower()
            in set(config["allowed_extensions"])
        )
        text = "\n".join(item.text for item in segments).strip()
        matched = sum(
            any(marker in text for marker in group)
            for group in config["marker_groups"]
        )
        parse_quality = min(1.0, len(text) / 5000) if text else 0.0
        score = round(
            min(1.0, matched / len(config["marker_groups"]) * 0.8
                + parse_quality * 0.2),
            2,
        )
        is_valid = (
            extension_ok
            and len(text) >= config["minimum_text_chars"]
            and len(segments) >= config["minimum_segments"]
            and matched >= config["minimum_marker_groups"]
        )
        if not extension_ok:
            reason = "仅支持 PDF 或 DOCX 招标文件。"
        elif (
            len(text) < config["minimum_text_chars"]
            or len(segments) < config["minimum_segments"]
        ):
            reason = "文件可解析内容过少，无法识别为有效招标文件。"
        elif matched < config["minimum_marker_groups"]:
            reason = "未识别到足够的招标、响应、需求或评审特征。"
        else:
            reason = "已识别为有效招标文件。"
        return DocumentValidation(is_valid, score, reason, parse_quality)
