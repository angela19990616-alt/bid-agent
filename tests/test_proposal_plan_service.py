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


def test_strict_template_outline_controls_writing_structure():
    implementation = uuid4()
    training = uuid4()
    chapters = ProposalPlanService._template_chapters(
        {
            "outline": [
                {"title": "格式1 投标函", "level": 1},
                {"title": "格式13 项目实施方案", "level": 1},
                {"title": "13.1 实施计划", "level": 2},
                {"title": "13.2 培训方案", "level": 2},
                {"title": "格式14 商务偏离表", "level": 1},
            ]
        },
        [
            {
                "id": implementation,
                "target_chapter": "实施计划",
                "normalized_text": "项目实施周期180日历天",
            },
            {
                "id": training,
                "target_chapter": "培训方案",
                "normalized_text": "提供业务培训",
            },
        ],
        {
            "writing_section_patterns": ["项目实施方案", "实施计划", "培训方案"],
            "non_writing_section_patterns": ["投标函", "偏离表"],
        },
    )

    assert [item["title"] for item in chapters] == [
        "13.1 实施计划",
        "13.2 培训方案",
    ]
    assert chapters[0]["requirement_ids"] == [implementation]
    assert chapters[1]["requirement_ids"] == [training]


def test_strict_template_does_not_fall_back_to_generated_outline():
    assert ProposalPlanService._template_chapters(
        {"outline": [{"title": "格式1 投标函", "level": 1}]},
        [],
        {
            "writing_section_patterns": ["技术方案"],
            "non_writing_section_patterns": ["投标函"],
        },
    ) == []


def test_strict_field_only_template_is_a_valid_empty_writing_outline():
    chapters = ProposalPlanService._template_chapters(
        {
            "outline": [
                {"title": "格式1 投标函", "level": 1},
                {"title": "格式2 法定代表人身份证明", "level": 1},
                {"title": "格式3 报价表", "level": 1},
            ]
        },
        [],
        {
            "writing_section_patterns": ["技术方案", "实施方案"],
            "non_writing_section_patterns": ["投标函", "身份证明", "报价表"],
        },
    )

    assert chapters == []


def test_reconcile_feedback_restores_requirement_to_mapped_draft(
    monkeypatch,
):
    project_id = uuid4()
    requirement_id = uuid4()
    section_id = uuid4()

    class Cursor:
        def __init__(self):
            self.calls = []
            self.results = [
                {
                    "status": "confirmed",
                    "response_action": "write_into_proposal",
                    "proposal_mapping": "实施计划",
                },
                {"id": section_id},
            ]

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def execute(self, sql, params):
            self.calls.append((sql, params))

        def fetchone(self):
            return self.results.pop(0)

    cursor = Cursor()

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def cursor(self, **_kwargs):
            return cursor

    monkeypatch.setattr(
        "app.services.proposal_plan_service.connect",
        lambda: Connection(),
    )
    monkeypatch.setattr(
        "app.services.proposal_plan_service.SectionService.list",
        lambda _self, _project_id: [],
    )

    ProposalPlanService().reconcile_requirement_feedback(
        project_id,
        requirement_id,
    )

    statements = [sql for sql, _params in cursor.calls]
    assert any(
        "DELETE FROM section_requirements" in sql for sql in statements
    )
    assert any(
        "INSERT INTO section_requirements" in sql for sql in statements
    )
    assert any(
        params == (project_id, "实施计划")
        for _sql, params in cursor.calls
    )


def test_reconcile_feedback_only_removes_ignored_requirement(monkeypatch):
    project_id = uuid4()
    requirement_id = uuid4()

    class Cursor:
        def __init__(self):
            self.calls = []

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def execute(self, sql, params):
            self.calls.append((sql, params))

        def fetchone(self):
            return {
                "status": "rejected",
                "response_action": "ignore",
                "proposal_mapping": "实施计划",
            }

    cursor = Cursor()

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def cursor(self, **_kwargs):
            return cursor

    monkeypatch.setattr(
        "app.services.proposal_plan_service.connect",
        lambda: Connection(),
    )
    monkeypatch.setattr(
        "app.services.proposal_plan_service.SectionService.list",
        lambda _self, _project_id: [],
    )

    ProposalPlanService().reconcile_requirement_feedback(
        project_id,
        requirement_id,
    )

    statements = [sql for sql, _params in cursor.calls]
    assert any(
        "DELETE FROM section_requirements" in sql for sql in statements
    )
    assert not any(
        "INSERT INTO section_requirements" in sql for sql in statements
    )
