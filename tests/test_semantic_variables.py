from uuid import uuid4

from app.core.entity_resolution import (
    EntityResolutionContext,
    Organization,
    Person,
    SlotContextClassifier,
)
from app.core.semantic_variables import (
    SlotDeduplicationEngine,
    VariableDictionary,
)
from app.services.generation_profile_service import (
    GenerationProfile,
    GenerationProfileService,
)


def _decision(field_key: str, slot, value: str = "张三") -> dict:
    return {
        "field_key": field_key,
        "canonical_key": slot.canonical_key,
        "label": slot.display_name,
        "display_name": slot.display_name,
        "expected_value_type": slot.expected_value_type,
        "expected_value_type_label": "姓名",
        "value": value,
        "source_type": "entity_registry",
        "source_reference": "企业人员档案",
        "confidence": 1.0,
        "status": "AUTO_FILL",
        "reason": "来源已核验，可以自动回填。",
        "required": True,
        "slot": slot.snapshot(),
        "semantic_field": slot.semantic_field,
        "expected_entity_type": "Person",
        "expected_role": slot.expected_role.value if slot.expected_role else None,
        "binding_status": "resolved",
        "relation_path": list(slot.relation_path),
        "entity_candidates": [],
        "fill_strategy": slot.fill_strategy.value,
    }


def _slot(
    label: str,
    context: str,
    location: str,
    section: str = "法定代表人身份证明",
):
    return SlotContextClassifier.classify(
        label=label,
        surrounding_text=context,
        source_location=location,
        document_section=section,
    )


def test_dictionary_collapses_legal_representative_aliases_into_one_variable():
    first = _slot("法人代表姓名", "法人代表姓名：___", "第3页第2段")
    second = _slot("法定代表人", "法定代表人：___", "第5页表格1")

    variables = SlotDeduplicationEngine.group_decisions([
        _decision("legal_representative", first),
        _decision("legal_representative__second", second),
    ])

    assert len(variables) == 1
    assert variables[0]["variable_key"] == (
        "organization.legal_representative.name"
    )
    assert variables[0]["slot_count"] == 2
    assert variables[0]["value"] == "张三"
    assert variables[0]["affected_locations"] == [
        "第3页第2段", "第5页表格1",
    ]


def test_legal_and_authorized_representatives_never_merge():
    legal = _slot("法定代表人姓名", "法定代表人姓名：___", "第3页")
    authorized = SlotContextClassifier.classify(
        label="授权代表姓名",
        surrounding_text="现委托___（姓名）为我方授权代表",
        source_location="第4页",
        document_section="授权委托书",
    )

    variables = SlotDeduplicationEngine.group_decisions([
        _decision("legal_representative", legal),
        _decision("authorized_representative", authorized, "李四"),
    ])

    assert {item["variable_key"] for item in variables} == {
        "organization.legal_representative.name",
        "project.authorized_representative.name",
    }


def test_unbound_generic_people_stay_separate_until_role_is_known():
    first = _slot(
        "姓名", "人员一 姓名：___", "表格1第2行", "项目团队人员表"
    )
    second = _slot(
        "姓名", "人员二 姓名：___", "表格1第3行", "项目团队人员表"
    )

    definitions = {
        VariableDictionary.resolve(first).variable_key,
        VariableDictionary.resolve(second).variable_key,
    }

    assert len(definitions) == 2


def test_entity_change_updates_every_slot_bound_to_the_variable():
    project_id = uuid4()
    organization_id = uuid4()
    legal_id = uuid4()
    slots = [
        _slot("法人代表姓名", "法人代表姓名：___", "第3页"),
        _slot("法定代表人", "法定代表人：___", "第5页"),
    ]
    profile = GenerationProfile(
        project_id=project_id,
        generation_mode="strict_template",
        historical_case_mode="closest_case",
        template_descriptor={
            "fields": [
                {
                    "field_key": (
                        "legal_representative"
                        if index == 0 else "legal_representative__second"
                    ),
                    "label": slot.display_name,
                    **slot.snapshot(),
                }
                for index, slot in enumerate(slots)
            ]
        },
        template_field_values={},
    )

    def context(name: str) -> EntityResolutionContext:
        return EntityResolutionContext(
            project_id=project_id,
            organization=Organization(
                id=organization_id,
                full_name="测试公司",
                legal_representative_person_id=legal_id,
            ),
            people=(Person(id=legal_id, name=name),),
        )

    before = GenerationProfileService.template_variable_decisions(
        profile, entity_context=context("张三")
    )
    after = GenerationProfileService.template_variable_decisions(
        profile, entity_context=context("李四")
    )

    assert before[0]["slot_count"] == 2
    assert before[0]["value"] == "张三"
    assert after[0]["value"] == "李四"
    assert {
        item["value"]
        for item in SlotDeduplicationEngine.fan_out(after)
    } == {"李四"}
