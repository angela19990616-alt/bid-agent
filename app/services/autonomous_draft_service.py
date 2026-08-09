from __future__ import annotations

from uuid import UUID

from app.services.conflict_service import (
    ConflictResolutionError,
    ConflictService,
)
from app.services.proposal_review_service import ProposalReviewService
from app.services.section_service import SectionService
from app.services.workspace_job_service import WorkspaceJobService


class AutonomousDraftService:
    """Generate a complete reviewable draft without auto-approving it."""

    def run(self, project_id: UUID, job_id: UUID) -> dict:
        section_service = SectionService()
        sections = section_service.list(project_id)
        if not sections:
            raise ValueError("方案目录为空，无法生成整本初稿。")
        generated = 0
        skipped_conflicts: list[str] = []
        for index, section in enumerate(sections, start=1):
            if section.get("current_version"):
                generated += 1
            else:
                try:
                    ConflictService.assert_section_unblocked(
                        project_id, section["id"]
                    )
                except ConflictResolutionError:
                    skipped_conflicts.append(section["title"])
                else:
                    section_service.generate(project_id, section["id"])
                    generated += 1
            WorkspaceJobService.update_progress(
                job_id,
                10 + int(index / len(sections) * 75),
            )

        review = ProposalReviewService().prepare_for_export(project_id)
        WorkspaceJobService.update_progress(job_id, 95)
        return {
            "section_count": len(sections),
            "generated_count": generated,
            "conflict_pending_sections": skipped_conflicts,
            "recommended_for_delivery": review["overall"][
                "recommended_for_delivery"
            ],
        }
