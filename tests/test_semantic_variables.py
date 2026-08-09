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


def _resolved_decision(field_key: str, slot, entity_id, value: str) -> dict:
    return {
        **_decision(field_key, slot, value),
        "resolved_entity_type": "Person",
        "resolved_entity_id": str(entity_id),
    }


def _missing_decision(field_key: str, slot) -> dict:
    return {
        **_decision(field_key, slot, ""),
        "value": None,
        "source_type": None,
        "source_reference": None,
        "status": "MISSING",
        "reason": "尚未找到可信值。",
        "binding_status": "not_found",
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


def test_same_bound_person_attribute_collapses_across_role_aliases():
    person_id = uuid4()
    legal = _slot("法定代表人姓名", "法定代表人：___", "第3页")
    signatory = SlotContextClassifier.classify(
        label="签署人姓名",
        surrounding_text="签署人姓名：___",
        source_location="第8页",
        document_section="投标函",
    )

    variables = SlotDeduplicationEngine.group_decisions([
        _resolved_decision("legal_representative", legal, person_id, "张三"),
        _resolved_decision("signatory_name", signatory, person_id, "张三"),
    ])

    assert len(variables) == 1
    assert variables[0]["slot_count"] == 2
    assert set(variables[0]["target_relations"]) == {
        "LEGAL_REPRESENTATIVE", "SIGNATORY",
    }


def test_equal_text_from_different_people_does_not_collapse():
    first = _slot("法定代表人姓名", "法定代表人：___", "第3页")
    second = SlotContextClassifier.classify(
        label="授权代表姓名",
        surrounding_text="授权代表姓名：___",
        source_location="第4页",
        document_section="授权委托书",
    )

    variables = SlotDeduplicationEngine.group_decisions([
        _resolved_decision("legal_representative", first, uuid4(), "张三"),
        _resolved_decision("authorized_representative", second, uuid4(), "张三"),
    ])

    assert len(variables) == 2


def test_bound_entity_variable_key_never_exposes_internal_identifier():
    person_id = uuid4()
    slot = _slot("法定代表人姓名", "法定代表人：___", "第3页")

    variable = SlotDeduplicationEngine.group_decisions([
        _resolved_decision("legal_representative", slot, person_id, "张三"),
    ])[0]

    assert str(person_id) not in variable["variable_key"]
    assert "custom_" not in variable["variable_key"]
    assert variable["variable_key"].startswith("entity_fact.person.")


def test_preview_manual_override_is_project_scoped_and_wins_for_rendering():
    project_id = uuid4()
    organization_id = uuid4()
    legal_id = uuid4()
    slot = _slot("法定代表人姓名", "法定代表人：___", "第3页")
    profile = GenerationProfile(
        project_id=project_id,
        generation_mode="strict_template",
        historical_case_mode="closest_case",
        template_descriptor={
            "fields": [{
                "field_key": "legal_representative",
                "label": slot.display_name,
                **slot.snapshot(),
            }]
        },
        template_field_values={"legal_representative": "李四"},
        last_fill_report={
            "field_reviews": {
                "legal_representative": {
                    "status": "confirmed",
                    "value": "李四",
                    "source_reference": "本项目人工修正",
                    "evidence_excerpt": "本项目人工修正：李四",
                    "evidence_location": "严格回填预览人工审核",
                }
            }
        },
    )
    context = EntityResolutionContext(
        project_id=project_id,
        organization=Organization(
            id=organization_id,
            full_name="测试公司",
            legal_representative_person_id=legal_id,
        ),
        people=(Person(id=legal_id, name="张三"),),
    )

    variables = GenerationProfileService.template_variable_decisions(
        profile, entity_context=context
    )

    assert variables[0]["value"] == "李四"
    assert variables[0]["source_type"] == "manual_verified"
    assert variables[0]["status"] == "AUTO_FILL"
    assert variables[0]["evidence_excerpt"] == "本项目人工修正：李四"
    assert variables[0]["evidence_location"] == "严格回填预览人工审核"


def test_recognized_person_slot_is_pending_binding_not_unknown_semantics():
    name = SlotContextClassifier.classify(
        label="姓名",
        surrounding_text="项目团队人员表 姓名：___",
        source_location="表格1第2行第1列",
        document_section="项目团队人员表",
        table_index=0,
        row=1,
        column=0,
    )
    title = SlotContextClassifier.classify(
        label="职务",
        surrounding_text="项目团队人员表 职务：___",
        source_location="表格1第2行第2列",
        document_section="项目团队人员表",
        table_index=0,
        row=1,
        column=1,
    )

    variables = SlotDeduplicationEngine.group_decisions([
        _missing_decision("person_name", name),
        _missing_decision("person_title", title),
    ])

    assert {item["resolution_state"] for item in variables} == {
        "person_binding_pending"
    }
    assert all(item["semantics_recognized"] for item in variables)
    assert len({item["review_group_key"] for item in variables}) == 1


def test_recognized_organization_slot_is_waiting_for_enterprise_fact():
    slot = SlotContextClassifier.classify(
        label="投标人名称",
        surrounding_text="投标人名称：___",
        source_location="第2页第3段",
        document_section="投标函",
    )

    variable = SlotDeduplicationEngine.group_decisions([
        _missing_decision("bidder_name", slot),
    ])[0]

    assert variable["semantics_recognized"] is True
    assert variable["resolution_state"] == "enterprise_fact_pending"
    assert variable["resolution_label"] == "待匹配企业资料"


def test_response_content_waits_for_generation_not_semantic_review():
    slot = SlotContextClassifier.classify(
        label="备注",
        surrounding_text="商务条款响应表 备注：___",
        source_location="表格3第2行第4列",
        document_section="商务条款响应表",
    )

    variable = SlotDeduplicationEngine.group_decisions([
        _missing_decision("response_notes", slot),
    ])[0]

    assert variable["semantic_field"] == "bid_response.content"
    assert variable["resolution_state"] == "response_generation_pending"
    assert variable["resolution_label"] == "待生成响应内容"


def test_only_genuinely_unmapped_slot_requires_semantic_review():
    slot = SlotContextClassifier.classify(
        label="响应内容",
        surrounding_text="技术要求响应表 响应内容：___",
        source_location="表格4第2行第3列",
        document_section="技术要求响应表",
    )

    variable = SlotDeduplicationEngine.group_decisions([
        _missing_decision("unmapped_response", slot),
    ])[0]

    assert variable["semantic_field"] == "text.value"
    assert variable["semantics_recognized"] is False
    assert variable["resolution_state"] == "semantic_review_required"
    assert variable["resolution_label"] == "需要确认字段含义"
