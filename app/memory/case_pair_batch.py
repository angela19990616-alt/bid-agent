from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

from app.knowledge.permissions import KnowledgeAccessContext
from app.memory.historical_case_learning import (
    HistoricalCaseLearningService,
    HistoricalCasePair,
    HistoricalCasePatternExtractor,
)
from app.services.document_service import extract_text


class CasePairManifestError(ValueError):
    pass


@dataclass(frozen=True)
class PreparedCasePair:
    pair: HistoricalCasePair
    pattern_count: int


@dataclass(frozen=True)
class CasePairBatchReport:
    pair_count: int
    pattern_count: int
    learned_pattern_count: int
    dry_run: bool
    permission_scope: str = "organization_private"
    fact_usage: str = "prohibited"

    def snapshot(self) -> dict[str, Any]:
        return {
            "pair_count": self.pair_count,
            "pattern_count": self.pattern_count,
            "learned_pattern_count": self.learned_pattern_count,
            "dry_run": self.dry_run,
            "permission_scope": self.permission_scope,
            "fact_usage": self.fact_usage,
        }


class CasePairBatchImporter:
    """Validates a complete case-pair batch before any database write."""

    def __init__(
        self,
        *,
        learning_service: HistoricalCaseLearningService | None = None,
        pattern_extractor: HistoricalCasePatternExtractor | None = None,
    ):
        self.learning_service = (
            learning_service or HistoricalCaseLearningService()
        )
        self.pattern_extractor = (
            pattern_extractor or HistoricalCasePatternExtractor()
        )

    def load_manifest(
        self,
        manifest_path: Path,
        *,
        expected_pairs: int = 5,
    ) -> list[PreparedCasePair]:
        manifest_path = manifest_path.resolve()
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CasePairManifestError("案例清单无法读取或不是有效 JSON。") from exc
        raw_pairs = payload.get("pairs") if isinstance(payload, dict) else None
        if not isinstance(raw_pairs, list):
            raise CasePairManifestError("案例清单必须包含 pairs 数组。")
        if len(raw_pairs) != expected_pairs:
            raise CasePairManifestError(
                f"案例清单必须恰好包含 {expected_pairs} 组，当前为 {len(raw_pairs)} 组。"
            )

        prepared: list[PreparedCasePair] = []
        identities: set[tuple[Path, Path]] = set()
        for index, item in enumerate(raw_pairs, start=1):
            if not isinstance(item, dict):
                raise CasePairManifestError(f"第 {index} 组案例配置无效。")
            tender_path = self._resolve_file(
                manifest_path.parent,
                item.get("tender"),
                allowed_suffixes={".docx", ".pdf"},
                label=f"第 {index} 组招标文件",
            )
            proposal_path = self._resolve_file(
                manifest_path.parent,
                item.get("winning_proposal"),
                allowed_suffixes={".docx"},
                label=f"第 {index} 组中标响应文件",
            )
            identity = (tender_path, proposal_path)
            if identity in identities:
                raise CasePairManifestError(f"第 {index} 组与前述案例重复。")
            identities.add(identity)

            project_type = str(item.get("project_type") or "").strip()
            industry = str(item.get("industry") or "").strip()
            if len(project_type) < 2 or len(industry) < 2:
                raise CasePairManifestError(
                    f"第 {index} 组必须填写项目类型和行业。"
                )
            try:
                quality_score = float(item.get("quality_score", 0.85))
            except (TypeError, ValueError) as exc:
                raise CasePairManifestError(
                    f"第 {index} 组质量分无效。"
                ) from exc
            if not 0.7 <= quality_score <= 1:
                raise CasePairManifestError(
                    f"第 {index} 组质量分必须在 0.7 到 1.0 之间。"
                )

            tender_content = tender_path.read_bytes()
            proposal_content = proposal_path.read_bytes()
            try:
                tender_text = extract_text(tender_path.name, tender_content)
                patterns = self.pattern_extractor.extract(proposal_content)
            except Exception as exc:
                raise CasePairManifestError(
                    f"第 {index} 组文件无法安全解析。"
                ) from exc
            if not tender_text.strip() or not patterns:
                raise CasePairManifestError(
                    f"第 {index} 组未提取到有效招标文本或方案结构。"
                )
            if any(
                pattern.get("prohibited_fact_copy") is not True
                or pattern.get("source_facts_removed") is not True
                for pattern in patterns
            ):
                raise CasePairManifestError(
                    f"第 {index} 组未通过历史事实隔离检查。"
                )
            prepared.append(
                PreparedCasePair(
                    pair=HistoricalCasePair(
                        tender_filename=tender_path.name,
                        tender_text=tender_text,
                        proposal_filename=proposal_path.name,
                        proposal_content=proposal_content,
                        project_type=project_type,
                        industry=industry,
                        quality_score=quality_score,
                    ),
                    pattern_count=len(patterns),
                )
            )
        return prepared

    def run(
        self,
        manifest_path: Path,
        *,
        access_context: KnowledgeAccessContext,
        expected_pairs: int = 5,
        dry_run: bool = False,
    ) -> CasePairBatchReport:
        prepared = self.load_manifest(
            manifest_path,
            expected_pairs=expected_pairs,
        )
        pattern_count = sum(item.pattern_count for item in prepared)
        learned: list[UUID] = []
        if not dry_run:
            learned = self.learning_service.learn_pairs(
                access_context=access_context,
                pairs=[item.pair for item in prepared],
            )
        return CasePairBatchReport(
            pair_count=len(prepared),
            pattern_count=pattern_count,
            learned_pattern_count=len(learned),
            dry_run=dry_run,
        )

    @staticmethod
    def _resolve_file(
        root: Path,
        raw_path: Any,
        *,
        allowed_suffixes: set[str],
        label: str,
    ) -> Path:
        value = str(raw_path or "").strip()
        if not value:
            raise CasePairManifestError(f"{label}路径为空。")
        path = (root / value).resolve()
        if root != path and root not in path.parents:
            raise CasePairManifestError(f"{label}必须位于清单目录内。")
        if not path.is_file():
            raise CasePairManifestError(f"{label}不存在。")
        if path.suffix.lower() not in allowed_suffixes:
            suffixes = "、".join(sorted(allowed_suffixes))
            raise CasePairManifestError(f"{label}仅支持 {suffixes}。")
        return path
