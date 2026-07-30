from uuid import uuid4

from app.services.proposal_plan_service import ProposalPlanService


def test_ignored_requirements_are_removed_without_blocking_outline():
    kept = uuid4()
    ignored = uuid4()

    result = ProposalPlanService._filter_chapters(
        [
            {
                "title": "实施计划",
                "requirement_ids": [kept, ignored],
            },
            {
                "title": "空章节",
                "requirement_ids": [ignored],
            },
        ],
        {kept},
    )

    assert result == [
        {
            "title": "实施计划",
            "requirement_ids": [kept],
        }
    ]


def test_outline_filter_removes_duplicate_requirement_links():
    requirement_id = uuid4()

    result = ProposalPlanService._filter_chapters(
        [{
            "title": "项目理解",
            "requirement_ids": [requirement_id, requirement_id],
        }],
        {requirement_id},
    )

    assert result[0]["requirement_ids"] == [requirement_id]
