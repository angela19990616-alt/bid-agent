import json

from app.core.entity_resolution import DocumentSlot, SlotContextClassifier
from app.core.semantic_variables import VariableDictionary
from app.services.slot_semantic_resolution_service import (
    SlotSemanticResolutionService,
)


class FakeModelClient:
    def __init__(self, slots):
        self.slots = slots
        self.calls = []

    def chat(self, messages, **kwargs):
        self.calls.append((messages, kwargs))
        return json.dumps({"slots": self.slots}, ensure_ascii=False)


def _field(
    label: str,
    context: str,
    location: str,
    *,
    section: str = "授权委托书",
):
    slot = SlotContextClassifier.classify(
        label=label,
        surrounding_text=context,
        source_location=location,
        document_section=section,
        paragraph_index=1,
    )
    return {
        **slot.snapshot(),
        "field_key": slot.canonical_key,
        "label": label,
        "required": True,
    }


def test_ai_understands_person_role_from_whole_sentence_before_fill():
    original = _field(
        "姓名",
        "现委托【当前空位：姓名】为我方代理人，参加本项目投标活动。",
        "授权委托书第3段",
    )
    client = FakeModelClient([{
        "group_id": "G001",
        "concept_id": "person_name",
        "role": "AUTHORIZED_REPRESENTATIVE",
        "confidence": 0.96,
        "reason": "完整句子说明该人员由投标人针对本项目授权。",
    }])

    result = SlotSemanticResolutionService(client).resolve([original])

    field = result.fields[0]
    assert field["semantic_field"] == "person.name"
    assert field["expected_role"] == "AUTHORIZED_REPRESENTATIVE"
    assert field["canonical_key"] == "authorized_representative"
    assert field["display_name"] == "本项目授权代表姓名"
    assert field["semantic_resolution"]["source"] == "ai_resolved"
    assert result.report["status"] == "completed"
    assert client.calls[0][1]["task"] == "classification"


def test_repeated_dates_share_one_ai_concept_and_one_business_variable():
    first = _field(
        "日期",
        "投标人（盖章）：____ 日期：【当前空位：日期】",
        "投标函第8段",
        section="投标函",
    )
    second = {
        **first,
        "slot_id": "second-date-slot",
        "source_location": "投标函第12段",
    }
    client = FakeModelClient([{
        "group_id": "G001",
        "concept_id": "signing_date",
        "role": None,
        "confidence": 0.98,
        "reason": "两处均位于投标文件签署区。",
    }])

    result = SlotSemanticResolutionService(client).resolve([first, second])
    definitions = [
        VariableDictionary.resolve(DocumentSlot.from_snapshot(item))
        for item in result.fields
    ]

    assert len(client.calls) == 1
    assert {item["semantic_field"] for item in result.fields} == {
        "bid_response.signing_date"
    }
    assert {item.variable_key for item in definitions} == {
        "bid_response.signing_date"
    }


def test_ai_cannot_turn_an_ordinary_value_into_a_document_action():
    original = _field(
        "项目名称",
        "项目名称：【当前空位：项目名称】",
        "封面第1段",
        section="封面",
    )
    client = FakeModelClient([{
        "group_id": "G001",
        "concept_id": "action_only",
        "role": None,
        "confidence": 0.99,
        "reason": "错误地认为这是动作。",
    }])

    result = SlotSemanticResolutionService(client).resolve([original])

    assert len(result.fields) == 1
    assert not result.actions
    assert result.fields[0]["semantic_resolution"]["source"] == (
        "deterministic_fallback"
    )
    assert result.fields[0]["semantic_resolution"][
        "requires_human_review"
    ] is True
    assert result.report["rejected_slot_count"] == 1


def test_low_confidence_or_malformed_ai_never_replaces_safe_mapping():
    original = _field(
        "供应商名称",
        "供应商名称：【当前空位：供应商名称】",
        "响应函第2段",
        section="响应函",
    )
    original["confidence"] = 0.65
    low_confidence = FakeModelClient([{
        "group_id": "G001",
        "concept_id": "project_name",
        "role": None,
        "confidence": 0.4,
        "reason": "判断不确定。",
    }])
    low = SlotSemanticResolutionService(low_confidence).resolve([original])

    class BrokenModelClient:
        @staticmethod
        def chat(*_args, **_kwargs):
            return "not json"

    broken = SlotSemanticResolutionService(BrokenModelClient()).resolve(
        [original]
    )

    assert low.fields[0]["semantic_field"] == "organization.full_name"
    assert low.report["status"] == "review_required"
    assert low.fields[0]["semantic_resolution"][
        "requires_human_review"
    ] is True
    assert broken.fields[0]["semantic_field"] == "organization.full_name"
    assert broken.report["status"] == "failed_fallback"
    assert broken.fields[0]["semantic_resolution"][
        "requires_human_review"
    ] is True


def test_ai_uncertain_marks_slot_for_human_semantic_review():
    original = _field(
        "名称",
        "兹授权【当前空位：名称】办理本项目相关事项。",
        "授权委托书第4段",
    )
    client = FakeModelClient([{
        "group_id": "G001",
        "concept_id": "uncertain",
        "role": None,
        "confidence": 0.72,
        "reason": "上下文无法判断是人员姓名还是机构名称。",
    }])

    result = SlotSemanticResolutionService(client).resolve([original])

    assert result.fields[0]["semantic_resolution"]["source"] == (
        "human_review_required"
    )
    assert result.fields[0]["semantic_resolution"][
        "requires_human_review"
    ] is True
    assert result.report["status"] == "review_required"


def test_table_rows_with_different_context_are_resolved_independently():
    manager = _field(
        "姓名",
        "项目负责人｜【当前空位：姓名】｜咨询工程师",
        "人员表第2行第2列",
        section="项目团队人员表",
    )
    manager.update({"table_index": 0, "row": 1, "column": 1})
    lead = _field(
        "姓名",
        "技术负责人｜【当前空位：姓名】｜高级工程师",
        "人员表第3行第2列",
        section="项目团队人员表",
    )
    lead.update({"table_index": 0, "row": 2, "column": 1})
    client = FakeModelClient([
        {
            "group_id": "G001",
            "concept_id": "person_name",
            "role": "PROJECT_MANAGER",
            "confidence": 0.97,
            "reason": "所在行明确为项目负责人。",
        },
        {
            "group_id": "G002",
            "concept_id": "person_name",
            "role": "TECHNICAL_LEAD",
            "confidence": 0.97,
            "reason": "所在行明确为技术负责人。",
        },
    ])

    result = SlotSemanticResolutionService(client).resolve([manager, lead])

    assert [item["expected_role"] for item in result.fields] == [
        "PROJECT_MANAGER",
        "TECHNICAL_LEAD",
    ]
    sent_slots = json.loads(client.calls[0][0][1]["content"])["slots"]
    assert len(sent_slots) == 2


def test_model_receives_context_and_concepts_but_never_a_value_to_fill():
    original = _field(
        "姓名",
        "本人【当前空位：姓名】系投标人的法定代表人。",
        "法定代表人证明第2段",
    )
    client = FakeModelClient([{
        "group_id": "G001",
        "concept_id": "person_name",
        "role": "LEGAL_REPRESENTATIVE",
        "confidence": 0.97,
        "reason": "句子明示法定代表人关系。",
    }])

    SlotSemanticResolutionService(client).resolve([original])

    prompt = client.calls[0][0][1]["content"]
    assert "法定代表人" in prompt
    assert "person_name" in prompt
    assert "只判断空位指向的业务概念" not in prompt
    assert "value" not in json.loads(prompt)["output_schema"]["slots"][0]
