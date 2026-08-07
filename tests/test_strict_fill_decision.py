from app.core.strict_fill import (
    DataSensitivity,
    EnterpriseFact,
    FillStatus,
    StrictFillDecisionEngine,
    TemplateField,
)


FIELD = TemplateField(
    field_id="field-1",
    label="法定代表人",
    canonical_key="legal_representative",
    required=True,
    source_location="第七章/格式1/封面",
)


def test_verified_enterprise_fact_can_be_auto_filled():
    decision = StrictFillDecisionEngine().decide(
        FIELD,
        [
            EnterpriseFact(
                canonical_key="legal_representative",
                value="张三",
                source_type="company_registry",
                source_reference="工商信息快照-2026-08-08",
                confidence=1.0,
                verified=True,
            )
        ],
    )

    assert decision.status == FillStatus.AUTO_FILL
    assert decision.value == "张三"
    assert decision.source_reference == "工商信息快照-2026-08-08"


def test_missing_fact_is_never_invented():
    decision = StrictFillDecisionEngine().decide(FIELD, [])

    assert decision.status == FillStatus.MISSING
    assert decision.value is None
    assert "不存在" in decision.reason


def test_sensitive_fact_always_requires_review():
    decision = StrictFillDecisionEngine().decide(
        FIELD,
        [
            EnterpriseFact(
                canonical_key="legal_representative",
                value="张三",
                source_type="controlled_personnel_vault",
                source_reference="person-001",
                confidence=1.0,
                verified=True,
                sensitivity=DataSensitivity.HIGHLY_SENSITIVE,
            )
        ],
    )

    assert decision.status == FillStatus.REVIEW_REQUIRED
    assert "敏感数据" in decision.reason


def test_conflicting_values_require_human_decision():
    facts = [
        EnterpriseFact(
            canonical_key="legal_representative",
            value=value,
            source_type="company_profile",
            source_reference=source,
            confidence=1.0,
            verified=True,
        )
        for value, source in (("张三", "profile-v1"), ("李四", "profile-v2"))
    ]

    decision = StrictFillDecisionEngine().decide(FIELD, facts)

    assert decision.status == FillStatus.REVIEW_REQUIRED
    assert decision.value is None
    assert "多个不同值" in decision.reason


def test_historical_case_cannot_be_used_as_enterprise_fact():
    decision = StrictFillDecisionEngine().decide(
        FIELD,
        [
            EnterpriseFact(
                canonical_key="legal_representative",
                value="历史文件中的某人",
                source_type="historical_case",
                source_reference="private-case-1",
                confidence=1.0,
                verified=True,
            )
        ],
    )

    assert decision.status == FillStatus.MISSING
    assert decision.value is None
    assert "仅可参考写法" in decision.reason
