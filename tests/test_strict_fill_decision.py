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


def test_enterprise_fact_without_precise_evidence_requires_review():
    decision = StrictFillDecisionEngine().decide(
        FIELD,
        [
            EnterpriseFact(
                canonical_key="legal_representative",
                value="张三",
                source_type="company_profile",
                source_reference="企业资料库",
                confidence=1.0,
                verified=True,
                evidence_title="企业工商资料.pdf",
            )
        ],
    )

    assert decision.status == FillStatus.REVIEW_REQUIRED
    assert "缺少页码、章节或附件位置" in decision.reason


def test_person_field_rejects_a_label_as_the_value():
    decision = StrictFillDecisionEngine().decide(
        FIELD,
        [
            EnterpriseFact(
                canonical_key="legal_representative",
                value="法人或授权代表",
                source_type="company_profile",
                source_reference="企业资料库",
                confidence=1.0,
                verified=True,
            )
        ],
    )

    assert decision.status == FillStatus.MISSING
    assert decision.value is None
    assert "不符合字段类型" in decision.reason


def test_person_field_accepts_a_real_name_with_middle_dot():
    assert StrictFillDecisionEngine.value_matches_field_type(
        "authorized_representative", "阿依古丽·艾力"
    ) is True


def test_common_template_fields_must_match_their_semantic_types():
    valid = {
        "project_number": "SCXHR2025-0320",
        "bidder_name": "北京大岳咨询有限责任公司",
        "postal_code": "100032",
        "contact_phone": "13800138000",
        "fax": "010-12345678",
        "website": "https://example.com",
        "bank_account": "123456789012",
        "date": "2026年8月9日",
        "registered_address": "北京市西城区某大街1号",
        "bid_round": "第二轮",
    }
    invalid = {
        "project_number": "项目编号",
        "bidder_name": "供应商名称",
        "postal_code": "邮政编码",
        "contact_phone": "联系电话",
        "fax": "请填写",
        "website": "公司网址",
        "bank_account": "银行账号",
        "date": "年月日",
        "registered_address": "注册地址",
        "bid_round": "报价轮次",
    }

    for key, value in valid.items():
        assert StrictFillDecisionEngine.value_matches_field_type(key, value)
    for key, value in invalid.items():
        assert not StrictFillDecisionEngine.value_matches_field_type(key, value)


def test_field_type_labels_are_business_readable():
    assert StrictFillDecisionEngine.field_type_label(
        "legal_representative"
    ) == "姓名"
    assert StrictFillDecisionEngine.field_type_label("contact_phone") == "电话号码"


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
