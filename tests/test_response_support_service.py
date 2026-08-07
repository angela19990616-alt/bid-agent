from types import SimpleNamespace
from uuid import uuid4

from app.services.response_support_service import ResponseSupportService


def requirement(**overrides):
    item = {
        "id": uuid4(),
        "title": "实施进度要求",
        "normalized_text": "实施周期为180日历天",
        "quote": "项目实施周期为180日历天。",
        "type": "delivery_requirement",
        "response_action": "write_into_proposal",
        "proposal_mapping": "实施计划",
        "priority": "P2",
        "proposal_value": 3,
        "sources": [],
    }
    item.update(overrides)
    return item


class FakeRequirements:
    def __init__(self, items):
        self.items = items

    def list(self, _project_id):
        return self.items


class FakeKnowledge:
    @staticmethod
    def access_context(project_id):
        return SimpleNamespace(workspace_id=project_id)

    @staticmethod
    def list_active(_context):
        return [
            {
                "id": uuid4(),
                "category": "qualification",
                "title": "张三高级工程师证书",
                "content": "张三具有高级工程师职称，专业为工程咨询。",
                "metadata": {
                    "verified_enterprise_fact": True,
                    "holder": "张三",
                    "asset_reference": "private://qualification/zhangsan",
                },
            }
        ]

    @staticmethod
    def _terms(value):
        return {
            word for word in (
                "张三", "高级工程师", "工程咨询", "实施周期", "180日历天"
            ) if word in value
        }


class FakeSections:
    @staticmethod
    def list(_project_id):
        return [
            {
                "id": uuid4(),
                "title": "实施计划",
                "requirement_ids": [],
                "current_version": {
                    "content": "本项目按照准备、实施和验收三个阶段推进。",
                    "origin": "generated",
                },
            }
        ]


class FakeGenerationProfile:
    @staticmethod
    def get(_project_id):
        return SimpleNamespace(
            template_descriptor={
                "field_labels": ["项目编号", "供应商名称"],
            },
            template_field_values={"project_number": "SCXHR20250320"},
        )


class FakeConflicts:
    @staticmethod
    def list(_project_id):
        return []


def make_service(items):
    return ResponseSupportService(
        requirement_service=FakeRequirements(items),
        knowledge_engine=FakeKnowledge(),
        section_service=FakeSections(),
        generation_profile_service=FakeGenerationProfile(),
        conflict_service=FakeConflicts(),
    )


def test_support_groups_fine_requirements_for_user_display():
    items = [requirement(), requirement(title="进度控制措施")]
    service = make_service(items)

    result = service.overview(uuid4())

    assert len(result["response_groups"]) == 1
    assert result["response_groups"][0]["item_count"] == 2
    assert result["response_groups"][0]["target_chapter"] == "实施计划"


def test_support_marks_exact_format_and_matches_verified_qualification():
    items = [
        requirement(
            type="format_requirement",
            title="附件格式",
            normalized_text="严格按照附件表格填写，不得修改格式",
            quote="投标人须严格按照附件表格填写，不得修改格式。",
            response_action="write_into_response_table",
            proposal_mapping=None,
        ),
        requirement(
            type="qualification_requirement",
            title="人员职称",
            normalized_text="项目负责人须具有工程咨询高级工程师职称",
            quote="项目负责人须具有高级工程师职称。",
            response_action="provide_attachment",
            proposal_mapping=None,
        ),
    ]
    service = make_service(items)

    result = service.overview(uuid4())

    assert result["format_requirements"][0]["fidelity"] == "exact_template"
    qualification = result["qualification_responses"][0]
    assert qualification["status"] == "matched_verified"
    assert qualification["matches"][0]["holder"] == "张三"
    assert "content" not in qualification["matches"][0]


def test_manual_archive_collects_variables_and_human_reviews():
    items = [
        requirement(
            type="format_requirement",
            title="固定响应表",
            normalized_text="严格按照附件表格填写，不得修改格式",
            quote="须严格按照附件表格填写。",
            response_action="write_into_response_table",
            proposal_mapping=None,
        ),
        requirement(
            type="qualification_requirement",
            title="未匹配资格",
            normalized_text="须提供法律职业资格证书",
            quote="须提供法律职业资格证书。",
            response_action="provide_attachment",
            proposal_mapping=None,
        ),
    ]
    service = make_service(items)
    service.knowledge_engine.list_active = lambda _context: []

    archive = service.overview(uuid4())["manual_action_archive"]

    variables = {
        item["title"]: item["status"]
        for item in archive["items"]
        if item["category"] == "variable"
    }
    assert variables == {"项目编号": "completed", "供应商名称": "pending"}
    assert any(
        item["category"] == "format_review"
        for item in archive["items"]
    )
    assert any(
        item["category"] == "material_review"
        for item in archive["items"]
    )
    assert archive["pending"] >= 3
