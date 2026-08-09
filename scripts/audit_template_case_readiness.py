#!/usr/bin/env python3
"""Audit template-first and private case-library readiness without DB writes."""

from __future__ import annotations

import argparse
import json
import sys
from io import BytesIO
from pathlib import Path
from uuid import uuid4

from docx import Document

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.memory.case_pair_batch import (  # noqa: E402
    CasePairBatchImporter,
    CasePairManifestError,
)
from app.agents.proposal_planner import ProposalPlanner  # noqa: E402
from app.rules.engine import RuleEngine  # noqa: E402
from app.services.generation_profile_service import (  # noqa: E402
    GenerationProfileService,
)
from app.services.response_template_service import (  # noqa: E402
    ResponseTemplateService,
)


def audit(manifest_path: Path, expected_pairs: int = 5) -> dict:
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return _failed_report(expected_pairs, f"案例清单不可读：{type(exc).__name__}")
    pairs = payload.get("pairs") if isinstance(payload, dict) else None
    actual_pairs = len(pairs) if isinstance(pairs, list) else 0
    error = None
    prepared = []
    if actual_pairs:
        try:
            prepared = CasePairBatchImporter().load_manifest(
                manifest_path,
                expected_pairs=actual_pairs,
            )
        except CasePairManifestError as exc:
            error = str(exc)
    else:
        error = "案例清单没有可验证的案例组。"

    template_service = ResponseTemplateService()
    template_modes = []
    for item, raw_pair in zip(prepared, pairs or []):
        tender_path = _resolve_tender(
            manifest_path.parent,
            str(raw_pair.get("tender") or ""),
        )
        if tender_path is None:
            template_modes.append("source_lookup_failed")
            continue
        descriptor = template_service.detect(
            tender_path.name, tender_path.read_bytes()
        )
        if descriptor.source_format == "pdf" and descriptor.detected:
            template_modes.append("pdf_template_manual_fill")
        elif descriptor.detected:
            template_modes.append("strict_template")
        else:
            template_modes.append("planned")

    patterns_isolated = all(
        pattern.get("prohibited_fact_copy") is True
        and pattern.get("source_facts_removed") is True
        for item in prepared
        for pattern in CasePairBatchImporter().pattern_extractor.extract(
            item.pair.proposal_content
        )
    )
    gates = {
        "available_pairs_valid": bool(prepared) and error is None,
        "complete_five_pair_batch": (
            len(prepared) == expected_pairs and error is None
        ),
        "all_cases_have_generation_decision": (
            len(template_modes) == len(prepared)
            and "source_lookup_failed" not in template_modes
        ),
        "historical_facts_isolated": bool(prepared) and patterns_isolated,
        "no_template_requirement_planning": _no_template_planning_gate(),
        "attachment_template_priority_stable": _template_priority_gate(),
    }
    return {
        "expected_pairs": expected_pairs,
        "available_pairs": actual_pairs,
        "validated_pairs": len(prepared),
        "pattern_count": sum(item.pattern_count for item in prepared),
        "generation_modes": {
            mode: template_modes.count(mode)
            for mode in sorted(set(template_modes))
        },
        "gates": gates,
        "ready": all(gates.values()),
        "blocker": error or (
            None if gates["complete_five_pair_batch"]
            else f"仍缺 {max(0, expected_pairs - actual_pairs)} 组真实案例文件。"
        ),
        "privacy": {
            "database_write": False,
            "source_text_in_report": False,
            "historical_facts_in_report": False,
        },
    }


def _resolve_tender(root: Path, relative_path: str) -> Path | None:
    path = (root / relative_path).resolve()
    resolved_root = root.resolve()
    if (
        not path.is_file()
        or (path != resolved_root and resolved_root not in path.parents)
    ):
        return None
    return path


def _no_template_planning_gate() -> bool:
    document = Document()
    document.add_paragraph("采购需求：供应商应提交实施计划与进度安排。")
    stream = BytesIO()
    document.save(stream)
    descriptor = ResponseTemplateService().detect(
        "采购文件.docx", stream.getvalue()
    )
    planned = ProposalPlanner().plan(
        [{
            "id": uuid4(),
            "proposal_chapter": "实施计划与进度安排",
            "need_generation": True,
        }],
        RuleEngine().load_default("writing"),
    )
    return (
        GenerationProfileService.mode_for_descriptor(
            descriptor.snapshot()
        ) == "planned"
        and bool(planned)
        and planned[0].title == "实施计划与进度安排"
    )


def _template_priority_gate() -> bool:
    preferred = GenerationProfileService.preferred_mode
    return (
        preferred("pdf_template_manual_fill", "planned")
        == "pdf_template_manual_fill"
        and preferred("strict_template", "pdf_template_manual_fill")
        == "strict_template"
        and preferred("planned", "strict_template")
        == "strict_template"
    )


def _failed_report(expected_pairs: int, blocker: str) -> dict:
    return {
        "expected_pairs": expected_pairs,
        "available_pairs": 0,
        "validated_pairs": 0,
        "pattern_count": 0,
        "generation_modes": {},
        "gates": {
            "available_pairs_valid": False,
            "complete_five_pair_batch": False,
            "all_cases_have_generation_decision": False,
            "historical_facts_isolated": False,
            "no_template_requirement_planning": False,
            "attachment_template_priority_stable": False,
        },
        "ready": False,
        "blocker": blocker,
        "privacy": {
            "database_write": False,
            "source_text_in_report": False,
            "historical_facts_in_report": False,
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="只读审计模板优先和五组机构私有案例库就绪度。"
    )
    parser.add_argument(
        "manifest",
        nargs="?",
        type=Path,
        default=ROOT / "database" / "case-pairs.local.json",
    )
    parser.add_argument("--expected-pairs", type=int, default=5)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = audit(args.manifest.resolve(), args.expected_pairs)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
