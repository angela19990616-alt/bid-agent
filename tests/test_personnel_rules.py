from datetime import date
from uuid import uuid4

from app.core.entity_resolution import Person, ProjectRole
from app.core.personnel_rules import PersonnelEntityRuleEngine, PersonnelRule


def test_personnel_rule_auto_fills_only_when_all_evidence_is_valid():
    person = Person(
        id=uuid4(),
        name="张三",
        employment_history=({
            "status": "active",
            "valid_from": "2020-01-01",
        },),
        role_history=({
            "role": "项目经理",
            "start_date": "2018-01-01",
        },),
        certification_history=({
            "name": "一级建造师",
            "status": "valid",
            "valid_to": "2030-12-31",
        },),
    )
    rule = PersonnelRule(
        role=ProjectRole.PROJECT_MANAGER,
        required_certificates=("一级建造师",),
        minimum_experience_years=5,
    )

    result = PersonnelEntityRuleEngine().evaluate(
        person, rule, as_of=date(2026, 8, 9)
    )

    assert result.status == "AUTO_FILL"
    assert result.eligible is True
    assert all(item["passed"] for item in result.checks)


def test_personnel_rule_requires_review_when_certificate_or_history_is_missing():
    person = Person(id=uuid4(), name="李四")
    rule = PersonnelRule(
        role=ProjectRole.PROJECT_MANAGER,
        required_certificates=("一级建造师",),
        minimum_experience_years=5,
    )

    result = PersonnelEntityRuleEngine().evaluate(person, rule)

    assert result.status == "REVIEW_REQUIRED"
    assert result.eligible is False
    assert any(not item["known"] for item in result.checks)
