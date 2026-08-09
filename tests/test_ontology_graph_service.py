import json
from uuid import uuid4

from app.core.entity_resolution import (
    EntityResolutionContext,
    Organization,
    Person,
    ProjectRole,
    ProjectRoleAssignment,
    SlotContextClassifier,
)
from app.services.generation_profile_service import GenerationProfile
from app.services.ontology_graph_service import OntologyGraphService


def _profile(project_id):
    bidder_slot = SlotContextClassifier.classify(
        label="投标人名称",
        surrounding_text="投标人名称：【当前空位】",
        source_location="格式1/第3段",
        document_section="第七章 响应文件格式 / 格式1 投标函",
        canonical_hint="bidder_name",
    )
    representative_slot = SlotContextClassifier.classify(
        label="姓名",
        surrounding_text="法定代表人【当前空位：姓名】",
        source_location="格式2/第5段",
        document_section="第七章 响应文件格式 / 格式2 法定代表人身份证明",
    )
    fields = [
        {
            "field_key": "bidder_name",
            "label": "投标人名称",
            **bidder_slot.snapshot(),
        },
        {
            "field_key": "bidder_name__second",
            "label": "投标人名称",
            "source_location": "格式1/第8段",
            **bidder_slot.snapshot(),
        },
        {
            "field_key": "legal_representative",
            "label": "姓名",
            **representative_slot.snapshot(),
        },
    ]
    return GenerationProfile(
        project_id=project_id,
        generation_mode="strict_template",
        historical_case_mode="closest_case",
        template_descriptor={
            "fields": fields,
            "actions": [{
                "display_name": "加盖投标人公章",
                "source_location": "格式1/签章处",
            }],
        },
        template_field_values={},
    )


def test_graph_groups_repeated_slots_and_never_exposes_database_ids():
    project_id = uuid4()
    organization_id = uuid4()
    person_id = uuid4()
    context = EntityResolutionContext(
        project_id=project_id,
        project_name="测试采购项目",
        organization=Organization(
            id=organization_id,
            full_name="测试咨询公司",
            legal_representative_person_id=person_id,
        ),
        people=(Person(id=person_id, name="张三", title="法定代表人"),),
        assignments=(ProjectRoleAssignment(
            project_id=project_id,
            organization_id=organization_id,
            role=ProjectRole.LEGAL_REPRESENTATIVE,
            person_id=person_id,
        ),),
    )

    graph = OntologyGraphService.build_graph(context, _profile(project_id))
    serialized = json.dumps({
        "nodes": graph.nodes,
        "edges": graph.edges,
    }, ensure_ascii=False)

    bidder_slots = [
        node for node in graph.nodes
        if node["kind"] == "slot" and node["label"] == "当前项目投标人名称"
    ]
    assert len(bidder_slots) == 1
    assert bidder_slots[0]["subtitle"] == "2 处原模板位置"
    assert "测试咨询公司" in serialized
    assert "张三" in serialized
    assert str(project_id) not in serialized
    assert str(organization_id) not in serialized
    assert str(person_id) not in serialized
    assert "custom_" not in serialized


def test_slot_links_to_expected_business_role_and_original_directory():
    project_id = uuid4()
    context = EntityResolutionContext(
        project_id=project_id,
        project_name="测试项目",
    )

    graph = OntologyGraphService.build_graph(context, _profile(project_id))

    role = next(
        node for node in graph.nodes
        if node["kind"] == "role"
        and node["label"] == "法定代表人"
    )
    assert role["subtitle"] == "尚待当前项目绑定"
    assert any(
        edge["target"] == role["id"]
        and edge["relation"] == "EXPECTS_ROLE"
        for edge in graph.edges
    )
    assert any(
        node["kind"] == "section"
        and "格式2 法定代表人身份证明" in node["label"]
        for node in graph.nodes
    )
