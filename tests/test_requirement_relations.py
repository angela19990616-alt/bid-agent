from app.core.requirement_relations import RequirementRelationEngine


def test_authorization_requirement_separates_entities_relations_and_actions():
    graph = RequirementRelationEngine().analyze(
        "投标人法定代表人应签字，授权代表应提交授权委托书并附身份证复印件。"
    )

    relations = {
        (item.subject, item.predicate, item.object)
        for item in graph.relations
    }
    assert (
        "legal_representative", "represents", "supplier"
    ) in relations
    assert (
        "authorized_representative", "authorized_by", "supplier"
    ) in relations
    assert (
        "authorization_letter", "proves_authorization_of",
        "authorized_representative",
    ) in relations
    assert "sign" in {item.action for item in graph.actions}
    assert "provide" in {item.action for item in graph.actions}
    assert "签字" in graph.constraints


def test_stamp_is_a_constraint_not_a_business_entity():
    graph = RequirementRelationEngine().analyze("供应商须加盖公章。")

    assert "stamp" in {item.action for item in graph.actions}
    assert all(item.key != "stamp" for item in graph.entities)


def test_legal_person_alias_builds_same_relation():
    graph = RequirementRelationEngine().analyze("法人应代表供应商签署响应文件。")

    assert any(
        item.subject == "legal_representative"
        and item.object == "supplier"
        for item in graph.relations
    )
