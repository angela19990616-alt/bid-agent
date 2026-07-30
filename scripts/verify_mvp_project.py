from __future__ import annotations

import argparse
from uuid import UUID

from app.services.export_service import ExportService
from app.services.proposal_review_service import ProposalReviewService
from app.services.section_service import SectionService


def verify_project(project_id: UUID) -> None:
    section_service = SectionService()
    sections = section_service.list(project_id)
    print(f"TOTAL {len(sections)}", flush=True)
    for index, section in enumerate(sections, start=1):
        current = section
        if not current.get("current_version"):
            current = section_service.generate(
                project_id,
                current["id"],
            )
        if current.get("status") != "approved":
            current = section_service.approve(
                project_id,
                current["id"],
            )
        version = current.get("current_version") or {}
        print(
            "SECTION",
            index,
            current["title"],
            current["status"],
            len(version.get("content") or ""),
            len(current.get("findings") or []),
            flush=True,
        )

    exported = ExportService().create_full(project_id)
    review = ProposalReviewService().latest(project_id)
    overall = review["overall"]
    print(
        "EXPORT",
        exported.get("status"),
        exported.get("filename"),
        flush=True,
    )
    print(
        "REVIEW",
        overall["recommended_for_delivery"],
        overall["blocking_risk_count"],
        overall["internal_identifier_leak_count"],
        overall["traceability_rate"],
        flush=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="逐章生成、确认并导出一个已获授权的 MVP 验收项目。"
    )
    parser.add_argument("project_id", type=UUID)
    parser.add_argument(
        "--approve-and-export",
        action="store_true",
        help="确认已获授权，可生成、确认章节并导出整本 Word。",
    )
    args = parser.parse_args()
    if not args.approve_and_export:
        parser.error("必须显式传入 --approve-and-export。")
    verify_project(args.project_id)


if __name__ == "__main__":
    main()
